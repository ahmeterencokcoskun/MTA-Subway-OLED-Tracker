import serial
import time
import requests
import math
import pandas as pd
from google.transit import gtfs_realtime_pb2

# --- CONFIGURATION ---
ARDUINO_PORT = "COM7"
BAUD_RATE = 9600

# Static MTA Stops Database
STATIONS_CSV_URL = "http://web.mta.info/developers/data/nyct/subway/Stations.csv"

# Live GTFS-Realtime Endpoints for all NYC Subway Lines
MTA_FEEDS = [
    "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs",      # 1, 2, 3, 4, 5, 6, S
    "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-ace",  # A, C, E
    "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-bdfm", # B, D, F, M
    "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-g",    # G
    "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-jz",   # J, Z
    "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-l",    # L
    "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-nqrw"  # N, Q, R, W
]

def load_all_stations():
    """Downloads and parses the MTA static stations database."""
    print(">>> Downloading MTA Stations Database (CSV)...")
    try:
        df = pd.read_csv(STATIONS_CSV_URL)
        stations_db = {}
        for index, row in df.iterrows():
            stop_id = str(row['GTFS Stop ID'])
            stop_name = str(row['Stop Name'])
            routes = str(row['Daytime Routes'])
            stations_db[stop_id] = {'name': stop_name, 'routes': routes}
        return stations_db
    except Exception as e:
        print(f"Error loading stations: {e}")
        return None

def get_live_arrivals(target_stop_id):
    """Fetches real-time ETA data across all MTA feeds for a specific stop."""
    arrivals = {}
    current_time = int(time.time())
    
    for feed_url in MTA_FEEDS:
        try:
            feed = gtfs_realtime_pb2.FeedMessage()
            response = requests.get(feed_url, timeout=5)
            feed.ParseFromString(response.content)
            
            for entity in feed.entity:
                if entity.HasField('trip_update'):
                    route_id = entity.trip_update.trip.route_id
                    for stop_update in entity.trip_update.stop_time_update:
                        if stop_update.stop_id == target_stop_id:
                            arrival_time = stop_update.arrival.time
                            minutes_away = math.floor((arrival_time - current_time) / 60)
                            
                            if minutes_away >= 0:
                                if route_id not in arrivals:
                                    arrivals[route_id] = []
                                arrivals[route_id].append(minutes_away)
        except Exception:
            continue # Silently skip offline endpoints
            
    # Sort ETAs and keep only the next 2 trains per route
    final_data = {}
    for route, times in arrivals.items():
        times.sort()
        if len(times) >= 2:
            final_data[route] = [times[0], times[1]]
        elif len(times) == 1:
            final_data[route] = [times[0], "-"]
            
    return final_data

def main():
    # 1. Interactive Station Selection
    stations_db = load_all_stations()
    if not stations_db:
        return
        
    print("\n" + "="*50)
    search_query = input("Enter a station name to search (e.g., 'Times Sq', 'Wall St'): ")
    
    # Filter dictionary based on search query
    matches = {k: v for k, v in stations_db.items() if search_query.lower() in v['name'].lower()}
    
    if not matches:
        print("[!] No stations found matching that query.")
        return
        
    print("\n--- MATCHING STATIONS ---")
    for sid, info in matches.items():
        print(f"ID: [{sid}] | Name: {info['name']} | Lines: ({info['routes']})")
        
    selected_id = input("\nEnter the exact ID (e.g., 120) from the brackets above: ")
    direction = input("Direction (N for Northbound/Uptown, S for Southbound/Downtown): ").upper()
    
    target_stop_id = f"{selected_id}{direction}"
    
    if selected_id not in stations_db:
        print("[!] Invalid Station ID.")
        return
        
    station_name = stations_db[selected_id]['name']
    
    # Ensure station name fits on OLED (max 16 chars approx)
    if len(station_name) > 16:
        station_name = station_name[:14] + ".."
        
    print(f"\n[+] Tracking initialized for: {station_name} ({target_stop_id})")
    
    # 2. Serial Communication & Main Loop
    try:
        ser = serial.Serial(ARDUINO_PORT, BAUD_RATE, timeout=1)
        print(f"[+] Serial Port {ARDUINO_PORT} opened. Streaming data...\n")
        
        while True:
            arrivals_data = get_live_arrivals(target_stop_id)
            
            if not arrivals_data:
                print("[-] No active trains found for this stop at the moment.")
                time.sleep(10)
                continue
                
            for route, times in arrivals_data.items():
                if times[0] == "-":
                    continue
                
                # Payload Format: Route, ETA1, ETA2, StationName
                # Example: N,2,7,Times Sq
                data_packet = f"{route},{times[0]},{times[1]},{station_name}\n"
                ser.write(data_packet.encode("ascii", "ignore"))
                print(f"STREAM -> Route: {route} | ETAs: {times[0]}m, {times[1]}m | Stop: {station_name}")
                
                time.sleep(5) # Display duration for each route
                
    except KeyboardInterrupt:
        print("\n[!] Program terminated by user.")
    except Exception as e:
        print(f"\n[!] Serial Error: {e}")
    finally:
        if 'ser' in locals() and ser.is_open:
            ser.close()

if __name__ == "__main__":
    main()