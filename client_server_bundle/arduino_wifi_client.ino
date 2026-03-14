#include <SPI.h>
#include <Wire.h>
#include <WiFiS3.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SH110X.h>

#define OLED_CS 10
#define OLED_DC 9
#define OLED_RST 8

const int BLUE = 2;
const int GREEN = 3;
const int YELLOW = 4;
const int RED = 5;

const unsigned long FETCH_PERIOD_MS = 20000;
const unsigned long WIFI_RETRY_MS = 8000;
const unsigned long HEARTBEAT_PERIOD_MS = 3000;
const unsigned long HEARTBEAT_PULSE_MS = 120;
const unsigned long HTTP_READ_TIMEOUT_MS = 5000;
const unsigned long ALERT_PREVIEW_MS = 10000;

const size_t MAX_JSON_BODY = 768;
const size_t MAX_ALERT_LEN = 200;

// Network settings
const char WIFI_SSID[] = "DESKTOP-75QM09J 4825";
const char WIFI_PASSWORD[] = "M3k94#74";
// Optional fallback network (used when primary SSID is unreachable).
const char WIFI_SSID_2[] = "";
const char WIFI_PASSWORD_2[] = "";

// Local hotspot/LAN endpoint on your PC (192.168.137.1:8000).
const bool USE_TLS = false;
const char API_HOST[] = "192.168.137.1";
const int API_PORT = 8000;
const char API_PATH[] = "/eta";

Adafruit_SH1106G display = Adafruit_SH1106G(128, 64, &SPI, OLED_DC, OLED_RST, OLED_CS);

WiFiClient plainClient;
WiFiSSLClient secureClient;

char route[8] = "--";
char eta1[8] = "--";
char eta2[8] = "--";
char station[24] = "REMOTE";
char alertMsg[MAX_ALERT_LEN + 1] = "No details available";
int alertFlag = 0;

bool hasFreshData = false;
unsigned long lastFetchMs = 0;
unsigned long lastWifiAttemptMs = 0;
unsigned long lastBluePulseMs = 0;

bool connectToWiFi(const char *ssid, const char *password, const char *label) {
  if (!ssid || strlen(ssid) == 0) {
    return false;
  }

  renderStatus("Connecting Wi-Fi", label);
  int status = WiFi.begin(ssid, password);
  unsigned long start = millis();
  while (status != WL_CONNECTED && millis() - start < 10000) {
    delay(250);
    status = WiFi.status();
  }

  if (status == WL_CONNECTED) {
    renderStatus("Wi-Fi connected", WiFi.localIP().toString().c_str());
    delay(700);
    return true;
  }

  return false;
}

void setAllTrafficLedsLow() {
  digitalWrite(RED, LOW);
  digitalWrite(YELLOW, LOW);
  digitalWrite(GREEN, LOW);
}

void updateTrafficLedsFromEta() {
  setAllTrafficLedsLow();

  if (strcmp(eta1, "--") == 0) {
    return;
  }

  int m = atoi(eta1);
  if (m <= 1) {
    digitalWrite(RED, HIGH);
  } else if (m <= 5) {
    digitalWrite(YELLOW, HIGH);
  } else {
    digitalWrite(GREEN, HIGH);
  }
}

void renderStatus(const char *line1, const char *line2) {
  display.clearDisplay();
  display.setTextColor(SH110X_WHITE);
  display.setTextSize(1);
  display.setCursor(0, 16);
  display.print(line1);
  display.setCursor(0, 30);
  display.print(line2);
  display.display();
}

void renderMainScreen() {
  display.clearDisplay();
  display.setTextColor(SH110X_WHITE);
  display.setTextWrap(false);

  display.setTextSize(1);
  display.setCursor(28, 5);
  display.print(station);

  display.fillCircle(14, 12, 11, SH110X_WHITE);
  display.setTextColor(SH110X_BLACK);
  display.setTextSize(2);
  display.setCursor((strlen(route) > 1 ? 4 : 8), 5);
  display.print(route);

  display.drawLine(0, 27, 128, 27, SH110X_WHITE);

  display.setTextColor(SH110X_WHITE);
  display.setTextSize(1);
  display.setCursor(0, 35);
  display.print("NEXT:");
  display.setCursor(0, 52);
  display.print("THEN:");

  display.setTextSize(2);
  display.setCursor(50, 32);
  display.print(eta1);
  if (strcmp(eta1, "--") != 0) display.print("m");

  display.setCursor(50, 50);
  display.print(eta2);
  if (strcmp(eta2, "--") != 0) display.print("m");

  display.display();
}

