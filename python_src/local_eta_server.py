from typing import List, Optional
import asyncio

from fastapi import FastAPI, HTTPException, Query
import uvicorn

from universal_tracker import FeedClient, SerialPublisher, TrackerConfig, TrackerService, sanitize_for_packet

app = FastAPI(title="Local ETA Server")

config = TrackerConfig()
feed_client = FeedClient(config)
# TrackerService methods used here do not require serial access.
tracker_service = TrackerService(config, feed_client, serial_publisher=None)
stations_df = feed_client.load_stations_df()
AUTO_ROUTE_TOKENS = {"", "AUTO", "*", "ANY"}
ACTIVE_QUERY = {
    "route": "",
    "station": "JAMAICA",
    "direction": "N",
    "stop_ids": None,
}


def split_routes(raw_routes: str) -> List[str]:
    routes = []
    for token in str(raw_routes or "").replace("/", " ").replace(",", " ").split():
        clean = sanitize_for_packet(token.upper(), 6)
        if clean:
            routes.append(clean)
    return routes


def get_all_routes() -> List[str]:
    if stations_df is None:
        return []

    routes = set()
    for value in stations_df.get("Daytime Routes", []):
        for route in split_routes(value):
            routes.add(route)
    return sorted(routes)


def get_station_catalog() -> List[dict]:
    if stations_df is None:
        return []

    catalog = {}
    for _, row in stations_df.iterrows():
        name = str(row.get("Stop Name", "")).strip()
        borough = str(row.get("Borough", "")).strip()
        stop_id = str(row.get("GTFS Stop ID", "")).strip()
        if not name:
            continue

        key = (name.upper(), borough.upper())
        if key not in catalog:
            catalog[key] = {
                "name": sanitize_for_packet(name.upper(), 80),
                "borough": sanitize_for_packet(borough.upper(), 20),
                "lines": set(),
                "stop_ids": set(),
            }

        for route in split_routes(row.get("Daytime Routes", "")):
            catalog[key]["lines"].add(route)

        if stop_id and stop_id.lower() != "nan":
            catalog[key]["stop_ids"].add(stop_id.upper())

    result = []
    for station in catalog.values():
        result.append(
            {
                "name": station["name"],
                "borough": station["borough"],
                "lines": sorted(station["lines"]),
                "stop_ids": sorted(station["stop_ids"]),
            }
        )
    result.sort(key=lambda item: (item["name"], item["borough"]))
    return result


def parse_csv_tokens(raw: str) -> List[str]:
    return [token.strip() for token in raw.replace(";", ",").split(",") if token.strip()]


def build_monitor_ids(stop_ids_raw: Optional[str], station: str, direction: str) -> List[str]:
    if stop_ids_raw:
        ids = []
        for sid in parse_csv_tokens(stop_ids_raw):
            normalized = sid.upper()
            if normalized.endswith("N") or normalized.endswith("S"):
                ids.append(normalized)
            else:
                ids.append(f"{normalized}{direction}")
        return sorted(set(ids))

    if stations_df is None:
        return []

    matches = stations_df[stations_df["Stop Name"].str.contains(station, case=False, na=False)].copy()
    if matches.empty:
        return []

    return sorted({f"{str(sid)}{direction}" for sid in matches["GTFS Stop ID"].tolist()})


