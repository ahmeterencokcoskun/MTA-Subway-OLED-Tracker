#include <SPI.h>
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SH110X.h>

#define OLED_CS     10
#define OLED_DC      9
#define OLED_RST     8

Adafruit_SH1106G display = Adafruit_SH1106G(128, 64, &SPI, OLED_DC, OLED_RST, OLED_CS);

String activeLine = "-";
String tren1 = "--";
String tren2 = "--";

void setup() {
  Serial.begin(9600);
  display.begin(0, true);
  
  display.clearDisplay();
  display.setTextColor(SH110X_WHITE);
  display.setTextSize(1);
  display.setCursor(10, 25);
  display.print("MTA Sistemine");
  display.setCursor(10, 40);
  display.print("Baglaniliyor...");
  display.display();
}

void loop() {
  // Python'dan veri gelirse (Örn: "N,2,7\n")
  if (Serial.available() > 0) {
    String data = Serial.readStringUntil('\n');
    
    int firstComma = data.indexOf(',');
    int secondComma = data.indexOf(',', firstComma + 1);
    
    if (firstComma > 0 && secondComma > 0) {
      activeLine = data.substring(0, firstComma);
      tren1 = data.substring(firstComma + 1, secondComma);
      tren2 = data.substring(secondComma + 1);
    }
    
    display.clearDisplay();

    // --- 1. DİNAMİK HAT LOGOSU ÇİZİMİ ---
    // MTA'nın klasik yuvarlak logosu
    display.fillCircle(14, 12, 11, SH110X_WHITE); 
    display.setTextColor(SH110X_BLACK); // Yazı siyah
    display.setTextSize(2);
    
    // Harfe veya rakama göre metni tam merkeze oturtmak için X koordinatı ayarı
    int textX = 8;
    if(activeLine == "W" || activeLine == "M") textX = 6; // Geniş harfler için
    if(activeLine == "1") textX = 9; // İnce rakamlar için
    
    display.setCursor(textX, 5);
    display.print(activeLine);

    // --- 2. DURAK İSMİ VE YÖN ---
    display.setTextColor(SH110X_WHITE);
    display.setTextSize(1);
    display.setCursor(30, 4);
    display.print("Times Sq - 42 St");
    display.setCursor(30, 14);
    display.print("Downtown Bound");

    // Ayraç Çizgisi
    display.drawLine(0, 27, 128, 27, SH110X_WHITE);

    // --- 3. GERİ SAYIM SAATLERİ ---
    // 1. Tren
    display.setTextSize(1);
    display.setCursor(0, 35);
    display.print("Next:");
    display.setTextSize(2);
    display.setCursor(45, 30);
    display.print(tren1);
    display.setTextSize(1);
    if(tren1 != "-") display.print(" min");

    // 2. Tren
    display.setTextSize(1);
    display.setCursor(0, 52);
    display.print("Then:");
    display.setTextSize(2);
    display.setCursor(45, 48);
    display.print(tren2);
    display.setTextSize(1);
    if(tren2 != "-") display.print(" min");

    display.display();
  }
}