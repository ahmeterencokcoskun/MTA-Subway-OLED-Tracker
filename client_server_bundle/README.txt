Client + Server Bundle

Files
- local_eta_server.py      FastAPI server (real-time GTFS based)
- universal_tracker.py     Shared tracker logic imported by server
- arduino_wifi_client.ino  Arduino UNO R4 WiFi client sketch
- ui_client.py             Desktop UI to control server and run ETA queries

Run server directly
1) Install dependencies:
   pip install fastapi uvicorn pandas requests pyserial gtfs-realtime-bindings protobuf
2) Start server:
   python local_eta_server.py

Run with UI client
1) Start UI:
   python ui_client.py
2) In the UI:
   - Click Start Server
   - Click Health
   - Fill route/station/direction and click Fetch ETA

Test endpoints
- http://127.0.0.1:8000/health
- http://127.0.0.1:8000/eta?route=7&station=JAMAICA&direction=N

Arduino notes
- Board: UNO R4 WiFi
- API host in sketch is set to 192.168.137.1 (PC hotspot IP)
- Keep server running while the board is polling /eta
