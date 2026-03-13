# 🚇 NYC MTA Live Subway Tracker (Arduino + OLED)

This project turns an Arduino and an OLED display into a real-time New York City Subway (MTA) countdown clock. It fetches live GTFS-Realtime data from MTA servers using Python and streams it via Serial to an Arduino UNO R4 WiFi, which renders a dynamic, retro-style station board on a 1.3" SPI OLED display.

![Project Preview](images/your_photo_here.jpg)

## ✨ Features
- **Real-time data:** Parses live GTFS-Realtime protocol buffers directly from NYC MTA endpoints.
- **Dynamic rendering:** Automatically cycles through active lines (1, 2, 3, 7, N, Q, R, W, S) at Times Sq - 42 St every 5 seconds.
- **Vector graphics:** Draws iconic circular MTA line logos and countdown metrics dynamically using the Adafruit GFX library.
- **Low latency:** Python handles API requests and parsing, then sends lightweight packets to Arduino.

## 🛠️ Hardware Requirements
- Arduino UNO R4 WiFi (or any compatible Arduino board)
- Waveshare 1.3" SPI OLED Display (SH1106)
- Jumper wires

### Wiring (SPI OLED)

| OLED Pin | Arduino Pin |
|----------|-------------|
| VCC      | 5V / 3.3V   |
| GND      | GND         |
| DIN      | Pin 11      |
| CLK      | Pin 13      |
| CS       | Pin 10      |
| DC       | Pin 9       |
| RST      | Pin 8       |

## 💻 Software Setup

### 1) Python Environment
Install Python 3.x, then install dependencies:

```bash
pip install gtfs-realtime-bindings requests pyserial
```

> **Note:** Update the `ARDUINO_PORT` variable in `python_src/metro_full.py` to match your board's COM port (for example, `COM7`).

### 2) Arduino IDE
1. Open `arduino_src.ino` in Arduino IDE.
2. Install these libraries from Library Manager:
   - Adafruit GFX Library
   - Adafruit SH110X
3. Upload the sketch to your Arduino.
4. Close Serial Monitor after upload to free the port for Python.

## 🚀 How to Run
1. Plug in your Arduino via USB.
2. Run the Python script:

```bash
python python_src/metro_full.py
```

3. Watch the OLED display show live NYC Subway arrival times.

## 📜 License
MIT License