void renderAlertScreen() {
  display.clearDisplay();
  display.setTextColor(SH110X_WHITE);
  display.setTextWrap(false);

  display.setTextSize(1);
  display.setCursor(0, 0);
  display.print("SERVICE ALERT");
  display.drawLine(0, 10, 127, 10, SH110X_WHITE);

  const int maxCharsPerLine = 21;
  int textLen = strlen(alertMsg);
  int idx = 0;

  for (int line = 0; line < 4 && idx < textLen; line++) {
    char lineBuf[maxCharsPerLine + 1];
    int out = 0;

    while (idx < textLen && alertMsg[idx] == ' ') {
      idx++;
    }

    while (idx < textLen && out < maxCharsPerLine) {
      lineBuf[out++] = alertMsg[idx++];
    }

    if (idx < textLen && out == maxCharsPerLine) {
      int back = out - 1;
      while (back > 0 && lineBuf[back] != ' ') {
        back--;
      }
      if (back > 0) {
        idx -= (out - back - 1);
        out = back;
      }
    }

    while (out > 0 && lineBuf[out - 1] == ' ') {
      out--;
    }

    lineBuf[out] = '\0';
    display.setCursor(0, 14 + (line * 12));
    display.print(lineBuf);
  }

  display.display();
}

bool ensureWiFiConnected() {
  if (WiFi.status() == WL_CONNECTED) {
    return true;
  }

  if (millis() - lastWifiAttemptMs < WIFI_RETRY_MS) {
    return false;
  }

  lastWifiAttemptMs = millis();
  renderStatus("Wi-Fi disconnected", "Reconnecting...");

  if (connectToWiFi(WIFI_SSID, WIFI_PASSWORD, "Primary SSID")) {
    return true;
  }

  if (connectToWiFi(WIFI_SSID_2, WIFI_PASSWORD_2, "Fallback SSID")) {
    return true;
  }

  return false;
}

const char *findJsonValueStart(const char *json, const char *key) {
  char pattern[32];
  snprintf(pattern, sizeof(pattern), "\"%s\"", key);
  const char *start = strstr(json, pattern);
  if (!start) return nullptr;

  start += strlen(pattern);
  while (*start == ' ' || *start == '\t') start++;
  if (*start != ':') return nullptr;
  start++;
  while (*start == ' ' || *start == '\t') start++;
  return start;
}

bool extractJsonString(const char *json, const char *key, char *out, size_t outSize) {
  const char *start = findJsonValueStart(json, key);
  if (!start || *start != '"') return false;

  start++;
  const char *end = strchr(start, '"');
  if (!end) return false;

  size_t len = (size_t)(end - start);
  if (len >= outSize) len = outSize - 1;
  strncpy(out, start, len);
  out[len] = '\0';
  return true;
}

bool extractJsonInt(const char *json, const char *key, int *outValue) {
  const char *start = findJsonValueStart(json, key);
  if (!start) return false;
  *outValue = atoi(start);
  return true;
}

bool readHttpResponseBody(arduino::Client &client, char *jsonBody, size_t bodySize) {
  bool inHeaders = true;
  size_t idx = 0;
  unsigned long lastReadMs = millis();
  char tail[5] = {0, 0, 0, 0, 0};

  while (client.connected() || client.available()) {
    if (client.available()) {
      char c = client.read();
      lastReadMs = millis();

      if (inHeaders) {
        tail[0] = tail[1];
        tail[1] = tail[2];
        tail[2] = tail[3];
        tail[3] = c;
        if (tail[0] == '\r' && tail[1] == '\n' && tail[2] == '\r' && tail[3] == '\n') {
          inHeaders = false;
        }
      } else {
        if (idx < bodySize - 1) {
          jsonBody[idx++] = c;
        }
      }
    }

    if (millis() - lastReadMs > HTTP_READ_TIMEOUT_MS) {
      break;
    }
  }

  jsonBody[idx] = '\0';
  return idx > 0;
}

