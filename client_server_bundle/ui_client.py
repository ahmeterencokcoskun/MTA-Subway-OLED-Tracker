import json
import subprocess
import sys
import threading
import time
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk

import requests


class EtaUiClient(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("MTA ETA Client UI")
        self.geometry("900x620")

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

        self.status_var = tk.StringVar(value="Ready")
        self._build_ui()

        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def _build_ui(self):
        root = ttk.Frame(self, padding=12)
        root.pack(fill=tk.BOTH, expand=True)

        server_box = ttk.LabelFrame(root, text="Server", padding=10)
        server_box.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(server_box, text="Base URL").grid(row=0, column=0, sticky="w")
        ttk.Entry(server_box, textvariable=self.base_url_var, width=42).grid(row=0, column=1, sticky="we", padx=6)
        ttk.Button(server_box, text="Start Server", command=self.start_server).grid(row=0, column=2, padx=4)
        ttk.Button(server_box, text="Stop Server", command=self.stop_server).grid(row=0, column=3, padx=4)
        ttk.Button(server_box, text="Health", command=self.check_health).grid(row=0, column=4, padx=4)
        ttk.Button(server_box, text="Hatlari Ogren", command=self.learn_lines).grid(row=0, column=5, padx=4)
        ttk.Button(server_box, text="Duraklari Yukle", command=self.load_stations).grid(row=0, column=6, padx=4)
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

        ttk.Label(query_box, text="Serial Port (opsiyonel, seri gonderim)").grid(row=2, column=0, sticky="w", pady=(10, 0))
        ttk.Entry(query_box, textvariable=self.arduino_port_var, width=12).grid(row=2, column=1, sticky="w", padx=(6, 18), pady=(10, 0))

        ttk.Button(query_box, text="Sorgula (ETA)", command=self.fetch_eta).grid(row=3, column=0, columnspan=2, sticky="we", pady=(12, 0))
        ttk.Button(query_box, text="Arduinoya Gonder", command=self.send_to_arduino).grid(row=3, column=2, columnspan=2, sticky="we", pady=(12, 0), padx=(6, 6))
        ttk.Button(query_box, text="Hat+Durak Listesi", command=self.show_catalog).grid(row=3, column=4, columnspan=2, sticky="we", pady=(12, 0))

        output_box = ttk.LabelFrame(root, text="Response", padding=10)
        output_box.pack(fill=tk.BOTH, expand=True)

        self.output = tk.Text(output_box, wrap=tk.WORD, font=("Consolas", 10), height=20)
        self.output.pack(fill=tk.BOTH, expand=True)

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

    def start_server(self):
        if self.server_process is not None and self.server_process.poll() is None:
            self.set_status("Server already running.")
            return

        try:
            health_url = f"{self.base_url_var.get().rstrip('/')}/health"
            response = requests.get(health_url, timeout=1.5)
            if response.ok:
                self.set_status("Server already reachable at Base URL.")
                return
        except Exception:
            pass

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
        except Exception as exc:
            self.set_status(f"Health check failed: {exc}")

    def learn_lines(self):
        try:
            payload = self._get_json("/meta/routes", timeout=12)
            routes = payload.get("routes", [])
            self.all_routes = routes
            self._refresh_route_options(preferred=self.route_var.get().strip().upper())
            self.append_output(json.dumps(payload, indent=2, ensure_ascii=True))
            self.set_status(f"{payload.get('count', len(routes))} hat yuklendi.")
        except Exception as exc:
            self.set_status(f"Hat listesi alinamadi: {exc}")

    def load_stations(self):
        try:
            payload = self._get_json("/meta/stations", timeout=25)
            stations = payload.get("stations", [])
            self.station_catalog = stations
            self.station_index = {item["name"]: item for item in stations}
            self._refresh_station_options()
            self.append_output(json.dumps(payload, indent=2, ensure_ascii=True))
            self.set_status(f"{payload.get('count', len(stations))} durak yuklendi.")
        except Exception as exc:
            self.set_status(f"Durak listesi alinamadi: {exc}")

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

        # Keep query bound to the selected station by always refreshing its stop IDs.
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
        self.set_status("Hat ve durak katalogu gosterildi (onizleme).")

    def fetch_eta(self):
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
            self.append_output(json.dumps(payload, indent=2, ensure_ascii=True))
            self.set_status("ETA fetched successfully.")
        except Exception as exc:
            self.set_status(f"ETA request failed: {exc}")

    def send_to_arduino(self):
        # Primary flow: write current UI selection as active localhost query for WiFi Arduino polling.
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
            self.set_status(f"Localhost aktif profil yazilamadi: {exc}")
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
                output = {"active_query": active_result.get("active_query", {}), "serial_push": serial_result}
                self.append_output(json.dumps(output, indent=2, ensure_ascii=True))
                self.set_status(f"Aktif profil kaydedildi, seri gonderim OK: {serial_result.get('port', '')}")
                return
            except Exception as exc:
                self.set_status(f"Aktif profil kaydedildi ama seri gonderim hatali: {exc}")
                self.append_output(json.dumps(active_result, indent=2, ensure_ascii=True))
                return

        self.append_output(json.dumps(active_result, indent=2, ensure_ascii=True))
        self.set_status("Aktif profil localhost'a yazildi. Arduino bir sonraki /eta isteginde bu veriyi alacak.")

    def on_close(self):
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
    app.mainloop()
