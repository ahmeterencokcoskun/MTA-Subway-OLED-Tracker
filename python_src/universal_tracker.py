import math
import time
from collections import defaultdict
from io import StringIO
from pathlib import Path

import pandas as pd
import requests
import serial
from google.transit import gtfs_realtime_pb2

# --- CONFIGURATION ---
ARDUINO_PORT = "COM7"
BAUD_RATE = 9600
HEADERS = {"User-Agent": "Mozilla/5.0"}

STATIONS_CSV_URL = "http://web.mta.info/developers/data/nyct/subway/Stations.csv"
ALERTS_URL = "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/camsys%2Fsubway-alerts"

MTA_FEEDS = {
    "ACE": "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-ace",
    "BDFM": "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-bdfm",
    "G": "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-g",
    "JZ": "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-jz",
    "NQRW": "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-nqrw",
    "L": "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-l",
    "1234567S": "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs",
    "SIR": "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-si",
}

AUTO_FALLBACK_WHEN_NO_SERVICE = True


def sanitize_for_packet(text, max_len):
    """Prepare a value for serial packet transport."""
    clean = str(text or "")
    clean = clean.replace("|", " ").replace(",", " ").replace("\n", " ").replace("\r", " ").strip()
    clean = clean.encode("ascii", "ignore").decode("ascii")
    return clean[:max_len]


def load_stations_df(session):
    """Load stations table from online source, fallback to local CSV if blocked."""
    print(">>> Downloading MTA Stations Database (CSV)...")
    df = None

    try:
        response = session.get(STATIONS_CSV_URL, timeout=10)
        response.raise_for_status()
        df = pd.read_csv(StringIO(response.text))
    except Exception as exc:
        print(f"[!] Online station CSV unavailable: {exc}")

    if df is None:
        candidates = [
            Path(__file__).resolve().parent.parent / "nyc_subway_stations_list.csv",
            Path(__file__).resolve().parent / "nyc_subway_stations_list.csv",
            Path.cwd() / "nyc_subway_stations_list.csv",
            Path.home() / "Desktop" / "nyc_subway_stations_list.csv",
        ]

        for candidate in candidates:
            if candidate.exists():
                try:
                    df = pd.read_csv(candidate)
                    print(f"[+] Loaded stations from local file: {candidate}")
                    break
                except Exception as exc:
                    print(f"[!] Failed reading local CSV ({candidate}): {exc}")

    if df is None:
        return None

    # Normalize possible column variants from online/local CSV files.
    rename_map = {
        "Station_ID": "GTFS Stop ID",
        "Station_Name": "Stop Name",
        "Lines": "Daytime Routes",
    }
    df = df.rename(columns=rename_map)

    required = ["GTFS Stop ID", "Stop Name", "Borough", "Daytime Routes"]
    for col in required:
        if col not in df.columns:
            df[col] = ""

    df = df[required].copy()
    df["GTFS Stop ID"] = df["GTFS Stop ID"].astype(str)
    df = df[df["GTFS Stop ID"].str.lower() != "nan"]
    return df


def get_arrivals(stop_ids, route_id, session):
    current_time = int(time.time())
    arrivals = []
    if isinstance(stop_ids, str):
        stop_ids = [stop_ids]
    stop_id_set = set(stop_ids)

    for feed_url in MTA_FEEDS.values():
        try:
            response = session.get(feed_url, timeout=6)
            response.raise_for_status()

            feed = gtfs_realtime_pb2.FeedMessage()
            feed.ParseFromString(response.content)

            for entity in feed.entity:
                if not entity.HasField("trip_update"):
                    continue

                trip = entity.trip_update.trip
                if str(trip.route_id).upper() != route_id.upper():
                    continue

                for stop_update in entity.trip_update.stop_time_update:
                    if stop_update.stop_id not in stop_id_set:
                        continue
                    if not stop_update.HasField("arrival"):
                        continue

                    diff = math.floor((stop_update.arrival.time - current_time) / 60)
                    if diff >= 0:
                        arrivals.append(diff)
        except Exception:
            continue

    arrivals.sort()
    eta1 = str(arrivals[0]) if len(arrivals) > 0 else "--"
    eta2 = str(arrivals[1]) if len(arrivals) > 1 else "--"
    return eta1, eta2


