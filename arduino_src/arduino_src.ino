#include <SPI.h>
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SH110X.h>

#define OLED_CS 10
#define OLED_DC 9
#define OLED_RST 8

const int BLUE = 2;
const int GREEN = 3;
const int YELLOW = 4;
const int RED = 5;

const unsigned long STATION_DISPLAY_MS = 10000;
const unsigned long ALERT_DETAIL_MS = 5000;
const unsigned long PACKET_TIMEOUT_MS = 35000;
const unsigned long HEARTBEAT_PERIOD_MS = 3000;
const unsigned long HEARTBEAT_PULSE_MS = 100;
const int MAX_STATION_LEN = 20;
const int MAX_ALERT_LEN = 200;
const int CHARS_PER_LINE = 21;
const int MAX_ALERT_LINES = 4;

// Data flow: Python sends one CSV packet, MCU parses it and updates OLED + LEDs.

Adafruit_SH1106G display = Adafruit_SH1106G(128, 64, &SPI, OLED_DC, OLED_RST, OLED_CS);

// Fixed-size buffers avoid heap fragmentation on long runtimes.
char route[8] = "";
char eta1[8] = "";
char eta2[8] = "";
char st_name[MAX_STATION_LEN + 1] = "";
int hasAlert = 0;
char alert_lines[12][CHARS_PER_LINE + 1];
int total_alert_lines = 0;

unsigned long lastPacketMs = 0;
unsigned long lastBluePulseMs = 0;
bool waitingScreenShown = false;

enum State { WAITING, SHOW_STATION, SHOW_ALERT_TITLE, SHOW_ALERT_DETAIL };
State currentState = WAITING;
unsigned long stateEnteredMs = 0;

void renderWaitingScreen();

void setup() {
  Serial.begin(115200);
  // Keep serial parsing responsive if a packet is incomplete.
  Serial.setTimeout(50);

  pinMode(BLUE, OUTPUT);
  pinMode(GREEN, OUTPUT);
  pinMode(YELLOW, OUTPUT);
  pinMode(RED, OUTPUT);

  display.begin(0, true);
  display.setRotation(2);
  display.setTextWrap(false);

  // Quick LED test on boot
  digitalWrite(BLUE, HIGH); delay(100); digitalWrite(BLUE, LOW);
  digitalWrite(GREEN, HIGH); delay(100); digitalWrite(GREEN, LOW);
  digitalWrite(YELLOW, HIGH); delay(100); digitalWrite(YELLOW, LOW);
  digitalWrite(RED, HIGH); delay(100); digitalWrite(RED, LOW);

  renderWaitingScreen();
  waitingScreenShown = true;
}

void loop() {
  // Always check serial first so new telemetry is not delayed.
  if (Serial.available() > 0) {
    char packetBuffer[256];
    int len = Serial.readBytesUntil('\n', packetBuffer, sizeof(packetBuffer) - 1);
    packetBuffer[len] = '\0';
    
    while(len > 0 && (packetBuffer[len-1] == '\r' || packetBuffer[len-1] == ' ' || packetBuffer[len-1] == '\n')) {
      packetBuffer[--len] = '\0';
    }

    if (len > 0 && processPacket(packetBuffer)) {
      lastPacketMs = millis();
      waitingScreenShown = false;
      currentState = SHOW_STATION;
      stateEnteredMs = millis();
      renderStation();
      updateTrafficLEDs();
    }
  }

  if (millis() - lastPacketMs > PACKET_TIMEOUT_MS) {
    currentState = WAITING;
  }

  unsigned long elapsed = millis() - stateEnteredMs;

  switch (currentState) {
    case SHOW_STATION:
      if (elapsed >= STATION_DISPLAY_MS) {
        if (hasAlert == 1) {
          currentState = SHOW_ALERT_TITLE;
          stateEnteredMs = millis();
          renderAlertTitle();
        } else {
          stateEnteredMs = millis();
        }
      }
      break;
    case SHOW_ALERT_TITLE:
      // Non-blocking red LED pulse while alert header is visible.
      if ((elapsed % 500) < 250) {
        digitalWrite(RED, HIGH);
      } else {
        digitalWrite(RED, LOW);
      }

      if (elapsed >= 2000) {
        digitalWrite(RED, LOW);
        currentState = SHOW_ALERT_DETAIL;
        stateEnteredMs = millis();
        renderAlertDetail(0);
      }
      break;
    case SHOW_ALERT_DETAIL:
      {
        int currentScrollOffset = elapsed / 2000;
        static int lastScrollOffset = -1;
        if (currentScrollOffset != lastScrollOffset) {
          lastScrollOffset = currentScrollOffset;
          renderAlertDetail(currentScrollOffset);
        }
        
        // Extend detail duration to let all lines scroll at least once.
        unsigned long currentDuration = max((unsigned long)ALERT_DETAIL_MS, (unsigned long)(total_alert_lines * 2000UL));
        
        if (elapsed >= currentDuration) {
          currentState = SHOW_STATION;
          stateEnteredMs = millis();
          lastScrollOffset = -1;
          renderStation();
          updateTrafficLEDs();
        }
      }
      break;
    case WAITING:
      if (!waitingScreenShown) {
        renderWaitingScreen();
        waitingScreenShown = true;
        
        digitalWrite(RED, LOW);
        digitalWrite(YELLOW, LOW);
        digitalWrite(GREEN, LOW);
      }

      // Soft heartbeat while waiting: brief pulse every ~3 seconds.
      if (millis() - lastBluePulseMs >= HEARTBEAT_PERIOD_MS) {
        lastBluePulseMs = millis();
        digitalWrite(BLUE, HIGH);
      } else if (millis() - lastBluePulseMs >= HEARTBEAT_PULSE_MS) {
        digitalWrite(BLUE, LOW);
      }
      break;
  }
}