@app.get("/eta")
def eta(
    route: Optional[str] = Query(None),
    station: Optional[str] = Query(None),
    direction: Optional[str] = Query(None),
    stop_ids: Optional[str] = Query(None),
    fallback_eta1: str = Query("--"),
    fallback_eta2: str = Query("--"),
):
    route_input = route if route is not None else ACTIVE_QUERY.get("route", "")
    station_input = station if station else ACTIVE_QUERY.get("station", "JAMAICA")
    direction_input = direction if direction else ACTIVE_QUERY.get("direction", "N")
    stop_ids_input = stop_ids if stop_ids is not None else ACTIVE_QUERY.get("stop_ids")

    raw_route = (route_input or "").strip().upper()
    route_clean = sanitize_for_packet(raw_route, 6)
    station_clean = sanitize_for_packet(str(station_input).upper(), 14)
    direction_clean = str(direction_input).strip().upper()
    if direction_clean not in ("N", "S"):
        raise HTTPException(status_code=400, detail="direction must be N or S")

    monitor_ids = build_monitor_ids(stop_ids_input, station_clean, direction_clean)
    if not monitor_ids:
        return {
            "route": route_clean,
            "eta1": fallback_eta1,
            "eta2": fallback_eta2,
            "station": station_clean,
            "alert_flag": 0,
            "alert_msg": "No details available",
            "monitor_ids": [],
        }

    trip_feeds = feed_client.fetch_trip_feeds()
    alert_feed = feed_client.fetch_alert_feed()

    selected_route = route_clean
    eta1 = fallback_eta1
    eta2 = fallback_eta2
    live_routes = []

    # Legacy behavior: if route is unknown, pick the nearest live route at this station.
    if route_clean in AUTO_ROUTE_TOKENS:
        live_routes = tracker_service.get_live_routes_at_stop(monitor_ids, trip_feeds)
        if live_routes:
            selected_route, eta1, eta2, _ = live_routes[0]
    else:
        eta1, eta2 = tracker_service.get_arrivals(monitor_ids, route_clean, trip_feeds)
        if eta1 == "--":
            live_routes = tracker_service.get_live_routes_at_stop(monitor_ids, trip_feeds)
            if live_routes:
                selected_route, eta1, eta2, _ = live_routes[0]

    alert_route = selected_route if selected_route else route_clean
    alert_msg = tracker_service.get_alert_details(alert_route, alert_feed)
    alert_flag = 0 if alert_msg == "No details available" else 1

    return {
        "requested_route": route_clean,
        "route": selected_route,
        "eta1": eta1,
        "eta2": eta2,
        "station": station_clean,
        "alert_flag": alert_flag,
        "alert_msg": sanitize_for_packet(alert_msg, 200),
        "monitor_ids": monitor_ids,
        "live_routes": [
            {"route": route_id, "eta1": r_eta1, "eta2": r_eta2}
            for route_id, r_eta1, r_eta2, _ in live_routes[:8]
        ],
    }


@app.get("/health")
def health():
    return {"ok": True, "stations_loaded": stations_df is not None}


@app.get("/meta/routes")
def meta_routes():
    routes = get_all_routes()
    return {"count": len(routes), "routes": routes}


@app.get("/meta/stations")
def meta_stations():
    stations = get_station_catalog()
    return {"count": len(stations), "stations": stations}


@app.post("/set_active_query")
def set_active_query(
    route: Optional[str] = Query(None),
    station: str = Query("JAMAICA"),
    direction: str = Query("N"),
    stop_ids: Optional[str] = Query(None),
):
    direction_clean = direction.strip().upper()
    if direction_clean not in ("N", "S"):
        raise HTTPException(status_code=400, detail="direction must be N or S")

    ACTIVE_QUERY["route"] = sanitize_for_packet((route or "").upper(), 6)
    ACTIVE_QUERY["station"] = sanitize_for_packet(station.upper(), 14)
    ACTIVE_QUERY["direction"] = direction_clean
    ACTIVE_QUERY["stop_ids"] = stop_ids.strip().upper() if stop_ids and stop_ids.strip() else None
    return {"ok": True, "active_query": ACTIVE_QUERY}


@app.get("/active_query")
def active_query():
    return {"active_query": ACTIVE_QUERY}


@app.post("/push_to_arduino")
def push_to_arduino(
    route: str = Query(""),
    eta1: str = Query("--"),
    eta2: str = Query("--"),
    alert_flag: int = Query(0),
    station: str = Query("UNKNOWN"),
    alert_msg: str = Query("No details available"),
    serial_port: Optional[str] = Query(None),
):
    if not serial_port or not serial_port.strip():
        raise HTTPException(status_code=400, detail="serial_port gerekli (ornek: COM3)")

    cfg = TrackerConfig()
    cfg.arduino_port = serial_port.strip()

    publisher = SerialPublisher(cfg)
    route_clean = sanitize_for_packet(route.upper(), 6)
    eta1_clean = sanitize_for_packet(eta1, 8)
    eta2_clean = sanitize_for_packet(eta2, 8)
    station_clean = sanitize_for_packet(station.upper(), 14)
    msg_clean = sanitize_for_packet(alert_msg, 200)
    flag_clean = 1 if int(alert_flag) else 0

    try:
        publisher.open()
        publisher.send_update(route_clean, eta1_clean, eta2_clean, flag_clean, station_clean, msg_clean)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Serial send failed on {cfg.arduino_port}: {exc}")
    finally:
        publisher.close()

    return {
        "ok": True,
        "port": cfg.arduino_port,
        "packet": {
            "route": route_clean,
            "eta1": eta1_clean,
            "eta2": eta2_clean,
            "alert_flag": flag_clean,
            "station": station_clean,
            "alert_msg": msg_clean,
        },
    }


if __name__ == "__main__":
    # On some Windows setups, Proactor loop startup can fail with WinError 10013.
    if hasattr(asyncio, "WindowsSelectorEventLoopPolicy"):
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    uvicorn.run(app, host="0.0.0.0", port=8000, loop="asyncio")