def get_best_route_at_stop(stop_ids, session):
    """Find the best live route at a stop by nearest ETA."""
    current_time = int(time.time())
    arrivals_by_route = defaultdict(list)
    if isinstance(stop_ids, str):
        stop_ids = [stop_ids]
    stop_id_set = set(stop_ids)

    for feed_url in MTA_FEEDS.values():
        try:
            response = session.get(feed_url, timeout=6)
            response.raise_for_status()

            feed = gtfs_realtime_pb2.FeedMessage()
            feed.ParseFromString(response.content)

            for entity in feed.entity:
                if not entity.HasField("trip_update"):
                    continue

                route = str(entity.trip_update.trip.route_id).upper().strip()
                if not route:
                    continue

                for stop_update in entity.trip_update.stop_time_update:
                    if stop_update.stop_id not in stop_id_set:
                        continue
                    if not stop_update.HasField("arrival"):
                        continue

                    diff = math.floor((stop_update.arrival.time - current_time) / 60)
                    if diff >= 0:
                        arrivals_by_route[route].append(diff)
        except Exception:
            continue

    if not arrivals_by_route:
        return None, "--", "--"

    best_route = None
    best_first_eta = None
    best_etas = []

    for route, values in arrivals_by_route.items():
        values.sort()
        first_eta = values[0]
        if best_first_eta is None or first_eta < best_first_eta:
            best_first_eta = first_eta
            best_route = route
            best_etas = values

    eta1 = str(best_etas[0]) if len(best_etas) > 0 else "--"
    eta2 = str(best_etas[1]) if len(best_etas) > 1 else "--"
    return best_route, eta1, eta2


def get_live_routes_at_stop(stop_ids, session):
    """Return all live routes at the stop with their next 2 ETAs."""
    current_time = int(time.time())
    arrivals_by_route = defaultdict(list)
    if isinstance(stop_ids, str):
        stop_ids = [stop_ids]
    stop_id_set = set(stop_ids)

    for feed_url in MTA_FEEDS.values():
        try:
            response = session.get(feed_url, timeout=6)
            response.raise_for_status()

            feed = gtfs_realtime_pb2.FeedMessage()
            feed.ParseFromString(response.content)

            for entity in feed.entity:
                if not entity.HasField("trip_update"):
                    continue

                route = str(entity.trip_update.trip.route_id).upper().strip()
                if not route:
                    continue

                for stop_update in entity.trip_update.stop_time_update:
                    if stop_update.stop_id not in stop_id_set:
                        continue
                    if not stop_update.HasField("arrival"):
                        continue

                    diff = math.floor((stop_update.arrival.time - current_time) / 60)
                    if diff >= 0:
                        arrivals_by_route[route].append(diff)
        except Exception:
            continue

    live = []
    for route, values in arrivals_by_route.items():
        values.sort()
        eta1 = str(values[0]) if len(values) > 0 else "--"
        eta2 = str(values[1]) if len(values) > 1 else "--"
        first_eta = values[0] if len(values) > 0 else 99999
        live.append((route, eta1, eta2, first_eta))

    live.sort(key=lambda item: item[3])
    return live


def get_alert_details(route_id, session):
    """Fetch alert text and sanitize commas/newlines for serial parsing."""
    try:
        response = session.get(ALERTS_URL, timeout=6)
        response.raise_for_status()

        feed = gtfs_realtime_pb2.FeedMessage()
        feed.ParseFromString(response.content)

        first_any_alert = None

        for entity in feed.entity:
            if not entity.HasField("alert"):
                continue

            header = entity.alert.header_text
            if not header.translation:
                continue

            msg = header.translation[0].text
            # OLED detail view can render up to ~84 chars (4 lines x 21 chars).
            clean_msg = sanitize_for_packet(msg, 84)
            if clean_msg and first_any_alert is None:
                first_any_alert = clean_msg

            for informed in entity.alert.informed_entity:
                informed_route = str(getattr(informed, "route_id", "") or "").upper().strip()
                target_route = route_id.upper().strip()
                if informed_route == target_route:
                    return clean_msg or "No details available"

        # Fallback: if there is any active alert in the feed, surface it.
        if first_any_alert:
            return first_any_alert
    except Exception:
        pass

    return "No details available"


