#include "esp_camera.h"
#include <WiFi.h>
#include <WebServer.h>

// =====================================
// GOOUUU ESP32-S3-CAM V1.5 Pins
// =====================================
#define CAMERA_PIN_PWDN   -1
#define CAMERA_PIN_RESET  -1
#define CAMERA_PIN_XCLK   15
#define CAMERA_PIN_SIOD    4
#define CAMERA_PIN_SIOC    5
#define CAMERA_PIN_Y9     16
#define CAMERA_PIN_Y8     17
#define CAMERA_PIN_Y7     18
#define CAMERA_PIN_Y6     12
#define CAMERA_PIN_Y5     10
#define CAMERA_PIN_Y4      8
#define CAMERA_PIN_Y3      9
#define CAMERA_PIN_Y2     11
#define CAMERA_PIN_VSYNC   6
#define CAMERA_PIN_HREF    7
#define CAMERA_PIN_PCLK   13

#define BUZZER_PIN 2  // Passive Buzzer connected to G2

const char* AP_SSID = "ESP32-Camera";
const char* AP_PASSWORD = "Camera1234";

WebServer server(80);

// =====================================
// 1. Camera initialization
// =====================================
bool startCamera() {
  camera_config_t config = {};
  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer = LEDC_TIMER_0;
  config.pin_d0 = CAMERA_PIN_Y2; config.pin_d1 = CAMERA_PIN_Y3;
  config.pin_d2 = CAMERA_PIN_Y4; config.pin_d3 = CAMERA_PIN_Y5;
  config.pin_d4 = CAMERA_PIN_Y6; config.pin_d5 = CAMERA_PIN_Y7;
  config.pin_d6 = CAMERA_PIN_Y8; config.pin_d7 = CAMERA_PIN_Y9;
  config.pin_xclk = CAMERA_PIN_XCLK; config.pin_pclk = CAMERA_PIN_PCLK;
  config.pin_vsync = CAMERA_PIN_VSYNC; config.pin_href = CAMERA_PIN_HREF;
  config.pin_sccb_sda = CAMERA_PIN_SIOD; config.pin_sccb_scl = CAMERA_PIN_SIOC;
  config.pin_pwdn = CAMERA_PIN_PWDN; config.pin_reset = CAMERA_PIN_RESET;
  config.xclk_freq_hz = 20000000;
  config.pixel_format = PIXFORMAT_JPEG;
  config.frame_size = FRAMESIZE_VGA; // VGA for better hand tracking
  config.jpeg_quality = 12;
  config.fb_count = 2;

  if (psramFound()) {
    config.fb_location = CAMERA_FB_IN_PSRAM;
    config.grab_mode = CAMERA_GRAB_LATEST;
  } else {
    config.fb_location = CAMERA_FB_IN_DRAM;
    config.grab_mode = CAMERA_GRAB_WHEN_EMPTY;
    config.fb_count = 1;
  }

  return (esp_camera_init(&config) == ESP_OK);
}

// =====================================
// 2. Web Server Handlers
// =====================================
void handleRoot() {
  server.send(200, "text/plain", "ESP32-S3 Pitch Controller Active. Send GET to /pitch?freq=500");
}

void handleCapture() {
  camera_fb_t* frame = esp_camera_fb_get();
  if (!frame) {
    server.send(500, "text/plain", "Camera capture failed");
    return;
  }
  server.sendHeader("Cache-Control", "no-store, no-cache, must-revalidate");
  server.setContentLength(frame->len);
  server.send(200, "image/jpeg", "");
  WiFiClient client = server.client();
  client.write(frame->buf, frame->len);
  esp_camera_fb_return(frame);
}

// ⚠️ THIS IS THE FUNCTION THAT WAS MISSING! ⚠️
void handleBuzz() {
  if (server.hasArg("freq")) {
    int freq = server.arg("freq").toInt();
    if (freq > 0) {
      tone(BUZZER_PIN, freq); // Play the specific frequency
      server.send(200, "text/plain", "Playing " + String(freq) + "Hz");
    } else {
      noTone(BUZZER_PIN); // Stop sound immediately
      server.send(200, "text/plain", "Stopped");
    }
  } else {
    server.send(400, "text/plain", "Missing 'freq' argument");
  }
}

// =====================================
// 3. Setup
// =====================================
void setup() {
  Serial.begin(115200);
  delay(1500);
  
  pinMode(BUZZER_PIN, OUTPUT);
  noTone(BUZZER_PIN); // Ensure it's quiet on startup

  if (!startCamera()) {
    Serial.println("Camera failed to start.");
    return;
  }

  WiFi.mode(WIFI_AP);
  WiFi.softAP(AP_SSID, AP_PASSWORD);
  Serial.print("AP Ready! IP: ");
  Serial.println(WiFi.softAPIP());

  server.on("/", HTTP_GET, handleRoot);
  server.on("/capture", HTTP_GET, handleCapture);
  server.on("/pitch", HTTP_GET, handleBuzz); // <-- This now successfully finds handleBuzz
  server.begin();
  
  Serial.println("Web server started!");
}

// =====================================
// 4. Main loop
// =====================================
void loop() {
  server.handleClient();
}