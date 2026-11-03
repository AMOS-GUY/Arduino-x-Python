import cv2
import numpy as np
import mediapipe as mp
import tkinter as tk
from PIL import Image, ImageTk
import urllib.request
import math
import threading
import time

# ==========================================
# CONFIGURATION
# ==========================================
ESP32_CAMERA_URL = "http://192.168.4.1/capture"
ESP32_PITCH_URL = "http://192.168.4.1/pitch?freq="


# ==========================================
# HAND TRACKER CLASS
# ==========================================
class FingerDistanceTracker:
    def __init__(self):
        self.mp_hands = mp.solutions.hands
        self.hands = self.mp_hands.Hands(
            static_image_mode=False,
            max_num_hands=1,
            min_detection_confidence=0.7,
            min_tracking_confidence=0.7
        )
        self.mp_draw = mp.solutions.drawing_utils

    def get_finger_distance(self, frame):
        """Returns distance between thumb tip and index finger tip"""
        img_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = self.hands.process(img_rgb)

        distance = None
        hand_landmarks = None

        if results.multi_hand_landmarks:
            hand_landmarks = results.multi_hand_landmarks[0]

            # Get thumb tip (landmark 4) and index tip (landmark 8)
            thumb_tip = hand_landmarks.landmark[4]
            index_tip = hand_landmarks.landmark[8]

            # Calculate Euclidean distance
            distance = math.sqrt(
                (thumb_tip.x - index_tip.x) ** 2 +
                (thumb_tip.y - index_tip.y) ** 2
            )

        return distance, hand_landmarks


# ==========================================
# MAIN APPLICATION
# ==========================================
class PitchControlApp:
    def __init__(self, root):
        self.root = root
        self.root.title("AI Finger Pitch Controller")
        self.root.geometry("1000x700")
        self.root.configure(bg="#1e1e1e")

        self.tracker = FingerDistanceTracker()
        self.is_running = False
        self.current_freq = 0
        self.last_pitch_update = 0

        self.setup_gui()

    def setup_gui(self):
        title_font = ("Helvetica", 24, "bold")
        label_font = ("Helvetica", 16)
        big_font = ("Helvetica", 72, "bold")

        # Title
        tk.Label(self.root, text="🎵 Finger Pitch Controller",
                 font=title_font, bg="#1e1e1e", fg="#00d2d3").pack(pady=20)

        # Camera frame
        self.lbl_camera = tk.Label(self.root, bg="#1e1e1e", text="Camera Offline")
        self.lbl_camera.pack(expand=True, fill=tk.BOTH, padx=20, pady=10)

        # Info panel
        info_frame = tk.Frame(self.root, bg="#2d2d2d")
        info_frame.pack(fill=tk.X, padx=20, pady=20)

        # Distance display
        self.lbl_distance = tk.Label(info_frame, text="Distance: 0.00",
                                     font=big_font, bg="#2d2d2d", fg="#f1c40f")
        self.lbl_distance.pack(pady=10)

        # Frequency display
        self.lbl_freq = tk.Label(info_frame, text="Frequency: 0 Hz",
                                 font=label_font, bg="#2d2d2d", fg="#2ecc71")
        self.lbl_freq.pack(pady=5)

        # Status
        self.lbl_status = tk.Label(info_frame, text="Status: Ready",
                                   font=label_font, bg="#2d2d2d", fg="#95a5a6")
        self.lbl_status.pack(pady=5)

        # Start button
        self.btn_start = tk.Button(info_frame, text="Start Tracking",
                                   font=label_font, bg="#2ecc71", fg="white",
                                   command=self.start_tracking, width=15)
        self.btn_start.pack(pady=10)

        # Instructions
        tk.Label(self.root,
                 text="👆 Pinch thumb and index finger to lower pitch\n"
                      "👐 Spread fingers to raise pitch",
                 font=("Helvetica", 12), bg="#1e1e1e", fg="#95a5a6").pack(pady=10)

    def start_tracking(self):
        self.is_running = True
        self.btn_start.config(state=tk.DISABLED, text="Tracking...")
        self.lbl_status.config(text="Status: Tracking fingers...", fg="#2ecc71")

        threading.Thread(target=self.tracking_loop, daemon=True).start()

    def tracking_loop(self):
        last_time = time.time()

        while self.is_running:
            try:
                # Fetch frame from ESP32
                req = urllib.request.Request(ESP32_CAMERA_URL,
                                             headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, timeout=2) as response:
                    arr = np.asarray(bytearray(response.read()), dtype=np.uint8)
                    frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)

                if frame is None:
                    continue

                frame = cv2.flip(frame, 1)

                # Get finger distance
                distance, landmarks = self.tracker.get_finger_distance(frame)

                if distance is not None:
                    # Draw landmarks
                    self.tracker.mp_draw.draw_landmarks(
                        frame, landmarks, self.tracker.mp_hands.HAND_CONNECTIONS
                    )

                    # Map distance to frequency (200 Hz to 2000 Hz)
                    # Distance typically ranges from 0.05 (pinched) to 0.3 (spread)
                    min_dist, max_dist = 0.05, 0.25
                    distance = max(min_dist, min(max_dist, distance))

                    # Normalize to 0-1
                    normalized = (distance - min_dist) / (max_dist - min_dist)

                    # Map to frequency range
                    min_freq, max_freq = 200, 2000
                    freq = int(min_freq + (max_freq - min_freq) * normalized)

                    # Update ESP32 every 100ms to avoid flooding
                    current_time = time.time()
                    if current_time - self.last_pitch_update > 0.1:
                        try:
                            urllib.request.urlopen(
                                f"{ESP32_PITCH_URL}{freq}",
                                timeout=1
                            )
                            self.last_pitch_update = current_time
                        except Exception as e:
                            print(f"Failed to send pitch: {e}")

                    # Update GUI
                    self.root.after(0, self.update_gui, frame, distance, freq)
                else:
                    try:
                        urllib.request.urlopen(f"{ESP32_PITCH_URL}0", timeout=1)
                    except Exception:
                        pass
                    self.root.after(0, lambda: self.lbl_status.config(text="Status: No hand detected", fg="#e74c3c"))
                    self.root.after(0, lambda: self.lbl_freq.config(text="Frequency: 0 Hz"))
                    self.root.after(0, lambda: self.lbl_distance.config(text="Distance: --", fg="#95a5a6"))

                time.sleep(0.05)  # ~20 FPS

            except Exception as e:
                print(f"Stream error: {e}")
                time.sleep(1)

    def update_gui(self, frame, distance, freq):
        try:
            # Convert and display frame
            cv2image = cv2.cvtColor(frame, cv2.COLOR_BGR2RGBA)
            img = Image.fromarray(cv2image)
            imgtk = ImageTk.PhotoImage(image=img)

            self.lbl_camera.imgtk = imgtk
            self.lbl_camera.configure(image=imgtk)

            # Update displays
            self.lbl_distance.config(text=f"Distance: {distance:.3f}")
            self.lbl_freq.config(text=f"Frequency: {freq} Hz")
            self.lbl_status.config(text="Status: Playing", fg="#2ecc71")

            # Color code based on pitch
            if freq < 600:
                self.lbl_distance.config(fg="#e74c3c")  # Red for low
            elif freq < 1400:
                self.lbl_distance.config(fg="#f1c40f")  # Yellow for mid
            else:
                self.lbl_distance.config(fg="#2ecc71")  # Green for high

        except Exception as e:
            print(f"GUI error: {e}")


if __name__ == "__main__":
    root = tk.Tk()
    app = PitchControlApp(root)
    root.mainloop()