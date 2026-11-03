import cv2
import numpy as np
import mediapipe as mp
import tkinter as tk
from tkinter import messagebox, font
from PIL import Image, ImageTk
import pandas as pd
import os
import threading
import time
from datetime import datetime
import urllib.request
import math

# ==========================================
# CONFIGURATION PARAMETERS
# ==========================================
EXCEL_FILE = "workers_track.xlsx"
ESP32_CAMERA_URL = "http://192.168.4.1/capture"
ESP32_PITCH_URL = "http://192.168.4.1/pitch?freq="

BREAK_DURATION_SECONDS = 300


# ==========================================
# GESTURE & POSTURE DETECTION CLASS
# ==========================================
class Detector:
    def __init__(self):
        # Posture
        self.mp_pose = mp.solutions.pose
        self.pose = self.mp_pose.Pose(
            static_image_mode=False, model_complexity=1,
            min_detection_confidence=0.5, min_tracking_confidence=0.5
        )
        self.mp_draw = mp.solutions.drawing_utils

        # Gestures (Hands)
        self.mp_hands = mp.solutions.hands
        self.hands = self.mp_hands.Hands(
            static_image_mode=False, max_num_hands=1,
            min_detection_confidence=0.7, min_tracking_confidence=0.7
        )

    def check_posture(self, frame):
        img_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        img_rgb.flags.writeable = False
        results = self.pose.process(img_rgb)
        img_rgb.flags.writeable = True
        frame = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2BGR)

        status = "No Person"
        if results.pose_landmarks:
            self.mp_draw.draw_landmarks(frame, results.pose_landmarks, self.mp_pose.POSE_CONNECTIONS)
            landmarks = results.pose_landmarks.landmark
            nose = landmarks[0]
            left_shoulder = landmarks[11]
            right_shoulder = landmarks[12]

            if left_shoulder.visibility > 0.5 and right_shoulder.visibility > 0.5:
                shoulder_mid_y = (left_shoulder.y + right_shoulder.y) / 2
                is_head_dropped = (nose.y > shoulder_mid_y - 0.1)
                is_nose_centered = abs(nose.x - ((left_shoulder.x + right_shoulder.x) / 2)) < 0.2
                in_zone = 0.2 < nose.x < 0.8 and 0.1 < nose.y < 0.8

                if is_head_dropped:
                    status = "Sleeping"
                elif is_nose_centered and in_zone and nose.y < left_shoulder.y:
                    status = "Working"
                else:
                    status = "Not Working"
            else:
                status = "Not Working"
        return status, frame

    def is_open_hand(self, hand_landmarks):
        # STRICT 5-FINGER CHECK: All 4 fingers + thumb must be extended
        fingers_extended = 0
        if hand_landmarks[8].y < hand_landmarks[6].y: fingers_extended += 1  # Index
        if hand_landmarks[12].y < hand_landmarks[10].y: fingers_extended += 1  # Middle
        if hand_landmarks[16].y < hand_landmarks[14].y: fingers_extended += 1  # Ring
        if hand_landmarks[20].y < hand_landmarks[18].y: fingers_extended += 1  # Pinky

        def dist(p1, p2):
            return math.hypot(p1.x - p2.x, p1.y - p2.y)

        thumb_extended = dist(hand_landmarks[4], hand_landmarks[0]) > dist(hand_landmarks[3], hand_landmarks[0])

        return (fingers_extended == 4 and thumb_extended)  # MUST be exactly 5 digits

    def is_thumbs_up(self, hand_landmarks):
        thumb_up = hand_landmarks[4].y < hand_landmarks[2].y
        fingers_curled = 0
        if hand_landmarks[8].y > hand_landmarks[6].y: fingers_curled += 1
        if hand_landmarks[12].y > hand_landmarks[10].y: fingers_curled += 1
        if hand_landmarks[16].y > hand_landmarks[14].y: fingers_curled += 1
        if hand_landmarks[20].y > hand_landmarks[18].y: fingers_curled += 1
        return thumb_up and (fingers_curled >= 3)


