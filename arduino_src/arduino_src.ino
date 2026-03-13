#include <SPI.h>
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SH110X.h>

#define OLED_CS     10
#define OLED_DC      9
#define OLED_RST     8

Adafruit_SH1106G display = Adafruit_SH1106G(128, 64, &SPI, OLED_DC, OLED_RST, OLED_CS);

// Global Variables
String activeRoute = "-";
String eta1 = "--";
String eta2 = "--";
String stationName = "Waiting..."; // Default until Python sends data

void setup() {
  Serial.begin(9600);
  display.begin(0, true);
  
  display.clearDisplay();
  display.setTextColor(SH110X_WHITE);
  display.setTextSize(1);
  display.setCursor(20, 25);
  display.print("MTA Universal");
  display.setCursor(20, 40);
  display.print("Tracker Ready");
  display.display();
}

void loop() {
  if (Serial.available() > 0) {
    // Expected format: Route,ETA1,ETA2,StationName\n
    String payload = Serial.readStringUntil('\n');
    payload.trim(); // Remove whitespace/newlines

    int firstComma = payload.indexOf(',');
    int secondComma = payload.indexOf(',', firstComma + 1);
    int thirdComma = payload.indexOf(',', secondComma + 1);

    if (firstComma > 0 && secondComma > 0 && thirdComma > 0) {
      activeRoute = payload.substring(0, firstComma);
      eta1 = payload.substring(firstComma + 1, secondComma);
      eta2 = payload.substring(secondComma + 1, thirdComma);
      stationName = payload.substring(thirdComma + 1);
      
      // Safety: If station name is too long for the screen
      if(stationName.length() > 16) {
        stationName = stationName.substring(0, 14) + "..";
      }
    }
    
    renderOLED();
  }
}

void renderOLED() {
  display.clearDisplay();

  // --- 1. DYNAMIC STATION NAME ---
  display.setTextColor(SH110X_WHITE);
  display.setTextSize(1);
  display.setCursor(32, 4);
  display.print(stationName); // NO HARDCODED TEXT HERE ANYMORE
  
  display.setCursor(32, 15);
  display.print("Subway Tracker");

  // --- 2. ROUTE LOGO ---
  display.fillCircle(14, 12, 11, SH110X_WHITE); 
  display.setTextColor(SH110X_BLACK); 
  display.setTextSize(2);
  
  // Center alignment for the letter/number inside the circle
  int textX = (activeRoute.length() > 1) ? 5 : 8; 
  display.setCursor(textX, 5);
  display.print(activeRoute);

  // Decorative line
  display.drawLine(0, 27, 128, 27, SH110X_WHITE);

  // --- 3. ARRIVAL TIMES ---
  display.setTextColor(SH110X_WHITE);
  display.setTextSize(1);
  display.setCursor(0, 35);
  display.print("Next:");
  
  display.setTextSize(2);
  display.setCursor(45, 30);
  display.print(eta1);
  display.setTextSize(1);
  if(eta1 != "-") display.print(" min");

  display.setTextSize(1);
  display.setCursor(0, 52);
  display.print("Then:");
  
  display.setTextSize(2);
  display.setCursor(45, 48);
  display.print(eta2);
  display.setTextSize(1);
  if(eta2 != "-") display.print(" min");

  display.display();
}