bool processPacket(char* p) {
  // Packet format: Route,ETA1,ETA2,AlertFlag,Station[,Message]
  char* token = strtok(p, ",");
  if (!token) return false;
  strncpy(route, token, sizeof(route) - 1);
  route[sizeof(route) - 1] = '\0';

  token = strtok(NULL, ",");
  if (!token) return false;
  strncpy(eta1, token, sizeof(eta1) - 1);
  eta1[sizeof(eta1) - 1] = '\0';

  token = strtok(NULL, ",");
  if (!token) return false;
  strncpy(eta2, token, sizeof(eta2) - 1);
  eta2[sizeof(eta2) - 1] = '\0';

  token = strtok(NULL, ",");
  if (!token) return false;
  hasAlert = atoi(token);

  token = strtok(NULL, ",");
  if (!token) return false;
  strncpy(st_name, token, sizeof(st_name) - 1);
  st_name[sizeof(st_name) - 1] = '\0';

  // Read remaining tail as alert message payload.
  token = strtok(NULL, ""); 
  char alert_msg_buffer[MAX_ALERT_LEN + 1];
  if (token) {
    strncpy(alert_msg_buffer, token, sizeof(alert_msg_buffer) - 1);
    alert_msg_buffer[sizeof(alert_msg_buffer) - 1] = '\0';
  } else {
    strcpy(alert_msg_buffer, "No details available");
  }

  // Pre-split alert text into OLED-width lines for lightweight rendering.
  total_alert_lines = 0;
  int msg_len = strlen(alert_msg_buffer);
  int start = 0;

  while (start < msg_len && total_alert_lines < 12) {
    int end_idx = start + CHARS_PER_LINE;
    if (end_idx < msg_len) {
      int split = end_idx;
      while (split > start && alert_msg_buffer[split] != ' ') {
        split--;
      }
      if (split > start) end_idx = split;
    } else {
      end_idx = msg_len;
    }

    int line_len = end_idx - start;
    if (line_len > CHARS_PER_LINE) line_len = CHARS_PER_LINE;

    strncpy(alert_lines[total_alert_lines], &alert_msg_buffer[start], line_len);
    alert_lines[total_alert_lines][line_len] = '\0';
    total_alert_lines++;

    start = end_idx;
    while (start < msg_len && alert_msg_buffer[start] == ' ') start++;
  }

  return true;
}

void renderWaitingScreen() {
  display.clearDisplay();
  display.setTextColor(SH110X_WHITE);
  display.setTextSize(1);
  display.setCursor(16, 20);
  display.print("WAITING FOR DATA");
  display.setCursor(20, 34);
  display.print("Check Python/COM");
  display.display();
}

void renderStation() {
  display.clearDisplay();
  display.setTextColor(SH110X_WHITE);
  display.setTextWrap(false);

  display.setTextSize(1);
  display.setCursor(30, 5);
  display.print(st_name);

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

void renderAlertTitle() {
  display.clearDisplay();
  display.setTextSize(2);
  display.setTextColor(SH110X_WHITE);
  display.setCursor(20, 15);
  display.print("SERVICE");
  display.setCursor(25, 35);
  display.print("ALERT!");
  display.display();
}

void renderAlertDetail(int startLineIndex) {
  display.clearDisplay();
  display.setTextSize(1);
  display.setTextColor(SH110X_WHITE);
  display.setTextWrap(false);
  display.setCursor(0, 0);
  display.print("ALERT DETAILS:");
  display.drawLine(0, 10, 128, 10, SH110X_WHITE);

  int y = 15;
  for (int i = startLineIndex; i < startLineIndex + MAX_ALERT_LINES && i < total_alert_lines; i++) {
    display.setCursor(0, y);
    display.print(alert_lines[i]);
    y += 12;
  }

  display.display();
}

void updateTrafficLEDs() {
  digitalWrite(BLUE, LOW);
  digitalWrite(RED, LOW);
  digitalWrite(YELLOW, LOW);
  digitalWrite(GREEN, LOW);

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
