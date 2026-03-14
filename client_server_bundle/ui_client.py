import json
import re
import socket
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk
from urllib.parse import urlparse

import requests


class EtaUiClient(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("MTA ETA Client UI")
        self.geometry("1020x820")

        self.bundle_dir = Path(__file__).resolve().parent
        self.server_script = self.bundle_dir / "local_eta_server.py"
        self.server_process = None
        self.server_logs = []

        self.all_routes = []
        self.station_catalog = []
        self.station_index = {}
        self.last_eta_payload = None

        self.base_url_var = tk.StringVar(value="http://127.0.0.1:8000")
        self.route_var = tk.StringVar(value="")
        self.station_var = tk.StringVar(value="JAMAICA")
        self.direction_var = tk.StringVar(value="N")
        self.stop_ids_var = tk.StringVar(value="")
        self.arduino_port_var = tk.StringVar(value="")

        self.auto_refresh_var = tk.BooleanVar(value=False)
        self.refresh_interval_var = tk.StringVar(value="10")
        self.refresh_success = 0
        self.refresh_fail = 0
        self.auto_refresh_job = None
        self.last_update_var = tk.StringVar(value="-")

        self.alert_history = []
        self.alert_only_var = tk.BooleanVar(value=False)

        self.metrics_var = tk.StringVar(value="metrics: -")

        self.api_profiles = {
            "localhost": "http://127.0.0.1:8000",
            "hotspot": "http://192.168.137.1:8000",
            "home-lan": "http://192.168.1.228:8000",
        }
        self.api_profile_var = tk.StringVar(value="localhost")

        self.favorites_file = self.bundle_dir / "ui_favorites.json"
        self.favorites = {}
        self.favorite_var = tk.StringVar(value="")

        self.status_var = tk.StringVar(value="Ready")
        self._build_ui()
        self._load_favorites()

        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def _build_ui(self):
        root = ttk.Frame(self, padding=12)
        root.pack(fill=tk.BOTH, expand=True)

        server_box = ttk.LabelFrame(root, text="Server", padding=10)
        server_box.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(server_box, text="Base URL").grid(row=0, column=0, sticky="w")
        ttk.Entry(server_box, textvariable=self.base_url_var, width=40).grid(row=0, column=1, sticky="we", padx=6)
        ttk.Button(server_box, text="Start Server", command=self.start_server).grid(row=0, column=2, padx=4)
        ttk.Button(server_box, text="Stop Server", command=self.stop_server).grid(row=0, column=3, padx=4)
        ttk.Button(server_box, text="Health", command=self.check_health).grid(row=0, column=4, padx=4)
        ttk.Button(server_box, text="Metrics", command=self.refresh_metrics).grid(row=0, column=5, padx=4)

        ttk.Label(server_box, text="API Profile").grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Combobox(
            server_box,
            textvariable=self.api_profile_var,
            values=list(self.api_profiles.keys()),
            width=12,
            state="readonly",
        ).grid(row=1, column=1, sticky="w", pady=(8, 0), padx=6)
        ttk.Button(server_box, text="Apply Profile", command=self.apply_api_profile).grid(row=1, column=2, padx=4, pady=(8, 0))
        ttk.Button(server_box, text="Port Inspector", command=self.inspect_port_8000).grid(row=1, column=3, padx=4, pady=(8, 0))
        ttk.Button(server_box, text="Kill Port 8000", command=self.kill_port_8000).grid(row=1, column=4, padx=4, pady=(8, 0))
        ttk.Button(server_box, text="Export Logs", command=self.export_logs).grid(row=1, column=5, padx=4, pady=(8, 0))

        ttk.Label(server_box, textvariable=self.metrics_var, anchor="w").grid(row=2, column=0, columnspan=6, sticky="we", pady=(8, 0))
        server_box.columnconfigure(1, weight=1)

        query_box = ttk.LabelFrame(root, text="ETA Query", padding=10)
        query_box.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(query_box, text="Route (optional)").grid(row=0, column=0, sticky="w")
        self.route_combo = ttk.Combobox(query_box, textvariable=self.route_var, width=12)
        self.route_combo.grid(row=0, column=1, sticky="w", padx=(6, 18))

        ttk.Label(query_box, text="Station").grid(row=0, column=2, sticky="w")
        self.station_combo = ttk.Combobox(query_box, textvariable=self.station_var, width=28)
        self.station_combo.grid(row=0, column=3, sticky="w", padx=(6, 18))
        self.station_combo.bind("<<ComboboxSelected>>", self.on_station_selected)

        ttk.Label(query_box, text="Direction").grid(row=0, column=4, sticky="w")
        ttk.Combobox(
            query_box,
            textvariable=self.direction_var,
            values=["N", "S"],
            width=5,
            state="readonly",
        ).grid(row=0, column=5, sticky="w", padx=(6, 0))

        ttk.Label(query_box, text="Stop IDs (optional, comma-separated)").grid(row=1, column=0, columnspan=3, sticky="w", pady=(10, 0))
        ttk.Entry(query_box, textvariable=self.stop_ids_var, width=48).grid(row=1, column=3, columnspan=3, sticky="we", padx=(6, 0), pady=(10, 0))

        ttk.Label(query_box, text="Serial Port (optional, for serial push)").grid(row=2, column=0, sticky="w", pady=(10, 0))
        ttk.Entry(query_box, textvariable=self.arduino_port_var, width=12).grid(row=2, column=1, sticky="w", padx=(6, 18), pady=(10, 0))

        ttk.Button(query_box, text="Fetch ETA", command=self.fetch_eta).grid(row=3, column=0, columnspan=2, sticky="we", pady=(12, 0))
        ttk.Button(query_box, text="Send to Arduino", command=self.send_to_arduino).grid(row=3, column=2, columnspan=2, sticky="we", pady=(12, 0), padx=(6, 6))
        ttk.Button(query_box, text="Route+Station List", command=self.show_catalog).grid(row=3, column=4, columnspan=2, sticky="we", pady=(12, 0))

        ttk.Checkbutton(query_box, text="Auto Refresh", variable=self.auto_refresh_var, command=self.toggle_auto_refresh).grid(row=4, column=0, sticky="w", pady=(10, 0))
        ttk.Label(query_box, text="Interval").grid(row=4, column=1, sticky="e", pady=(10, 0))
        ttk.Combobox(
            query_box,
            textvariable=self.refresh_interval_var,
            values=["5", "10", "20"],
            width=5,
            state="readonly",
        ).grid(row=4, column=2, sticky="w", pady=(10, 0), padx=(6, 0))
        ttk.Label(query_box, textvariable=self.last_update_var).grid(row=4, column=3, columnspan=3, sticky="w", pady=(10, 0))

        fav_box = ttk.LabelFrame(root, text="Favorites", padding=10)
        fav_box.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(fav_box, text="Favorite").grid(row=0, column=0, sticky="w")
        self.favorite_combo = ttk.Combobox(fav_box, textvariable=self.favorite_var, width=28)
        self.favorite_combo.grid(row=0, column=1, padx=6, sticky="w")
        ttk.Button(fav_box, text="Save Current", command=self.save_current_favorite).grid(row=0, column=2, padx=4)
        ttk.Button(fav_box, text="Load", command=self.load_selected_favorite).grid(row=0, column=3, padx=4)
        ttk.Button(fav_box, text="Delete", command=self.delete_selected_favorite).grid(row=0, column=4, padx=4)

        output_box = ttk.LabelFrame(root, text="Response", padding=10)
        output_box.pack(fill=tk.BOTH, expand=True)

        self.output = tk.Text(output_box, wrap=tk.WORD, font=("Consolas", 10), height=14)
        self.output.pack(fill=tk.BOTH, expand=True)

        alerts_box = ttk.LabelFrame(root, text="Alert History", padding=10)
        alerts_box.pack(fill=tk.BOTH, expand=True, pady=(10, 0))

        ttk.Checkbutton(alerts_box, text="Show alerts only", variable=self.alert_only_var, command=self.refresh_alert_history_view).pack(anchor="w")
        self.alert_text = tk.Text(alerts_box, wrap=tk.WORD, font=("Consolas", 9), height=8)
        self.alert_text.pack(fill=tk.BOTH, expand=True)

        status_bar = ttk.Label(root, textvariable=self.status_var, anchor="w")
        status_bar.pack(fill=tk.X, pady=(10, 0))

    def set_status(self, message):
        self.status_var.set(message)
        self.update_idletasks()

    def append_output(self, text):
        self.output.delete("1.0", tk.END)
        self.output.insert(tk.END, text)

    def append_log_line(self, line):
        self.server_logs.append(line)
        if len(self.server_logs) > 300:
            self.server_logs = self.server_logs[-300:]

    def render_server_logs(self, header=None):
        logs_text = "\n".join(self.server_logs[-80:]) if self.server_logs else "(no logs)"
        if header:
            self.append_output(f"{header}\n\n{logs_text}")
        else:
            self.append_output(logs_text)

    def _stream_server_output(self, pipe, label):
        try:
            for line in iter(pipe.readline, ""):
                text = line.rstrip("\n")
                if text:
                    self.append_log_line(f"[{label}] {text}")
        finally:
            try:
                pipe.close()
            except Exception:
                pass

    def _start_log_threads(self):
        if self.server_process is None:
            return
        threading.Thread(
            target=self._stream_server_output,
            args=(self.server_process.stdout, "STDOUT"),
            daemon=True,
        ).start()
        threading.Thread(
            target=self._stream_server_output,
            args=(self.server_process.stderr, "STDERR"),
            daemon=True,
        ).start()

    def _poll_server_process(self):
        if self.server_process is None:
            return

        exit_code = self.server_process.poll()
        if exit_code is None:
            self.after(1000, self._poll_server_process)
            return

        self.set_status(f"Server exited with code {exit_code}.")
        self.render_server_logs(header=f"Server exited with code {exit_code}")
        self.server_process = None

    def _get_json(self, path, params=None, timeout=10):
        url = f"{self.base_url_var.get().rstrip('/')}{path}"
        response = requests.get(url, params=params, timeout=timeout)
        response.raise_for_status()
        return response.json()

    def _refresh_route_options(self, preferred=None):
        values = [""] + self.all_routes if self.all_routes else [""]
        self.route_combo["values"] = values
        if preferred is not None:
            self.route_var.set(preferred)

    def _refresh_station_options(self):
        names = [item["name"] for item in self.station_catalog]
        self.station_combo["values"] = names

    def _parse_base_url(self):
        raw = self.base_url_var.get().strip()
        parsed = urlparse(raw)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        return host, port

    def _is_port_in_use(self, port):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.bind(("127.0.0.1", port))
            return False
        except OSError:
            return True
        finally:
            sock.close()

    def _verify_active_query(self, expected):
        payload = self._get_json("/active_query", timeout=8)
        active = payload.get("active_query", {})

        expected_norm = {
            "route": (expected.get("route") or "").strip().upper(),
            "station": (expected.get("station") or "").strip().upper(),
            "direction": (expected.get("direction") or "").strip().upper(),
            "stop_ids": (expected.get("stop_ids") or "").strip().upper() or None,
        }
        active_norm = {
            "route": str(active.get("route") or "").strip().upper(),
            "station": str(active.get("station") or "").strip().upper(),
            "direction": str(active.get("direction") or "").strip().upper(),
            "stop_ids": str(active.get("stop_ids") or "").strip().upper() or None,
        }
        return expected_norm == active_norm, payload

    def _load_favorites(self):
        if self.favorites_file.exists():
            try:
                self.favorites = json.loads(self.favorites_file.read_text(encoding="utf-8"))
            except Exception:
                self.favorites = {}
        else:
            self.favorites = {}
        self.favorite_combo["values"] = sorted(self.favorites.keys())

    def _save_favorites(self):
        self.favorites_file.write_text(json.dumps(self.favorites, indent=2, ensure_ascii=True), encoding="utf-8")
        self.favorite_combo["values"] = sorted(self.favorites.keys())

    def save_current_favorite(self):
        name = simpledialog.askstring("Save Favorite", "Favorite name:")
        if not name:
            return
        self.favorites[name] = {
            "route": self.route_var.get().strip(),
            "station": self.station_var.get().strip(),
            "direction": self.direction_var.get().strip().upper(),
            "stop_ids": self.stop_ids_var.get().strip(),
        }
        self._save_favorites()
        self.favorite_var.set(name)
        self.set_status(f"Favorite saved: {name}")

    def load_selected_favorite(self):
        name = self.favorite_var.get().strip()
        fav = self.favorites.get(name)
        if not fav:
            self.set_status("Favorite not found.")
            return
        self.route_var.set(fav.get("route", ""))
        self.station_var.set(fav.get("station", ""))
        self.direction_var.set(fav.get("direction", "N"))
        self.stop_ids_var.set(fav.get("stop_ids", ""))
        self.set_status(f"Favorite loaded: {name}")

    def delete_selected_favorite(self):
        name = self.favorite_var.get().strip()
        if not name or name not in self.favorites:
            return
        del self.favorites[name]
        self._save_favorites()
        self.favorite_var.set("")
        self.set_status(f"Favorite deleted: {name}")

    def apply_api_profile(self):
        profile = self.api_profile_var.get().strip()
        url = self.api_profiles.get(profile)
        if not url:
            return
        self.base_url_var.set(url)
        self.set_status(f"API profile applied: {profile}")

    def _inspect_port_8000_data(self):
        output = subprocess.check_output(["netstat", "-ano", "-p", "tcp"], text=True, stderr=subprocess.STDOUT)
        lines = output.splitlines()
        pids = set()
        for line in lines:
            if ":8000" in line and "LISTENING" in line.upper():
                m = re.search(r"(\d+)\s*$", line.strip())
                if m:
                    pids.add(int(m.group(1)))
        details = []
        for pid in sorted(pids):
            try:
                info = subprocess.check_output(["tasklist", "/FI", f"PID eq {pid}", "/V"], text=True, stderr=subprocess.STDOUT)
            except Exception as exc:
                info = f"tasklist failed for PID {pid}: {exc}"
            details.append({"pid": pid, "tasklist": info})
        return details

    def inspect_port_8000(self):
        try:
            details = self._inspect_port_8000_data()
            if not details:
                self.append_output("No LISTENING process on port 8000.")
                self.set_status("Port 8000 is free.")
                return
            self.append_output(json.dumps(details, indent=2, ensure_ascii=True))
            self.set_status(f"Port 8000 inspector: {len(details)} process(es) found.")
        except Exception as exc:
            self.set_status(f"Port inspector failed: {exc}")

    def kill_port_8000(self):
        try:
            details = self._inspect_port_8000_data()
            killed = []
            for item in details:
                pid = item["pid"]
                subprocess.run(["taskkill", "/PID", str(pid), "/F"], check=False, capture_output=True, text=True)
                killed.append(pid)
            self.append_output(json.dumps({"killed_pids": killed}, indent=2, ensure_ascii=True))
            self.set_status(f"Killed listeners on port 8000: {killed}")
        except Exception as exc:
            self.set_status(f"Kill port failed: {exc}")

    def export_logs(self):
        try:
            exports_dir = self.bundle_dir / "exports"
            exports_dir.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            out_file = exports_dir / f"debug_export_{ts}.json"

            try:
                active_query = self._get_json("/active_query", timeout=6)
            except Exception:
                active_query = {"error": "unavailable"}
            try:
                metrics = self._get_json("/metrics", timeout=6)
            except Exception:
                metrics = {"error": "unavailable"}

            payload = {
                "exported_at": ts,
                "base_url": self.base_url_var.get().strip(),
                "query": {
                    "route": self.route_var.get().strip(),
                    "station": self.station_var.get().strip(),
                    "direction": self.direction_var.get().strip().upper(),
                    "stop_ids": self.stop_ids_var.get().strip(),
                },
                "refresh": {
                    "success": self.refresh_success,
                    "fail": self.refresh_fail,
                    "last_update": self.last_update_var.get(),
                },
                "last_eta_payload": self.last_eta_payload,
                "active_query": active_query,
                "metrics": metrics,
                "alert_history": self.alert_history,
                "server_logs": self.server_logs,
            }
            out_file.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")
            self.set_status(f"Exported logs: {out_file.name}")
            self.append_output(f"Exported: {out_file}")
        except Exception as exc:
            self.set_status(f"Export failed: {exc}")

    def start_server(self):
        if self.server_process is not None and self.server_process.poll() is None:
            self.set_status("Server already running.")
            return

        host, port = self._parse_base_url()

        try:
            health_url = f"{self.base_url_var.get().rstrip('/')}/health"
            response = requests.get(health_url, timeout=1.5)
            if response.ok:
                self.set_status("Server already reachable at Base URL.")
                return
        except Exception:
            pass

        if self._is_port_in_use(port):
            self.set_status(
                f"Port {port} is in use but {host} is not responding to health checks. "
                "Possible conflicting process."
            )
            self.append_output(
                "Port conflict detected. Stop the existing process on port "
                f"{port} or adjust Base URL before starting server."
            )
            return

        if not self.server_script.exists():
            messagebox.showerror("Error", f"Server script not found: {self.server_script}")
            return

        self.server_logs = []
        cmd = [sys.executable, str(self.server_script)]
        self.server_process = subprocess.Popen(
            cmd,
            cwd=str(self.bundle_dir),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self._start_log_threads()
        self.set_status("Starting server...")

        time.sleep(1.0)
        exit_code = self.server_process.poll()
        if exit_code is not None:
            self.set_status(f"Server failed to start (exit {exit_code}).")
            self.render_server_logs(header=f"Server failed to start (exit {exit_code})")
            self.server_process = None
            return

        self.set_status("Server started.")
        self.after(1000, self._poll_server_process)

    def stop_server(self):
        if self.server_process is None or self.server_process.poll() is not None:
            self.set_status("Server is not running.")
            return

        self.server_process.terminate()
        try:
            self.server_process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self.server_process.kill()

        self.server_process = None
        self.set_status("Server stopped.")

    def check_health(self):
        url = f"{self.base_url_var.get().rstrip('/')}/health"
        try:
            response = requests.get(url, timeout=6)
            response.raise_for_status()
            payload = response.json()
            self.append_output(json.dumps(payload, indent=2, ensure_ascii=True))
            self.set_status("Health check OK.")
            self.refresh_metrics()
        except Exception as exc:
            self.set_status(f"Health check failed: {exc}")

    def refresh_metrics(self):
        try:
            m = self._get_json("/metrics", timeout=8)
            self.metrics_var.set(
                "metrics: requests={requests_total} errors={errors_total} last_success={last_success_ts} last_alert={last_alert_ts}".format(
                    **{
                        "requests_total": m.get("requests_total", 0),
                        "errors_total": m.get("errors_total", 0),
                        "last_success_ts": m.get("last_success_ts", "-"),
                        "last_alert_ts": m.get("last_alert_ts", "-"),
                    }
                )
            )
        except Exception:
            self.metrics_var.set("metrics: unavailable")

    def learn_lines(self):
        try:
            payload = self._get_json("/meta/routes", timeout=12)
            routes = payload.get("routes", [])
            self.all_routes = routes
            self._refresh_route_options(preferred=self.route_var.get().strip().upper())
            self.append_output(json.dumps(payload, indent=2, ensure_ascii=True))
            self.set_status(f"{payload.get('count', len(routes))} routes loaded.")
        except Exception as exc:
            self.set_status(f"Failed to load route list: {exc}")

    def load_stations(self):
        try:
            payload = self._get_json("/meta/stations", timeout=25)
            stations = payload.get("stations", [])
            self.station_catalog = stations
            self.station_index = {item["name"]: item for item in stations}
            self._refresh_station_options()
            self.append_output(json.dumps(payload, indent=2, ensure_ascii=True))
            self.set_status(f"{payload.get('count', len(stations))} stations loaded.")
        except Exception as exc:
            self.set_status(f"Failed to load station list: {exc}")

    def on_station_selected(self, _event=None):
        station_name = self.station_var.get().strip().upper()
        station = self.station_index.get(station_name)
        if not station:
            return

        station_routes = station.get("lines", [])
        if station_routes:
            self.route_combo["values"] = [""] + station_routes
            if self.route_var.get().strip().upper() not in station_routes:
                self.route_var.set("")

        self.stop_ids_var.set(",".join(station.get("stop_ids", [])))

    def show_catalog(self):
        if not self.all_routes:
            self.learn_lines()
        if not self.station_catalog:
            self.load_stations()

        summary = {
            "routes_count": len(self.all_routes),
            "routes": self.all_routes,
            "stations_count": len(self.station_catalog),
            "stations_preview": self.station_catalog[:30],
        }
        self.append_output(json.dumps(summary, indent=2, ensure_ascii=True))
        self.set_status("Route and station catalog displayed (preview).")

    def _record_alert_history(self, payload):
        entry = {
            "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "route": payload.get("route", ""),
            "station": payload.get("station", ""),
            "alert_flag": int(payload.get("alert_flag", 0)),
            "alert_msg": payload.get("alert_msg", ""),
        }
        self.alert_history.append(entry)
        self.alert_history = self.alert_history[-20:]
        self.refresh_alert_history_view()

    def refresh_alert_history_view(self):
        self.alert_text.delete("1.0", tk.END)
        show_alert_only = self.alert_only_var.get()
        rows = []
        for item in self.alert_history:
            if show_alert_only and int(item.get("alert_flag", 0)) != 1:
                continue
            rows.append(
                f"[{item.get('ts')}] {item.get('route')} @ {item.get('station')} | "
                f"alert={item.get('alert_flag')} | {item.get('alert_msg')}"
            )
        self.alert_text.insert(tk.END, "\n".join(rows) if rows else "(no alert history)")

    def fetch_eta(self, from_auto=False):
        url = f"{self.base_url_var.get().rstrip('/')}/eta"
        params = {
            "station": self.station_var.get().strip(),
            "direction": self.direction_var.get().strip().upper(),
        }

        route = self.route_var.get().strip()
        if route:
            params["route"] = route

        stop_ids = self.stop_ids_var.get().strip()
        if stop_ids:
            params["stop_ids"] = stop_ids

        try:
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            payload = response.json()
            self.last_eta_payload = payload
            self._record_alert_history(payload)
            if not from_auto:
                self.append_output(json.dumps(payload, indent=2, ensure_ascii=True))
            self.refresh_success += 1
            self.last_update_var.set(
                f"Last update: {datetime.now().strftime('%H:%M:%S')} | OK={self.refresh_success} FAIL={self.refresh_fail}"
            )
            self.set_status("ETA fetched successfully." if not from_auto else "Auto refresh OK")
            self.refresh_metrics()
            return payload
        except Exception as exc:
            self.refresh_fail += 1
            self.last_update_var.set(
                f"Last update: {datetime.now().strftime('%H:%M:%S')} | OK={self.refresh_success} FAIL={self.refresh_fail}"
            )
            self.set_status(f"ETA request failed: {exc}")
            return None

    def toggle_auto_refresh(self):
        if self.auto_refresh_var.get():
            self.set_status("Auto refresh enabled.")
            self._schedule_auto_refresh()
        else:
            if self.auto_refresh_job is not None:
                self.after_cancel(self.auto_refresh_job)
                self.auto_refresh_job = None
            self.set_status("Auto refresh disabled.")

    def _schedule_auto_refresh(self):
        if not self.auto_refresh_var.get():
            return
        try:
            seconds = int(self.refresh_interval_var.get().strip())
        except Exception:
            seconds = 10
        seconds = max(5, seconds)
        self.auto_refresh_job = self.after(seconds * 1000, self._auto_refresh_tick)

    def _auto_refresh_tick(self):
        self.fetch_eta(from_auto=True)
        self._schedule_auto_refresh()

    def send_to_arduino(self):
        active_params = {
            "route": self.route_var.get().strip(),
            "station": self.station_var.get().strip(),
            "direction": self.direction_var.get().strip().upper(),
        }

        stop_ids = self.stop_ids_var.get().strip()
        if stop_ids:
            active_params["stop_ids"] = stop_ids

        try:
            url = f"{self.base_url_var.get().rstrip('/')}/set_active_query"
            response = requests.post(url, params=active_params, timeout=10)
            response.raise_for_status()
            active_result = response.json()
        except Exception as exc:
            self.set_status(f"Failed to write localhost active profile: {exc}")
            return

        try:
            verified, verify_payload = self._verify_active_query(active_params)
        except Exception as exc:
            self.set_status(f"Active profile written but could not be verified: {exc}")
            self.append_output(json.dumps(active_result, indent=2, ensure_ascii=True))
            return

        if not verified:
            output = {
                "write_result": active_result,
                "verify_result": verify_payload,
                "warning": "active_query write/verify mismatch",
            }
            self.append_output(json.dumps(output, indent=2, ensure_ascii=True))
            self.set_status("Active profile written but verification inconsistent.")
            return

        serial_port = self.arduino_port_var.get().strip()
        if serial_port:
            payload = self.last_eta_payload or {}
            push_params = {
                "route": payload.get("route", active_params.get("route", "")),
                "eta1": payload.get("eta1", "--"),
                "eta2": payload.get("eta2", "--"),
                "alert_flag": payload.get("alert_flag", 0),
                "station": payload.get("station", active_params.get("station", "JAMAICA")),
                "alert_msg": payload.get("alert_msg", "No details available"),
                "serial_port": serial_port,
            }
            try:
                serial_result = self._get_json("/push_to_arduino", params=push_params, timeout=12)
                output = {
                    "active_query": active_result.get("active_query", {}),
                    "active_query_verify": verify_payload.get("active_query", {}),
                    "serial_push": serial_result,
                }
                self.append_output(json.dumps(output, indent=2, ensure_ascii=True))
                self.set_status(f"Active profile saved, serial push OK: {serial_result.get('port', '')}")
                return
            except Exception as exc:
                self.set_status(f"Active profile saved but serial push failed: {exc}")
                self.append_output(json.dumps(active_result, indent=2, ensure_ascii=True))
                return

        output = {
            "active_query": active_result.get("active_query", {}),
            "active_query_verify": verify_payload.get("active_query", {}),
        }
        self.append_output(json.dumps(output, indent=2, ensure_ascii=True))
        self.set_status("Active profile written to localhost. Arduino will receive this data on next /eta request.")

    def on_close(self):
        if self.auto_refresh_job is not None:
            self.after_cancel(self.auto_refresh_job)
            self.auto_refresh_job = None

        if self.server_process is not None and self.server_process.poll() is None:
            if messagebox.askyesno("Exit", "Server is running. Stop server and exit?"):
                self.stop_server()
                self.destroy()
            return
        self.destroy()


if __name__ == "__main__":
    app = EtaUiClient()
    app.after(300, app.learn_lines)
    app.after(700, app.load_stations)
    app.after(900, app.refresh_metrics)
    app.mainloop()
