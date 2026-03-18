# tabs/dmm_tab.py - COMPLETE FILE
import tkinter as tk
from tkinter import ttk, messagebox
import threading
import time
import datetime
from utils.logger import get_logger, session_logger

_logger = get_logger(__name__)

DMM_INSTRUMENTS = [
    {"name": "Keysight_34465A_1"},
    {"name": "Keysight_34465A_2"},
    {"name": "Keysight_34461A"},
]

POLL_INTERVAL_MS = 1000
STALE_AFTER_S    = 5.0   # readings older than this are flagged stale


class DMMTab(ttk.Frame):

    def __init__(self, parent, driver_registry: dict):
        super().__init__(parent)
        self._registry    = driver_registry
        self._polling     = False
        self._poll_thread = None
        self._rows        = {}
        self._build_ui()

    def set_driver_registry(self, registry: dict):
        self._registry = registry

    def _build_ui(self):
        ttk.Label(self, text="Digital Multimeters",
                  font=("Segoe UI", 14, "bold")).pack(pady=10)

        table_frame = ttk.LabelFrame(self, text="DMM Readback")
        table_frame.pack(fill="both", expand=True, padx=15, pady=5)

        cols = ("Instrument", "Mode", "Reading", "Unit", "Age (s)", "Status")
        self.tree = ttk.Treeview(table_frame, columns=cols,
                                  show="headings", height=6)
        col_widths = {
            "Instrument": 220, "Mode": 140,
            "Reading": 160,    "Unit": 80,
            "Age (s)": 80,     "Status": 120,
        }
        for col in cols:
            self.tree.heading(col, text=col)
            self.tree.column(col, width=col_widths[col], anchor="center")
        self.tree.pack(fill="both", expand=True, padx=5, pady=5)
        self.tree.bind("<Double-1>", self._on_row_double_click)

        ttk.Label(table_frame,
                  text="Double-click a row to change measurement mode  |  "
                       f"Readings older than {STALE_AFTER_S:.0f} s are flagged stale",
                  foreground="gray").pack(pady=2)

        ctrl_frame = ttk.Frame(self)
        ctrl_frame.pack(fill="x", padx=15, pady=5)

        ttk.Label(ctrl_frame, text="Poll Interval (ms):").pack(
            side="left", padx=(0, 5))
        self.interval_var = tk.StringVar(value=str(POLL_INTERVAL_MS))
        ttk.Entry(ctrl_frame, textvariable=self.interval_var,
                  width=8).pack(side="left", padx=5)

        ttk.Button(ctrl_frame, text="Read Once",
                   command=self._read_once).pack(side="left", padx=10)
        self.poll_btn = ttk.Button(ctrl_frame, text="Start Live Polling",
                                    command=self._toggle_polling)
        self.poll_btn.pack(side="left", padx=5)
        ttk.Button(ctrl_frame, text="Clear Readings",
                   command=self._clear_readings).pack(side="left", padx=5)

        log_frame = ttk.LabelFrame(self, text="Reading Log")
        log_frame.pack(fill="both", expand=True, padx=15, pady=5)

        self.log_text = tk.Text(log_frame, height=8, state="disabled",
                                 font=("Consolas", 9), wrap="word")
        scroll = ttk.Scrollbar(log_frame, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scroll.set)
        self.log_text.pack(side="left", fill="both", expand=True,
                           padx=5, pady=5)
        scroll.pack(side="right", fill="y")

        self.status_lbl = ttk.Label(self, text="Status: Idle",
                                     foreground="gray")
        self.status_lbl.pack(pady=5)

        self._populate_rows()

    def _populate_rows(self):
        self.tree.delete(*self.tree.get_children())
        self._rows.clear()
        for dmm in DMM_INSTRUMENTS:
            name = dmm["name"]
            self._rows[name] = {
                "mode":      "VOLT:DC",
                "reading":   None,      # float or None
                "timestamp": None,      # datetime or None
            }
            self.tree.insert("", "end", iid=name,
                             values=(name, "VOLT:DC", "---", "V", "---", "Idle"))

    # ── Mode dialog ────────────────────────────────────────────
    def _on_row_double_click(self, event):
        sel = self.tree.selection()
        if sel:
            self._open_mode_dialog(sel[0])

    def _open_mode_dialog(self, name: str):
        dialog = tk.Toplevel(self)
        dialog.title(f"Configure: {name}")
        dialog.grab_set()
        dialog.resizable(False, False)

        ttk.Label(dialog, text=f"Instrument: {name}",
                  font=("Segoe UI", 10, "bold")).grid(
                  row=0, column=0, columnspan=2, padx=15, pady=10)
        ttk.Label(dialog, text="Measurement Mode:").grid(
                  row=1, column=0, padx=10, sticky="e")

        mode_var = tk.StringVar(value=self._rows[name]["mode"])
        ttk.Combobox(
            dialog, textvariable=mode_var, state="readonly", width=18,
            values=["VOLT:DC", "VOLT:AC", "CURR:DC", "CURR:AC", "RES"]
        ).grid(row=1, column=1, padx=10, pady=8)

        def apply():
            new_mode = mode_var.get()
            self._rows[name]["mode"]      = new_mode
            self._rows[name]["reading"]   = None
            self._rows[name]["timestamp"] = None
            unit = self._mode_unit(new_mode)
            vals = self.tree.item(name, "values")
            self.tree.item(name, values=(
                vals[0], new_mode, "---", unit, "---", "Idle"))
            _logger.info(f"DMM {name} mode set to {new_mode}")
            dialog.destroy()

        ttk.Button(dialog, text="Apply", command=apply).grid(
                   row=2, column=0, columnspan=2, pady=10)

    def _mode_unit(self, mode: str) -> str:
        return {"VOLT:DC": "V", "VOLT:AC": "V",
                "CURR:DC": "A", "CURR:AC": "A",
                "RES": "Ω"}.get(mode, "")

    # ── Reading ────────────────────────────────────────────────
    def _read_once(self):
        for name in self._rows:
            self._read_dmm(name)
        self.status_lbl.config(
            text="Status: Read complete", foreground="green")

    def _read_dmm(self, name: str):
        drv = self._registry.get(name)
        if drv is None:
            vals = list(self.tree.item(name, "values"))
            vals[2] = "---"
            vals[4] = "---"
            vals[5] = "Not connected"
            self.tree.item(name, values=vals)
            return

        mode = self._rows[name]["mode"]
        try:
            drv._inst.write(f"CONF:{mode}")
            raw   = drv._inst.query("READ?").strip()
            value = float(raw)
            unit  = self._mode_unit(mode)
            now   = datetime.datetime.now()

            # Store reading + timestamp
            self._rows[name]["reading"]   = value
            self._rows[name]["timestamp"] = now

            display = f"{value:.6g}"
            self.tree.item(name, values=(
                name, mode, display, unit, "0.0", "OK"))
            self._log(f"{name} [{mode}] = {display} {unit}")
            session_logger.log(
                instrument=name,
                voltage=value if "VOLT" in mode else "-",
                current=value if "CURR" in mode else "-",
                notes=f"DMM {mode} reading"
            )
            _logger.info(f"DMM {name}: {display} {unit}")

        except Exception as e:
            self.tree.item(name, values=(
                name, mode, "ERROR",
                self._mode_unit(mode), "---", str(e)[:30]))
            _logger.error(f"DMM {name} read error: {e}")

    # ── Age ticker — updates Age column every second ───────────
    def _tick_ages(self):
        """Called every second to update the Age (s) column in the table."""
        now = datetime.datetime.now()
        for name, row in self._rows.items():
            ts = row.get("timestamp")
            if ts is None:
                continue
            age_s = (now - ts).total_seconds()
            vals  = list(self.tree.item(name, "values"))
            vals[4] = f"{age_s:.1f}"
            if age_s > STALE_AFTER_S:
                vals[5] = "STALE"
            self.tree.item(name, values=vals)
        self.after(1000, self._tick_ages)

    # ── Polling ────────────────────────────────────────────────
    def _toggle_polling(self):
        if self._polling:
            self._polling = False
            self.poll_btn.config(text="Start Live Polling")
            self.status_lbl.config(
                text="Status: Polling stopped", foreground="gray")
            _logger.info("DMM live polling stopped")
        else:
            try:
                interval_ms = int(self.interval_var.get())
            except ValueError:
                messagebox.showerror("Invalid Interval",
                                     "Poll interval must be an integer (ms).")
                return
            self._polling = True
            self.poll_btn.config(text="Stop Live Polling")
            self.status_lbl.config(
                text="Status: Polling...", foreground="orange")
            _logger.info(f"DMM live polling started at {interval_ms} ms")
            self._poll_thread = threading.Thread(
                target=self._poll_loop, args=(interval_ms,), daemon=True)
            self._poll_thread.start()
            self._tick_ages()   # start the age ticker

    def _poll_loop(self, interval_ms: int):
        while self._polling:
            for name in list(self._rows.keys()):
                if not self._polling:
                    break
                self.after(0, lambda n=name: self._read_dmm(n))
            time.sleep(interval_ms / 1000.0)

    def _clear_readings(self):
        for name in self._rows:
            mode = self._rows[name]["mode"]
            self._rows[name]["reading"]   = None
            self._rows[name]["timestamp"] = None
            self.tree.item(name, values=(
                name, mode, "---", self._mode_unit(mode), "---", "Idle"))
        self.log_text.config(state="normal")
        self.log_text.delete("1.0", tk.END)
        self.log_text.config(state="disabled")
        self.status_lbl.config(text="Status: Cleared", foreground="gray")

    def _log(self, message: str):
        ts   = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
        line = f"[{ts}] {message}\n"

        def _update():
            self.log_text.config(state="normal")
            self.log_text.insert(tk.END, line)
            self.log_text.see(tk.END)
            self.log_text.config(state="disabled")

        self.after(0, _update)

    # ── Sequencer API ──────────────────────────────────────────
    def get_latest_readings(self, max_age_s: float = STALE_AFTER_S) -> dict:
        """
        Return latest readings for sequencer PAE calculation.

        Each entry:
            {
                "mode":    str,
                "reading": str,        # display string from tree
                "unit":    str,
                "value":   float|None, # raw float, None if no reading yet
                "stale":   bool,       # True if older than max_age_s
            }

        The sequencer should check stale=True and skip PAE if so.
        """
        now      = datetime.datetime.now()
        result   = {}
        for name, row in self._rows.items():
            ts      = row.get("timestamp")
            value   = row.get("reading")
            vals    = self.tree.item(name, "values")
            stale   = True
            if ts is not None:
                age_s = (now - ts).total_seconds()
                stale = age_s > max_age_s
            result[name] = {
                "mode":    vals[1],
                "reading": vals[2],
                "unit":    vals[3],
                "value":   value,
                "stale":   stale,
            }
        return result

    def stop_polling(self):
        self._polling = False
