import math
import time
from collections import defaultdict
from dataclasses import dataclass, field
from io import StringIO
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd
import requests
import serial
from google.transit import gtfs_realtime_pb2

@dataclass
class TrackerConfig:
    arduino_port: str = "COM7"
    baud_rate: int = 115200
    serial_timeout: int = 1
    update_period_seconds: int = 20
    auto_fallback_when_no_service: bool = False
    headers: Dict[str, str] = field(default_factory=lambda: {"User-Agent": "Mozilla/5.0"})
    stations_csv_url: str = "http://web.mta.info/developers/data/nyct/subway/Stations.csv"
    alerts_url: str = "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/camsys%2Fsubway-alerts"
    mta_feeds: Dict[str, str] = field(
        default_factory=lambda: {
            "ACE": "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-ace",
            "BDFM": "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-bdfm",
            "G": "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-g",
            "JZ": "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-jz",
            "NQRW": "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-nqrw",
            "L": "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-l",
            "1234567S": "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs",
            "SIR": "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-si",
        }
    )


class FeedClient:
    def __init__(self, config: TrackerConfig):
        self.config = config
        self.session = requests.Session()
        self.session.headers.update(config.headers)

    def load_stations_df(self) -> Optional[pd.DataFrame]:
        print(">>> Downloading MTA Stations Database (CSV)...")
        df = None

        try:
            response = self.session.get(self.config.stations_csv_url, timeout=10)
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

    def fetch_trip_feeds(self) -> List[gtfs_realtime_pb2.FeedMessage]:
        feeds = []
        for feed_url in self.config.mta_feeds.values():
            try:
                response = self.session.get(feed_url, timeout=6)
                if response.status_code == 200:
                    feed = gtfs_realtime_pb2.FeedMessage()
                    feed.ParseFromString(response.content)
                    feeds.append(feed)
            except Exception:
                pass
        return feeds

    def fetch_alert_feed(self) -> Optional[gtfs_realtime_pb2.FeedMessage]:
        try:
            response = self.session.get(self.config.alerts_url, timeout=6)
            if response.status_code == 200:
                feed = gtfs_realtime_pb2.FeedMessage()
                feed.ParseFromString(response.content)
                return feed
        except Exception:
            pass
        return None

    def close(self):
        self.session.close()


class SerialPublisher:
    def __init__(self, config: TrackerConfig):
        self.config = config
        self.serial_port = None

    def open(self):
        self.serial_port = serial.Serial(
            self.config.arduino_port,
            self.config.baud_rate,
            timeout=self.config.serial_timeout,
        )

    def send_update(self, route: str, eta1: str, eta2: str, alert_flag: int, station_name: str, alert_msg: str):
        packet = f"{route},{eta1},{eta2},{alert_flag},{station_name},{alert_msg}\n"
        self.serial_port.write(packet.encode("ascii", "ignore"))
        print(f"Update: {packet.strip()}")

    def close(self):
        if self.serial_port is not None and self.serial_port.is_open:
            self.serial_port.close()