bool fetch_json_and_render() {
  if (!ensureWiFiConnected()) {
    return false;
  }

  arduino::Client *clientPtr;
  if (USE_TLS) {
    clientPtr = &secureClient;
  } else {
    clientPtr = &plainClient;
  }

  arduino::Client &client = *clientPtr;

  if (!client.connect(API_HOST, API_PORT)) {
    renderStatus("API connect failed", API_HOST);
    return false;
  }

  client.print("GET ");
  client.print(API_PATH);
  client.println(" HTTP/1.1");
  client.print("Host: ");
  client.println(API_HOST);
  client.println("User-Agent: UNO-R4-WiFi");
  client.println("Connection: close");
  client.println();

  char jsonBody[MAX_JSON_BODY];
  if (!readHttpResponseBody(client, jsonBody, sizeof(jsonBody))) {
    client.stop();
    renderStatus("HTTP read timeout", "No JSON body");
    return false;
  }
  client.stop();

  char tmpRoute[8] = "--";
  char tmpEta1[8] = "--";
  char tmpEta2[8] = "--";
  char tmpStation[24] = "REMOTE";
  char tmpAlert[MAX_ALERT_LEN + 1] = "No details available";
  int tmpAlertFlag = 0;

  extractJsonString(jsonBody, "route", tmpRoute, sizeof(tmpRoute));
  extractJsonString(jsonBody, "eta1", tmpEta1, sizeof(tmpEta1));
  extractJsonString(jsonBody, "eta2", tmpEta2, sizeof(tmpEta2));
  extractJsonString(jsonBody, "station", tmpStation, sizeof(tmpStation));
  extractJsonString(jsonBody, "alert_msg", tmpAlert, sizeof(tmpAlert));
  bool hasAlertFlag = extractJsonInt(jsonBody, "alert_flag", &tmpAlertFlag);

  // Fallback: if server flag cannot be parsed but message has content, still show alert.
  if (!hasAlertFlag) {
    tmpAlertFlag = 0;
  }
  if (strlen(tmpAlert) > 0 && strcmp(tmpAlert, "No details available") != 0) {
    tmpAlertFlag = 1;
  }

  strncpy(route, tmpRoute, sizeof(route) - 1);
  route[sizeof(route) - 1] = '\0';
  strncpy(eta1, tmpEta1, sizeof(eta1) - 1);
  eta1[sizeof(eta1) - 1] = '\0';
  strncpy(eta2, tmpEta2, sizeof(eta2) - 1);
  eta2[sizeof(eta2) - 1] = '\0';
  strncpy(station, tmpStation, sizeof(station) - 1);
  station[sizeof(station) - 1] = '\0';
  strncpy(alertMsg, tmpAlert, sizeof(alertMsg) - 1);
  alertMsg[sizeof(alertMsg) - 1] = '\0';
  alertFlag = tmpAlertFlag;

  updateTrafficLedsFromEta();
  if (tmpAlertFlag == 1) {
    renderAlertScreen();
    delay(ALERT_PREVIEW_MS);
  }
  renderMainScreen();
  return true;
}

void setup() {
  pinMode(BLUE, OUTPUT);
  pinMode(GREEN, OUTPUT);
  pinMode(YELLOW, OUTPUT);
  pinMode(RED, OUTPUT);

  display.begin(0, true);
  display.setRotation(2);
  display.setTextWrap(false);

  digitalWrite(BLUE, HIGH); delay(100); digitalWrite(BLUE, LOW);
  digitalWrite(GREEN, HIGH); delay(100); digitalWrite(GREEN, LOW);
  digitalWrite(YELLOW, HIGH); delay(100); digitalWrite(YELLOW, LOW);
  digitalWrite(RED, HIGH); delay(100); digitalWrite(RED, LOW);

  renderStatus("Booting", "Connecting Wi-Fi...");
  ensureWiFiConnected();
  fetch_json_and_render();
  lastFetchMs = millis();
}

void loop() {
  if (millis() - lastFetchMs >= FETCH_PERIOD_MS) {
    lastFetchMs = millis();
    hasFreshData = fetch_json_and_render();
  }

  if (!hasFreshData) {
    if (millis() - lastBluePulseMs >= HEARTBEAT_PERIOD_MS) {
      lastBluePulseMs = millis();
      digitalWrite(BLUE, HIGH);
    } else if (millis() - lastBluePulseMs >= HEARTBEAT_PULSE_MS) {
      digitalWrite(BLUE, LOW);
    }
  } else {
    digitalWrite(BLUE, LOW);
  }
}
