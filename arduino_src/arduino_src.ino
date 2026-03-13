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

Adafruit_SH1106G display = Adafruit_SH1106G(128, 64, &SPI, OLED_DC, OLED_RST, OLED_CS);

String route;
String eta1;
String eta2;
String st_name;
String alert_msg;
int hasAlert = 0;
unsigned long lastPacketMs = 0;
unsigned long lastBluePulseMs = 0;
bool waitingScreenShown = false;

void renderWaitingScreen();

void setup() {
  Serial.begin(9600);

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
  if (Serial.available() > 0) {
    String packet = Serial.readStringUntil('\n');
    packet.trim();

    if (!processPacket(packet)) {
      return;
    }

    lastPacketMs = millis();
    waitingScreenShown = false;

    // 1) Station and ETA screen
    renderStation();
    updateTrafficLEDs();
    delay(10000);

    if (hasAlert == 1) {
      // 2) Alert title + red flash only
      renderAlertTitle();
      for (int i = 0; i < 4; i++) {
        digitalWrite(RED, HIGH);
        delay(250);
        digitalWrite(RED, LOW);
        delay(250);
      }

      // 3) Alert details (extended)
      renderAlertDetail();
      delay(7000);

      // Return to station screen after detail phase
      renderStation();
    }

    digitalWrite(BLUE, LOW);
  } else if (millis() - lastPacketMs > 30000) {
    if (!waitingScreenShown) {
      renderWaitingScreen();
      waitingScreenShown = true;
    }

    digitalWrite(RED, LOW);
    digitalWrite(YELLOW, LOW);
    digitalWrite(GREEN, LOW);

    // Soft heartbeat while waiting: brief pulse every ~3 seconds.
    if (millis() - lastBluePulseMs >= 3000) {
      lastBluePulseMs = millis();
      digitalWrite(BLUE, HIGH);
    } else if (millis() - lastBluePulseMs >= 60) {
      digitalWrite(BLUE, LOW);
    }
  }
}

bool processPacket(String p) {
  // Format: Route,ETA1,ETA2,Flag,Station[,Message]
  int f1 = p.indexOf(',');
  int f2 = p.indexOf(',', f1 + 1);
  int f3 = p.indexOf(',', f2 + 1);
  int f4 = p.indexOf(',', f3 + 1);
  int f5 = p.indexOf(',', f4 + 1);

  if (f1 < 0 || f2 < 0 || f3 < 0 || f4 < 0) {
    return false;
  }

  route = p.substring(0, f1);
  eta1 = p.substring(f1 + 1, f2);
  eta2 = p.substring(f2 + 1, f3);
  hasAlert = p.substring(f3 + 1, f4).toInt();

  if (f5 > 0) {
    st_name = p.substring(f4 + 1, f5);
    alert_msg = p.substring(f5 + 1);
  } else {
    st_name = p.substring(f4 + 1);
    alert_msg = "No details available";
  }

  if (st_name.length() > 16) st_name = st_name.substring(0, 16);
  if (alert_msg.length() > 84) alert_msg = alert_msg.substring(0, 84);

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
  display.setCursor((route.length() > 1 ? 4 : 8), 5);
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
  if (eta1 != "--") display.print("m");

  display.setCursor(50, 50);
  display.print(eta2);
  if (eta2 != "--") display.print("m");

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

void renderAlertDetail() {
  display.clearDisplay();
  display.setTextSize(1);
  display.setTextColor(SH110X_WHITE);
  display.setTextWrap(false);
  display.setCursor(0, 0);
  display.print("ALERT DETAILS:");
  display.drawLine(0, 10, 128, 10, SH110X_WHITE);

  String msg = alert_msg;
  if (msg.length() == 0 || msg == "No details available") {
    msg = "No details available";
  }

  const int maxCharsPerLine = 21;
  const int maxLines = 4;
  int start = 0;
  int y = 15;

  for (int line = 0; line < maxLines && start < msg.length(); line++) {
    int end = start + maxCharsPerLine;
    if (end < msg.length()) {
      int split = msg.lastIndexOf(' ', end);
      if (split > start) end = split;
    }

    String part = msg.substring(start, end);
    part.trim();
    display.setCursor(0, y);
    display.print(part);

    start = end;
    while (start < msg.length() && msg.charAt(start) == ' ') start++;
    y += 12;
  }

  display.display();
}

void updateTrafficLEDs() {
  digitalWrite(BLUE, LOW);
  digitalWrite(RED, LOW);
  digitalWrite(YELLOW, LOW);
  digitalWrite(GREEN, LOW);

  if (eta1 == "--") {
    return;
  }

  int m = eta1.toInt();
  if (m <= 1) {
    digitalWrite(RED, HIGH);
  } else if (m <= 5) {
    digitalWrite(YELLOW, HIGH);
  } else {
    digitalWrite(GREEN, HIGH);
  }
}