def main():
    session = requests.Session()
    session.headers.update(HEADERS)

    stations_df = load_stations_df(session)
    if stations_df is None:
        print("Error loading stations: no reachable online source and no valid local CSV file found.")
        return

    print("\n" + "=" * 50)
    search = input("Search Station (e.g. Jamaica): ").strip()
    matches = stations_df[stations_df["Stop Name"].str.contains(search, case=False, na=False)]

    if matches.empty:
        print("[!] No matches.")
        return

    station_options = (
        matches[["Stop Name", "Borough", "Daytime Routes"]]
        .drop_duplicates()
        .reset_index(drop=True)
    )

    print("\nMatching stations:")
    for idx, row in station_options.iterrows():
        print(
            f"[{idx + 1}] {row['Stop Name']} "
            f"| Borough: {row['Borough']} "
            f"| Lines: {row['Daytime Routes']}"
        )

    try:
        selected_index = int(input("\nSelect station number: ").strip()) - 1
    except ValueError:
        print("[!] Invalid selection.")
        return

    if selected_index < 0 or selected_index >= len(station_options):
        print("[!] Invalid selection.")
        return

    selected_station_name = str(station_options.iloc[selected_index]["Stop Name"])
    direction = input("Direction (N/S): ").strip().upper()
    route_id = sanitize_for_packet(input("Line: ").strip().upper(), 4)

    if direction not in ("N", "S"):
        print("[!] Direction must be N or S.")
        return
    if not route_id:
        print("[!] Invalid route input.")
        return

    station_full_name = selected_station_name
    station_name = sanitize_for_packet(station_full_name, 14)

    # Some stations share the same name across multiple stop IDs.
    same_name_rows = stations_df[stations_df["Stop Name"] == station_full_name].copy()
    same_name_rows = same_name_rows.drop_duplicates(subset=["GTFS Stop ID", "Daytime Routes", "Borough"])
    monitor_ids = sorted({f"{str(sid)}{direction}" for sid in same_name_rows["GTFS Stop ID"].tolist()})

    if len(same_name_rows) > 1:
        print("\n[+] Same-name station variants (all will be monitored):")
        print(same_name_rows[["GTFS Stop ID", "Stop Name", "Borough", "Daytime Routes"]].to_string(index=False))

    scheduled_lines = set()
    for routes in same_name_rows["Daytime Routes"].fillna("").astype(str):
        for token in routes.replace("/", " ").replace(",", " ").split():
            cleaned = token.strip().upper()
            if cleaned:
                scheduled_lines.add(cleaned)
    if scheduled_lines:
        print(f"[i] Scheduled/daytime lines here: {' '.join(sorted(scheduled_lines))}")

    ser = None
    try:
        ser = serial.Serial(ARDUINO_PORT, BAUD_RATE, timeout=1)
        print(f"[+] Tracking {station_name} ({len(monitor_ids)} stop IDs, dir={direction}) | Line: {route_id}")

        while True:
            route_to_send = route_id
            eta1, eta2 = get_arrivals(monitor_ids, route_id, session)

            if AUTO_FALLBACK_WHEN_NO_SERVICE and eta1 == "--":
                live_routes = get_live_routes_at_stop(monitor_ids, session)
                if live_routes:
                    preview = ", ".join([f"{r}({e1},{e2})" for r, e1, e2, _ in live_routes[:8]])
                    print(f"[!] No live trips for {route_id}. Live routes at this station now: {preview}")

                    fallback_route, f_eta1, f_eta2, _ = live_routes[0]
                    route_to_send = fallback_route
                    eta1, eta2 = f_eta1, f_eta2
                    print(f"[+] Auto fallback -> {fallback_route} ({eta1}, {eta2})")
                else:
                    print(f"[!] No live trips found at this station right now (requested: {route_id}).")

            alert_msg = get_alert_details(route_to_send, session)
            alert_flag = 0 if alert_msg == "No details available" else 1
            print(f"Alert state -> flag: {alert_flag}, msg: {alert_msg}")

            # Packet: Route,ETA1,ETA2,AlertFlag,StationName,AlertMsg
            packet = f"{route_to_send},{eta1},{eta2},{alert_flag},{station_name},{alert_msg}\n"
            ser.write(packet.encode("ascii", "ignore"))
            print(f"Update: {packet.strip()}")
            time.sleep(20)
    except KeyboardInterrupt:
        print("\nStopped.")
    except Exception as exc:
        print(f"Serial Error: {exc}")
    finally:
        if ser is not None and ser.is_open:
            ser.close()
        session.close()


if __name__ == "__main__":
    main()