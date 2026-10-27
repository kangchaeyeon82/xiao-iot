// XIAO ESP32S3 → FastAPI(Render) 원격 제어 펌웨어
//
// 2초마다 HTTPS POST /device/readings 로 센서값(내장 온도, WiFi RSSI)을 보내고,
// 응답 {"led": true|false} 로 보드 LED(GPIO21)를 켜고 끈다.
// 보드가 클라우드로 먼저 요청을 보내는 구조라 어떤 WiFi에 있어도 제어된다.

#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <HTTPClient.h>
#include <time.h>

#include "secrets.h"   // WIFI_SSID, WIFI_PASSWORD, DEVICE_API_KEY, API_BASE
#include "root_ca.h"   // ROOT_CA_PEM

const uint8_t LED_PIN = LED_BUILTIN;      // XIAO ESP32S3: GPIO21, LOW 일 때 켜짐
const uint32_t POST_INTERVAL_MS = 2000;
const uint32_t HTTP_TIMEOUT_MS = 60000;   // Render 무료 플랜은 잠들었다 깨는 데 최대 ~50초

WiFiClientSecure tls;
HTTPClient http;
uint32_t lastPost = 0;
bool ledOn = false;

void setLed(bool on) {
  ledOn = on;
  digitalWrite(LED_PIN, on ? LOW : HIGH);
}

void connectWiFi() {
  if (WiFi.status() == WL_CONNECTED) return;
  Serial.printf("[WiFi] %s 연결 중", WIFI_SSID);
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  uint32_t start = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - start < 20000) {
    delay(500);
    Serial.print('.');
  }
  if (WiFi.status() == WL_CONNECTED) {
    Serial.printf("\n[WiFi] 연결됨 IP=%s RSSI=%d dBm\n",
                  WiFi.localIP().toString().c_str(), WiFi.RSSI());
  } else {
    Serial.println("\n[WiFi] 연결 실패, 다음 주기에 재시도");
  }
}

// 인증서 유효기간 검사를 위해 시계를 맞춘다
void syncClock() {
  configTime(9 * 3600, 0, "pool.ntp.org", "time.google.com");
  Serial.print("[NTP] 시간 동기화");
  time_t now = time(nullptr);
  uint32_t start = millis();
  while (now < 1700000000 && millis() - start < 15000) {
    delay(300);
    Serial.print('.');
    now = time(nullptr);
  }
  Serial.printf(" %s", now > 1700000000 ? ctime(&now) : "실패(계속 진행)\n");
}

void postReading() {
  float temp = temperatureRead();   // ESP32-S3 내장 온도센서 (칩 온도)
  int rssi = WiFi.RSSI();
  char body[64];
  snprintf(body, sizeof(body), "{\"temperature\":%.1f,\"rssi\":%d}", temp, rssi);

  if (!http.begin(tls, String(API_BASE) + "/device/readings")) {
    Serial.println("[HTTP] begin 실패");
    return;
  }
  http.addHeader("Content-Type", "application/json");
  http.addHeader("X-Device-Key", DEVICE_API_KEY);

  uint32_t t0 = millis();
  int code = http.POST(body);
  uint32_t ms = millis() - t0;

  if (code == 200) {
    String res = http.getString();
    bool want = res.indexOf("\"led\":true") >= 0;
    if (want != ledOn) {
      setLed(want);
      Serial.printf("[LED] %s\n", want ? "ON" : "OFF");
    }
    Serial.printf("[POST] %s -> 200 (%lu ms) LED=%s\n", body, ms, ledOn ? "ON" : "OFF");
  } else if (code > 0) {
    Serial.printf("[POST] HTTP %d (%lu ms): %s\n", code, ms, http.getString().c_str());
  } else {
    Serial.printf("[POST] 실패: %s (%lu ms)\n", http.errorToString(code).c_str(), ms);
  }
  http.end();
}

void setup() {
  Serial.begin(115200);
  delay(1000);
  pinMode(LED_PIN, OUTPUT);
  setLed(false);
  Serial.println("\n=== XIAO ESP32S3 IoT ===");
  Serial.printf("API: %s\n", API_BASE);

  connectWiFi();
  syncClock();

  tls.setCACert(ROOT_CA_PEM);
  http.setReuse(true);              // TLS 연결을 재사용해 매번 핸드셰이크하지 않음
  http.setTimeout(HTTP_TIMEOUT_MS);
  http.setConnectTimeout(HTTP_TIMEOUT_MS);
}

void loop() {
  if (WiFi.status() != WL_CONNECTED) {
    connectWiFi();
    delay(1000);
    return;
  }
  if (millis() - lastPost >= POST_INTERVAL_MS) {
    lastPost = millis();
    postReading();
  }
}
