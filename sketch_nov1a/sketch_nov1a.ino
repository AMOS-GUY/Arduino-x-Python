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

#define BUZZER_PIN 2  // NEW: Buzzer connected to G3

//unsigned log buzz_until = 0;

const char* AP_SSID = "ESP32-Camera";
const char* AP_PASSWORD = "Camera1234";

WebServer server(80);
unsigned long buzz_until = 0; // Non-blocking buzzer timer

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
  config.frame_size = FRAMESIZE_QVGA; 
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

  esp_err_t err = esp_camera_init(&config);
  return (err == ESP_OK);
}

void handleRoot() {
  server.send(200, "text/plain", "ESP32-S3 Camera + Buzzer Active. Send GET to /capture or /buzz?ms=500");
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

// NEW: Handle Buzzer Trigger from Python
void handleBuzz() {
  if (server.hasArg("ms")) {
    int duration = server.arg("ms").toInt();
    buzz_until = millis() + duration;
    Serial.println("🔊 Buzzer HTTP request received! Buzzing for " + String(duration) + "ms");
    server.send(200, "text/plain", "Buzzer triggered");
  } else {
    server.send(400, "text/plain", "Missing 'ms' argument");
  }
}

void setup() {
  Serial.begin(115200);
  delay(1500);
  
  pinMode(BUZZER_PIN, OUTPUT);
  digitalWrite(BUZZER_PIN, LOW);

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
  server.on("/buzz", HTTP_GET, handleBuzz); 
  server.begin();
}

void loop() {
  server.handleClient();
  
  // Non-blocking buzzer control
  if (millis() < buzz_until) {
    digitalWrite(BUZZER_PIN, HIGH);
  } else {
    digitalWrite(BUZZER_PIN, LOW);
  }
}