class TrackerService:
    def __init__(self, config: TrackerConfig, feed_client: FeedClient, serial_publisher: SerialPublisher):
        self.config = config
        self.feed_client = feed_client
        self.serial_publisher = serial_publisher

    def get_arrivals(
        self,
        stop_ids: List[str],
        route_id: str,
        trip_feeds: List[gtfs_realtime_pb2.FeedMessage],
    ) -> Tuple[str, str]:
        current_time = int(time.time())
        arrivals = []
        if isinstance(stop_ids, str):
            stop_ids = [stop_ids]
        stop_id_set = set(stop_ids)

        for feed in trip_feeds:
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

        arrivals.sort()
        eta1 = str(arrivals[0]) if len(arrivals) > 0 else "--"
        eta2 = str(arrivals[1]) if len(arrivals) > 1 else "--"
        return eta1, eta2

    def get_live_routes_at_stop(
        self,
        stop_ids: List[str],
        trip_feeds: List[gtfs_realtime_pb2.FeedMessage],
    ) -> List[Tuple[str, str, str, int]]:
        current_time = int(time.time())
        arrivals_by_route = defaultdict(list)
        if isinstance(stop_ids, str):
            stop_ids = [stop_ids]
        stop_id_set = set(stop_ids)

        for feed in trip_feeds:
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

        live = []
        for route, values in arrivals_by_route.items():
            values.sort()
            eta1 = str(values[0]) if len(values) > 0 else "--"
            eta2 = str(values[1]) if len(values) > 1 else "--"
            first_eta = values[0] if len(values) > 0 else 99999
            live.append((route, eta1, eta2, first_eta))

        live.sort(key=lambda item: item[3])
        return live

    def get_alert_details(self, route_id: str, alert_feed: Optional[gtfs_realtime_pb2.FeedMessage]) -> str:
        if not alert_feed:
            return "No details available"

        for entity in alert_feed.entity:
            if not entity.HasField("alert"):
                continue

            header = entity.alert.header_text
            if not header.translation:
                continue

            msg = header.translation[0].text
            clean_msg = sanitize_for_packet(msg, 200)

            for informed in entity.alert.informed_entity:
                informed_route = str(getattr(informed, "route_id", "") or "").upper().strip()
                target_route = route_id.upper().strip()
                if informed_route == target_route:
                    return clean_msg or "No details available"

        return "No details available"

    def select_station_and_routes(self, stations_df: pd.DataFrame):
        print("\n" + "=" * 50)
        search = input("Search Station (e.g. Jamaica): ").strip()
        matches = stations_df[stations_df["Stop Name"].str.contains(search, case=False, na=False)]

        if matches.empty:
            print("[!] No matches.")
            return None

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
            return None

        if selected_index < 0 or selected_index >= len(station_options):
            print("[!] Invalid selection.")
            return None

        selected_station_name = str(station_options.iloc[selected_index]["Stop Name"])
        available_lines = str(station_options.iloc[selected_index]["Daytime Routes"]).strip()

        direction = input("Direction (N/S): ").strip().upper()
        route_input = input(f"Line(s) to track ({available_lines} available): ").strip().upper()

        if direction not in ("N", "S"):
            print("[!] Direction must be N or S.")
            return None

        requested_routes = []
        for route_token in route_input.replace(",", " ").split():
            clean_route = sanitize_for_packet(route_token, 4)
            if clean_route:
                requested_routes.append(clean_route)

        if not requested_routes:
            print("[!] Invalid route input.")
            return None

        station_name = sanitize_for_packet(selected_station_name, 14)
        same_name_rows = stations_df[stations_df["Stop Name"] == selected_station_name].copy()
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

            valid_routes = []
            for route in requested_routes:
                if route in scheduled_lines:
                    valid_routes.append(route)
                else:
                    print(f"[!] Warning: Line '{route}' does not serve this station. Ignoring.")

            if not valid_routes:
                print("[!] Error: None of the entered lines serve this station. Please try again.")
                return None

            requested_routes = valid_routes

        return station_name, monitor_ids, requested_routes, direction

    def run(self):
        stations_df = self.feed_client.load_stations_df()
        if stations_df is None:
            print("Error loading stations: no reachable online source and no valid local CSV file found.")
            return

        selected = self.select_station_and_routes(stations_df)
        if selected is None:
            return

        station_name, monitor_ids, requested_routes, direction = selected

        try:
            self.serial_publisher.open()
            print(
                f"[+] Tracking {station_name} ({len(monitor_ids)} stop IDs, dir={direction}) "
                f"| Lines: {', '.join(requested_routes)}"
            )

            route_idx = 0
            while True:
                route_to_send = requested_routes[route_idx]
                route_idx = (route_idx + 1) % len(requested_routes)

                trip_feeds = self.feed_client.fetch_trip_feeds()
                alert_feed = self.feed_client.fetch_alert_feed()
                eta1, eta2 = self.get_arrivals(monitor_ids, route_to_send, trip_feeds)

                if self.config.auto_fallback_when_no_service and eta1 == "--":
                    live_routes = self.get_live_routes_at_stop(monitor_ids, trip_feeds)
                    if live_routes:
                        preview = ", ".join([f"{r}({e1},{e2})" for r, e1, e2, _ in live_routes[:8]])
                        print(f"[!] No live trips for {route_to_send}. Live routes at this station now: {preview}")

                        fallback_route, f_eta1, f_eta2, _ = live_routes[0]
                        route_to_send = fallback_route
                        eta1, eta2 = f_eta1, f_eta2
                        print(f"[+] Auto fallback -> {fallback_route} ({eta1}, {eta2})")
                    else:
                        print(f"[!] No live trips found at this station right now (requested: {route_to_send}).")

                alert_msg = self.get_alert_details(route_to_send, alert_feed)
                alert_flag = 0 if alert_msg == "No details available" else 1
                print(f"Tracking {route_to_send} -> Alert flag: {alert_flag}, msg: {alert_msg}")

                self.serial_publisher.send_update(route_to_send, eta1, eta2, alert_flag, station_name, alert_msg)
                time.sleep(self.config.update_period_seconds)
        except KeyboardInterrupt:
            print("\nStopped.")
        except Exception as exc:
            print(f"Serial Error: {exc}")
        finally:
            self.serial_publisher.close()
            self.feed_client.close()


def sanitize_for_packet(text, max_len):
    """Prepare a value for serial packet transport."""
    clean = str(text or "")
    clean = clean.replace("|", " ").replace(",", " ").replace("\n", " ").replace("\r", " ").strip()
    clean = clean.encode("ascii", "ignore").decode("ascii")
    return clean[:max_len]

if __name__ == "__main__":
    cfg = TrackerConfig()
    client = FeedClient(cfg)
    publisher = SerialPublisher(cfg)
    service = TrackerService(cfg, client, publisher)
    service.run()