# ==========================================
# MAIN APPLICATION CLASS
# ==========================================
class WorkerTrackerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("ESP32 AI Worker Tracker")
        self.root.geometry("1200x800")
        self.root.configure(bg="#2c3e50")

        self.is_running = False
        self.on_break = False
        self.worker_id = None
        self.start_time = 0
        self.elapsed_work_time = 0
        self.elapsed_downtime = 0
        self.break_end_time = 0
        self.last_buzz_time = 0
        self.frame_count = 0

        self.detector = Detector()

        # Gesture State Machine
        self.hand_raise_start = 0
        self.awaiting_thumbs_up = False

        self.setup_gui()

    def setup_gui(self):
        title_font = font.Font(family="Helvetica", size=24, weight="bold")
        label_font = font.Font(family="Helvetica", size=14)
        timer_font = font.Font(family="Helvetica", size=48, weight="bold")
        btn_font = font.Font(family="Helvetica", size=12, weight="bold")

        header_frame = tk.Frame(self.root, bg="#2c3e50", pady=10)
        header_frame.pack(fill=tk.X)
        tk.Label(header_frame, text="ESP32 AI Gesture & Posture Tracker", font=title_font, bg="#2c3e50",
                 fg="white").pack()

        input_frame = tk.Frame(self.root, bg="#34495e", pady=20, padx=20)
        input_frame.pack(fill=tk.X, padx=20)
        tk.Label(input_frame, text="Worker ID:", font=label_font, bg="#34495e", fg="white").pack(side=tk.LEFT, padx=5)
        self.entry_id = tk.Entry(input_frame, font=label_font, width=20)
        self.entry_id.pack(side=tk.LEFT, padx=5)

        self.btn_start = tk.Button(input_frame, text="Start Work", font=btn_font, bg="#2ecc71", fg="white",
                                   command=self.start_work, width=12, relief=tk.FLAT)
        self.btn_start.pack(side=tk.LEFT, padx=10)
        self.btn_finish = tk.Button(input_frame, text="Finish Work", font=btn_font, bg="#e74c3c", fg="white",
                                    command=self.finish_work, width=12, relief=tk.FLAT, state=tk.DISABLED)
        self.btn_finish.pack(side=tk.LEFT, padx=10)
        self.btn_break = tk.Button(input_frame, text="Manual Break", font=btn_font, bg="#f1c40f", fg="black",
                                   command=self.request_break, width=12, relief=tk.FLAT, state=tk.DISABLED)
        self.btn_break.pack(side=tk.LEFT, padx=10)

        display_frame = tk.Frame(self.root, bg="#2c3e50")
        display_frame.pack(expand=True, fill=tk.BOTH, padx=20, pady=10)

        self.lbl_camera = tk.Label(display_frame, bg="#2c3e50", text="Camera Offline", fg="white")
        self.lbl_camera.pack(side=tk.LEFT, expand=True, fill=tk.BOTH, padx=10)

        info_panel = tk.Frame(display_frame, bg="#34495e", width=400)
        info_panel.pack(side=tk.RIGHT, fill=tk.Y, padx=10)
        info_panel.pack_propagate(False)

        self.lbl_timer = tk.Label(info_panel, text="00:00:00", font=timer_font, bg="#34495e", fg="#95a5a6")
        self.lbl_timer.pack(pady=30)
        self.lbl_status = tk.Label(info_panel, text="Status: IDLE", font=label_font, bg="#34495e", fg="white",
                                   wraplength=350)
        self.lbl_status.pack(pady=10)
        self.lbl_posture = tk.Label(info_panel, text="Posture: N/A", font=label_font, bg="#34495e", fg="white")
        self.lbl_posture.pack(pady=10)
        self.lbl_downtime = tk.Label(info_panel, text="Total Downtime: 0s", font=label_font, bg="#34495e", fg="#e74c3c")
        self.lbl_downtime.pack(pady=10)
        self.lbl_gesture = tk.Label(info_panel, text="Gesture: None", font=label_font, bg="#34495e", fg="#3498db")
        self.lbl_gesture.pack(pady=10)

    def start_work(self):
        wid = self.entry_id.get()
        if not wid:
            messagebox.showwarning("Input Error", "Please enter a Worker ID.")
            return

        self.worker_id = wid
        self.is_running = True
        self.on_break = False
        self.start_time = time.time()
        self.elapsed_work_time = 0
        self.elapsed_downtime = 0
        self.last_buzz_time = 0
        self.hand_raise_start = 0
        self.awaiting_thumbs_up = False

        self.entry_id.config(state=tk.DISABLED)
        self.btn_start.config(state=tk.DISABLED)
        self.btn_finish.config(state=tk.NORMAL)
        self.btn_break.config(state=tk.NORMAL)
        self.lbl_status.config(text="Status: Connecting to ESP32...", fg="white")

        threading.Thread(target=self.process_loop, daemon=True).start()

    def trigger_double_buzzer(self):
        """Sounds the buzzer twice rapidly as a penalty."""
        try:
            urllib.request.urlopen(ESP32_PITCH_URL + "800", timeout=1)  # Beep 1
            time.sleep(0.15)
            urllib.request.urlopen(ESP32_PITCH_URL + "0", timeout=1)  # Stop
            time.sleep(0.15)
            urllib.request.urlopen(ESP32_PITCH_URL + "800", timeout=1)  # Beep 2
            time.sleep(0.15)
            urllib.request.urlopen(ESP32_PITCH_URL + "0", timeout=1)  # Stop
            print("🚨 DOUBLE BUZZER TRIGGERED (False Alarm)!")
        except Exception as e:
            print(f"Buzzer failed: {e}")

    def process_loop(self):
        last_time = time.time()

        while self.is_running:
            try:
                req = urllib.request.Request(ESP32_CAMERA_URL, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, timeout=2) as response:
                    arr = np.asarray(bytearray(response.read()), dtype=np.uint8)
                    frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)

                if frame is None: continue
                frame = cv2.flip(frame, 1)

                current_time = time.time()
                delta_time = current_time - last_time
                last_time = current_time

                if self.on_break:
                    if time.time() >= self.break_end_time:
                        self.on_break = False
                        self.root.after(0, lambda: self.lbl_status.config(text="Status: Working", fg="#2ecc71"))
                    self.root.after(0, self.update_gui_safe, "On Break", frame, True, "On Break")
                else:
                    posture_status, processed_frame = self.detector.check_posture(frame)
                    gesture_status = "None"

                    # Run Gesture Detection every 4th frame to save CPU
                    self.frame_count += 1
                    if self.frame_count % 4 == 0:
                        img_rgb = cv2.cvtColor(processed_frame, cv2.COLOR_BGR2RGB)
                        hand_results = self.detector.hands.process(img_rgb)

                        if hand_results.multi_hand_landmarks:
                            hand_landmarks = hand_results.multi_hand_landmarks[0]
                            self.detector.mp_draw.draw_landmarks(processed_frame, hand_landmarks,
                                                                 self.detector.mp_hands.HAND_CONNECTIONS)

                            # --- ADD THIS FINGERTIP RADAR ---
                            h, w, _ = processed_frame.shape
                            thumb_tip = hand_landmarks[4]
                            index_tip = hand_landmarks[8]

                            # Draw big red dots on the exact fingertips
                            cv2.circle(processed_frame, (int(thumb_tip.x * w), int(thumb_tip.y * h)), 12, (0, 0, 255),
                                       -1)
                            cv2.circle(processed_frame, (int(index_tip.x * w), int(index_tip.y * h)), 12, (0, 0, 255),
                                       -1)

                            open_hand = self.detector.is_open_hand(hand_landmarks)
                            thumbs_up = self.detector.is_thumbs_up(hand_landmarks)

                            if thumbs_up:
                                gesture_status = "Thumbs Up! 👍"
                            elif open_hand:
                                gesture_status = "Open Hand (5 Fingers) ✋"
                            else:
                                gesture_status = "Hand Detected"

                            # GESTURE STATE MACHINE
                            if self.awaiting_thumbs_up:
                                if thumbs_up:
                                    # CONFIRMED: Grant break
                                    self.on_break = True
                                    self.break_end_time = time.time() + BREAK_DURATION_SECONDS
                                    self.root.after(0, lambda: self.lbl_status.config(
                                        text=f"Status: ON BREAK ({BREAK_DURATION_SECONDS}s)", fg="#f1c40f"))
                                    self.root.after(0, lambda: self.lbl_timer.config(foreground="#f1c40f"))
                                    self.awaiting_thumbs_up = False
                                    self.hand_raise_start = 0
                                elif not open_hand and not thumbs_up:
                                    # FALSE ALARM: Hand lowered/closed without thumbs up
                                    self.trigger_double_buzzer()
                                    self.root.after(0, lambda: self.lbl_status.config(
                                        text="Status: False Alarm! Keep working.", fg="#e74c3c"))
                                    self.awaiting_thumbs_up = False
                                    self.hand_raise_start = 0
                            else:
                                if open_hand:
                                    if self.hand_raise_start == 0:
                                        self.hand_raise_start = current_time
                                    elif current_time - self.hand_raise_start >= 5.0:
                                        # 5 seconds reached!
                                        self.awaiting_thumbs_up = True
                                        self.root.after(0, lambda: self.lbl_status.config(
                                            text="Show THUMBS UP to confirm break!", fg="#f1c40f"))
                                else:
                                    self.hand_raise_start = 0

                    # Posture Time Logic
                    if posture_status == "Working":
                        self.elapsed_work_time += delta_time
                    elif posture_status in ["Not Working", "Sleeping"]:
                        self.elapsed_downtime += delta_time
                        if current_time - self.last_buzz_time > 3.0:
                            try:
                                urllib.request.urlopen(ESP32_PITCH_URL + "800", timeout=1)  # Posture alarm
                                self.last_buzz_time = current_time
                            except Exception as e:
                                print(f"Buzzer failed: {e}")

                    self.root.after(0, self.update_gui_safe, posture_status, processed_frame, False, gesture_status)

                time.sleep(0.15)
            except Exception as e:
                print(f"Stream error: {e}")
                time.sleep(1)

    def update_gui_safe(self, posture_status, frame, is_break, gesture_status="None"):
        try:
            cv2image = cv2.cvtColor(frame, cv2.COLOR_BGR2RGBA)
            img = Image.fromarray(cv2image)
            imgtk = ImageTk.PhotoImage(image=img)
            self.lbl_camera.imgtk = imgtk
            self.lbl_camera.configure(image=imgtk)

            m, s = divmod(int(self.elapsed_work_time), 60)
            h, m = divmod(m, 60)
            self.lbl_timer.config(text=f"{h:02d}:{m:02d}:{s:02d}")
            self.lbl_posture.config(text=f"Posture: {posture_status}")
            self.lbl_downtime.config(text=f"Total Downtime: {int(self.elapsed_downtime)}s")
            self.lbl_gesture.config(text=f"Gesture: {gesture_status}")

            if not is_break and not self.awaiting_thumbs_up:
                if posture_status == "Working":
                    self.lbl_timer.config(foreground="#2ecc71")
                    self.lbl_status.config(text="Status: Working", fg="#2ecc71")
                elif posture_status in ["Not Working", "Sleeping"]:
                    self.lbl_timer.config(foreground="#e74c3c")
                    self.lbl_status.config(text=f"Status: {posture_status} ⚠️", fg="#e74c3c")
                else:
                    self.lbl_timer.config(foreground="#95a5a6")
                    self.lbl_status.config(text=f"Status: {posture_status}", fg="#95a5a6")

            if self.hand_raise_start > 0 and not self.awaiting_thumbs_up:
                remaining = 5.0 - (time.time() - self.hand_raise_start)
                self.lbl_gesture.config(text=f"Hold 5 fingers... {remaining:.1f}s", fg="#f1c40f")

        except Exception as e:
            print(f"GUI Update Error: {e}")

    def request_break(self):
        if self.on_break: return
        if messagebox.askyesno("Break Request", "Request a 5-minute break?"):
            self.on_break = True
            self.break_end_time = time.time() + BREAK_DURATION_SECONDS
            self.lbl_status.config(text=f"Status: ON BREAK ({BREAK_DURATION_SECONDS}s)", fg="#f1c40f")

    def finish_work(self):
        self.is_running = False
        self.on_break = False
        time.sleep(0.5)
        end_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        total_work_str = time.strftime("%H:%M:%S", time.gmtime(self.elapsed_work_time))
        total_down_str = time.strftime("%H:%M:%S", time.gmtime(self.elapsed_downtime))

        new_data = {"Worker ID": [self.worker_id], "Date": [datetime.now().strftime("%Y-%m-%d")],
                    "End Time": [end_timestamp], "Total Work Time": [total_work_str],
                    "Total Downtime": [total_down_str]}
        df_new = pd.DataFrame(new_data)
        if os.path.exists(EXCEL_FILE):
            try:
                df_existing = pd.read_excel(EXCEL_FILE)
                df_final = pd.concat([df_existing, df_new], ignore_index=True)
            except Exception:
                df_final = df_new
        else:
            df_final = df_new
        try:
            df_final.to_excel(EXCEL_FILE, index=False)
        except PermissionError:
            messagebox.showerror("Error", "Close the Excel file and try again.")

        messagebox.showinfo("Session Ended",
                            f"Worker ID: {self.worker_id}\nWork: {total_work_str}\nDowntime: {total_down_str}")
        self.reset_ui()

    def reset_ui(self):
        self.entry_id.config(state=tk.NORMAL)
        self.btn_start.config(state=tk.NORMAL)
        self.btn_finish.config(state=tk.DISABLED)
        self.btn_break.config(state=tk.DISABLED)
        self.lbl_timer.config(text="00:00:00", fg="#95a5a6")
        self.lbl_status.config(text="Status: IDLE", fg="white")
        self.lbl_posture.config(text="Posture: N/A")
        self.lbl_downtime.config(text="Total Downtime: 0s")
        self.lbl_gesture.config(text="Gesture: None", fg="#3498db")
        self.lbl_camera.config(image='', text="Camera Offline")


if __name__ == "__main__":
    root = tk.Tk()
    app = WorkerTrackerApp(root)
    root.mainloop()