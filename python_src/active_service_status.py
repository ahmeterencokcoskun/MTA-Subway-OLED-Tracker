import argparse
import time
from collections import defaultdict

import requests
from google.transit import gtfs_realtime_pb2

HEADERS = {"User-Agent": "Mozilla/5.0"}

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

ALERTS_URL = "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/camsys%2Fsubway-alerts"

EXPECTED_ROUTES = [
    "1", "2", "3", "4", "5", "6", "7",
    "A", "B", "C", "D", "E", "F", "G", "J", "L", "M", "N", "Q", "R", "S", "W", "Z", "SI",
]


def fetch_trip_counts(session):
    """Return live trip counts grouped by route id."""
    route_counts = defaultdict(int)
    feed_health = {}

    for feed_name, feed_url in MTA_FEEDS.items():
        try:
            response = session.get(feed_url, timeout=8)
            response.raise_for_status()

            feed = gtfs_realtime_pb2.FeedMessage()
            feed.ParseFromString(response.content)

            updates = 0
            for entity in feed.entity:
                if not entity.HasField("trip_update"):
                    continue
                route_id = str(entity.trip_update.trip.route_id).upper().strip()
                if not route_id:
                    continue
                route_counts[route_id] += 1
                updates += 1

            feed_health[feed_name] = f"OK ({updates} trip updates)"
        except Exception as exc:
            feed_health[feed_name] = f"ERROR ({exc})"

    return route_counts, feed_health


def fetch_alert_counts(session):
    """Return active alert counts grouped by route id."""
    alert_counts = defaultdict(int)
    unscoped_alerts = 0

    try:
        response = session.get(ALERTS_URL, timeout=8)
        response.raise_for_status()

        feed = gtfs_realtime_pb2.FeedMessage()
        feed.ParseFromString(response.content)

        for entity in feed.entity:
            if not entity.HasField("alert"):
                continue

            matched_route = False
            for informed in entity.alert.informed_entity:
                route_id = str(getattr(informed, "route_id", "") or "").upper().strip()
                if route_id:
                    alert_counts[route_id] += 1
                    matched_route = True

            if not matched_route:
                unscoped_alerts += 1
    except Exception as exc:
        print(f"[!] Alert feed read error: {exc}")

    return alert_counts, unscoped_alerts


def print_status(target_route, route_counts, alert_counts, unscoped_alerts, feed_health):
    target_route = target_route.upper().strip()
    active = route_counts.get(target_route, 0) > 0
    trip_count = route_counts.get(target_route, 0)
    target_alerts = alert_counts.get(target_route, 0)

    print("\n" + "=" * 64)
    print(f"Route check: {target_route}")
    print(f"Live trip updates for {target_route}: {trip_count}")
    print(f"Route-scoped alerts for {target_route}: {target_alerts}")
    print(f"Unscoped subway alerts: {unscoped_alerts}")
    print(f"Service state: {'ACTIVE' if active else 'NO LIVE TRIPS SEEN'}")

    print("\nFeed health")
    for name in sorted(feed_health):
        print(f"- {name}: {feed_health[name]}")

    active_routes = sorted([r for r, c in route_counts.items() if c > 0])
    print("\nRoutes with live trips now:")
    print(", ".join(active_routes) if active_routes else "(none)")


def print_full_audit(route_counts, alert_counts, unscoped_alerts, feed_health):
    print("\n" + "=" * 64)
    print("FULL NETWORK SERVICE AUDIT")

    feed_errors = {name: status for name, status in feed_health.items() if status.startswith("ERROR")}
    print("\nFeed diagnostics")
    for name in sorted(feed_health):
        print(f"- {name}: {feed_health[name]}")

    print("\nRoute states")
    active_routes = []
    inactive_routes = []
    for route in EXPECTED_ROUTES:
        trips = route_counts.get(route, 0)
        alerts = alert_counts.get(route, 0)
        is_active = trips > 0
        state = "ACTIVE" if is_active else "NO LIVE TRIPS"
        print(f"- {route:>3}: {state:13} | trips={trips:3} | alerts={alerts:2}")
        if is_active:
            active_routes.append(route)
        else:
            inactive_routes.append(route)

    print("\nAnomalies")
    if feed_errors:
        print("- Feed errors present")
        for name in sorted(feed_errors):
            print(f"  {name}: {feed_errors[name]}")
    else:
        print("- No feed transport errors detected")

    routes_alert_no_trips = [r for r in EXPECTED_ROUTES if route_counts.get(r, 0) == 0 and alert_counts.get(r, 0) > 0]
    if routes_alert_no_trips:
        print(f"- Routes with alerts but no live trips: {', '.join(routes_alert_no_trips)}")
    else:
        print("- No route has alerts-without-trips condition")

    print(f"- Unscoped subway alerts: {unscoped_alerts}")

    print("\nSummary")
    print(f"- Active routes: {', '.join(active_routes) if active_routes else '(none)'}")
    print(f"- Inactive routes: {', '.join(inactive_routes) if inactive_routes else '(none)'}")


def parse_args():
    parser = argparse.ArgumentParser(description="MTA subway live service status checker")
    parser.add_argument("--route", default="S", help="Route to monitor in live mode (default: S)")
    parser.add_argument("--refresh", type=int, default=20, help="Refresh interval for live mode in seconds")
    parser.add_argument("--audit-once", action="store_true", help="Run one-shot full network audit and exit")
    return parser.parse_args()


def main():
    args = parse_args()
    target_route = str(args.route).strip().upper() or "S"
    refresh_seconds = max(5, int(args.refresh))

    session = requests.Session()
    session.headers.update(HEADERS)

    if args.audit_once:
        route_counts, feed_health = fetch_trip_counts(session)
        alert_counts, unscoped_alerts = fetch_alert_counts(session)
        print_full_audit(route_counts, alert_counts, unscoped_alerts, feed_health)
        session.close()
        return

    print(f"\nMonitoring route {target_route}. Refresh: {refresh_seconds}s")
    print("Press Ctrl+C to stop.\n")

    try:
        while True:
            route_counts, feed_health = fetch_trip_counts(session)
            alert_counts, unscoped_alerts = fetch_alert_counts(session)
            print_status(target_route, route_counts, alert_counts, unscoped_alerts, feed_health)
            time.sleep(refresh_seconds)
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        session.close()


if __name__ == "__main__":
    main()
