# tabs/spectrum_analyzer_tab.py - COMPLETE FILE
import tkinter as tk
from tkinter import ttk, messagebox
from utils.logger import get_logger
from utils.freq_entry import FreqEntry

_logger = get_logger(__name__)


class SpectrumAnalyzerTab(ttk.Frame):

    DRIVER_NAME = "PXA_N9030A"

    def __init__(self, parent, driver_registry: dict):
        super().__init__(parent)
        self._registry      = driver_registry
        self._live_polling  = False
        self._poll_interval = 2000
        self._last_trace    = []
        self._has_plot      = False
        self._build_ui()

    def set_driver_registry(self, registry: dict):
        self._registry = registry

    def _get_driver(self):
        drv = self._registry.get(self.DRIVER_NAME)
        if drv is None:
            messagebox.showerror("Not Connected",
                                 f"{self.DRIVER_NAME} not connected.\n"
                                 "Go to Device Manager and click Connect All.")
        return drv

    def _build_ui(self):
        ttk.Label(self, text="Spectrum Analyzer - Keysight PXA N9030A",
                  font=("Segoe UI", 14, "bold")).pack(pady=10)

        main = ttk.Frame(self)
        main.pack(fill="both", expand=True, padx=15, pady=5)

        # ── LEFT: Settings ─────────────────────────────────────
        left = ttk.LabelFrame(main, text="Analyzer Settings")
        left.pack(side="left", fill="both", expand=False, padx=(0, 10))

        settings_grid = ttk.Frame(left)
        settings_grid.pack(padx=10, pady=10)

        def add_label(row, text):
            ttk.Label(settings_grid, text=text,
                      width=20, anchor="e").grid(
                      row=row, column=0, padx=8, pady=6, sticky="e")

        def add_plain_row(row, label, var, unit=""):
            """For non-frequency fields (ref level, acq window)."""
            ttk.Label(settings_grid, text=label,
                      width=20, anchor="e").grid(
                      row=row, column=0, padx=8, pady=6, sticky="e")
            ttk.Entry(settings_grid, textvariable=var, width=12).grid(
                row=row, column=1, padx=5, pady=6, sticky="w")
            if unit:
                ttk.Label(settings_grid, text=unit).grid(
                    row=row, column=2, sticky="w")

        # FreqEntry rows
        add_label(0, "Center Frequency:")
        self.center_fe = FreqEntry(settings_grid, width=12, default_unit="MHz")
        self.center_fe.grid(row=0, column=1, columnspan=2, padx=5, pady=6, sticky="w")

        add_label(1, "Span:")
        self.span_fe = FreqEntry(settings_grid, width=12, default_unit="MHz")
        self.span_fe.grid(row=1, column=1, columnspan=2, padx=5, pady=6, sticky="w")

        add_label(2, "RBW:")
        self.rbw_fe = FreqEntry(settings_grid, width=12, default_unit="kHz")
        self.rbw_fe.grid(row=2, column=1, columnspan=2, padx=5, pady=6, sticky="w")

        add_label(3, "VBW:")
        self.vbw_fe = FreqEntry(settings_grid, width=12, default_unit="kHz")
        self.vbw_fe.grid(row=3, column=1, columnspan=2, padx=5, pady=6, sticky="w")

        # Plain entry rows
        self.ref_var = tk.StringVar(value="")
        self.acq_var = tk.StringVar(value="")
        add_plain_row(4, "Reference Level:", self.ref_var, "dBm")
        add_plain_row(5, "Acq. Window:",     self.acq_var, "sec")

        ttk.Button(left, text="Apply Settings",
                   command=self._apply_settings).pack(fill="x", padx=10, pady=6)

        ttk.Separator(left, orient="horizontal").pack(fill="x", padx=10, pady=5)

        # Trigger
        trig_frame = ttk.LabelFrame(left, text="Trigger")
        trig_frame.pack(fill="x", padx=10, pady=5)
        ttk.Button(trig_frame, text="Single Sweep",
                   command=self._single_sweep).pack(fill="x", padx=8, pady=5)
        ttk.Button(trig_frame, text="Continuous ON",
                   command=lambda: self._set_continuous(True)).pack(fill="x", padx=8, pady=3)
        ttk.Button(trig_frame, text="Continuous OFF",
                   command=lambda: self._set_continuous(False)).pack(fill="x", padx=8, pady=3)

        ttk.Separator(left, orient="horizontal").pack(fill="x", padx=10, pady=5)

        # Presets
        preset_frame = ttk.LabelFrame(left, text="Quick Presets")
        preset_frame.pack(fill="x", padx=10, pady=5)
        ttk.Button(preset_frame, text="1 GHz / 100 MHz span",
                   command=lambda: self._apply_preset(1e9, 100e6)).pack(
                   fill="x", padx=5, pady=3)
        ttk.Button(preset_frame, text="2.4 GHz / 200 MHz span",
                   command=lambda: self._apply_preset(2.4e9, 200e6)).pack(
                   fill="x", padx=5, pady=3)
        ttk.Button(preset_frame, text="5.8 GHz / 500 MHz span",
                   command=lambda: self._apply_preset(5.8e9, 500e6)).pack(
                   fill="x", padx=5, pady=3)

        # ── RIGHT: Trace plot ──────────────────────────────────
        right = ttk.LabelFrame(main, text="Trace")
        right.pack(side="right", fill="both", expand=True)

        try:
            import matplotlib
            #matplotlib.use("TkAgg")
            from matplotlib.figure import Figure
            from matplotlib.backends.backend_tkagg import (
                FigureCanvasTkAgg, NavigationToolbar2Tk)

            self._fig = Figure(figsize=(6, 4), dpi=96)
            self._ax  = self._fig.add_subplot(111)
            self._ax.set_title("Spectrum Trace")
            self._ax.set_xlabel("Frequency (MHz)")
            self._ax.set_ylabel("Amplitude (dBm)")
            self._ax.grid(True)

            canvas = FigureCanvasTkAgg(self._fig, master=right)
            canvas.get_tk_widget().pack(fill="both", expand=True, padx=5, pady=5)
            NavigationToolbar2Tk(canvas, right).update()
            self._plot_canvas = canvas
            self._has_plot    = True

        except ImportError:
            self._has_plot = False
            ttk.Label(right,
                      text="Install matplotlib for live plots.\n(pip install matplotlib)",
                      foreground="gray").pack(expand=True)

        # Plot controls
        plot_btn_frame = ttk.Frame(right)
        plot_btn_frame.pack(fill="x", padx=5, pady=4)

        ttk.Button(plot_btn_frame, text="Refresh Trace",
                   command=self._refresh_trace).pack(side="left", padx=5)

        ttk.Separator(plot_btn_frame, orient="vertical").pack(
            side="left", fill="y", padx=6, pady=2)

        ttk.Label(plot_btn_frame, text="Interval (ms):").pack(side="left", padx=(0, 2))
        self.poll_interval_var = tk.StringVar(value="2000")
        ttk.Entry(plot_btn_frame, textvariable=self.poll_interval_var,
                  width=6).pack(side="left", padx=2)
        self.live_btn = ttk.Button(plot_btn_frame, text="▶  Live Update",
                                    command=self._toggle_live)
        self.live_btn.pack(side="left", padx=5)

        ttk.Separator(plot_btn_frame, orient="vertical").pack(
            side="left", fill="y", padx=6, pady=2)

        ttk.Button(plot_btn_frame, text="Save Trace CSV",
                   command=self._save_trace).pack(side="left", padx=5)
        ttk.Button(plot_btn_frame, text="Clear Plot",
                   command=self._clear_plot).pack(side="left", padx=5)

        self.status_lbl = ttk.Label(self, text="Status: Idle", foreground="gray")
        self.status_lbl.pack(pady=5)

    # ── Settings ───────────────────────────────────────────────
    def _apply_settings(self):
        drv = self._get_driver()
        if drv is None:
            return

        center_hz = self.center_fe.get_hz()
        span_hz   = self.span_fe.get_hz()
        rbw_hz    = self.rbw_fe.get_hz()
        vbw_hz    = self.vbw_fe.get_hz()

        try:
            ref_raw = self.ref_var.get().strip()
            ref_val = float(ref_raw) if ref_raw else None
        except ValueError:
            messagebox.showerror("Invalid Input", "Reference Level must be a number.")
            return

        try:
            if center_hz is not None: drv.set_center(center_hz)
            if span_hz   is not None: drv.set_span(span_hz)
            if rbw_hz    is not None: drv.set_rbw(rbw_hz)
            if vbw_hz    is not None: drv.set_vbw(vbw_hz)
            if ref_val   is not None: drv.set_ref_level(ref_val)
            self.status_lbl.config(text="Status: Settings applied", foreground="green")
            _logger.info(f"SpecAn settings applied: center={center_hz} span={span_hz} "
                         f"rbw={rbw_hz} vbw={vbw_hz} ref={ref_val}")
        except Exception as e:
            messagebox.showerror("Hardware Error", str(e))
            _logger.error(f"SpecAn apply settings failed: {e}")

    def _apply_preset(self, center: float, span: float):
        self.center_fe.set_hz(center)
        self.span_fe.set_hz(span)
        self._apply_settings()

    # ── Trigger ────────────────────────────────────────────────
    def _single_sweep(self):
        drv = self._get_driver()
        if drv is None:
            return
        try:
            acq_str  = self.acq_var.get().strip()
            acq_time = float(acq_str) if acq_str else None
            if hasattr(drv, "single_sweep"):
                drv.single_sweep(acq_time)
            else:
                drv._inst.write("INIT:IMM")
            self.status_lbl.config(text="Status: Sweep triggered", foreground="green")
            _logger.info(f"SpecAn single sweep triggered, acq_time={acq_time}")
            self._refresh_trace()
        except Exception as e:
            messagebox.showerror("Hardware Error", str(e))
            _logger.error(f"SpecAn single sweep failed: {e}")

    def _set_continuous(self, enable: bool):
        drv = self._get_driver()
        if drv is None:
            return
        try:
            drv._inst.write("INIT:CONT ON" if enable else "INIT:CONT OFF")
            state = "ON" if enable else "OFF"
            self.status_lbl.config(
                text=f"Status: Continuous {state}", foreground="green")
            _logger.info(f"SpecAn continuous sweep {state}")
        except Exception as e:
            messagebox.showerror("Hardware Error", str(e))
            _logger.error(f"SpecAn continuous sweep failed: {e}")

    # ── Live polling ───────────────────────────────────────────
    def _toggle_live(self):
        if self._live_polling:
            self._live_polling = False
            self.live_btn.config(text="▶  Live Update")
            self.status_lbl.config(
                text="Status: Live update stopped", foreground="gray")
            _logger.info("SpecAn live polling stopped")
        else:
            try:
                self._poll_interval = int(self.poll_interval_var.get())
            except ValueError:
                self._poll_interval = 2000
            self._live_polling = True
            self.live_btn.config(text="■  Stop Live")
            self.status_lbl.config(
                text="Status: Live updating...", foreground="orange")
            _logger.info(f"SpecAn live polling started at {self._poll_interval} ms")
            self._live_poll_tick()

    def _live_poll_tick(self):
        if not self._live_polling:
            return
        self._refresh_trace()
        self.after(self._poll_interval, self._live_poll_tick)

    def stop_live(self):
        self._live_polling = False

    # ── Trace ──────────────────────────────────────────────────
    def _refresh_trace(self):
        drv = self._registry.get(self.DRIVER_NAME)
        if drv is None:
            if not self._live_polling:
                messagebox.showerror("Not Connected",
                                     f"{self.DRIVER_NAME} not connected.\n"
                                     "Go to Device Manager and click Connect All.")
            return
        try:
            trace = drv.acquire_trace()
            self._last_trace = trace
            if self._has_plot and trace:
                self._ax.clear()
                self._ax.set_title("Spectrum Trace")
                self._ax.set_ylabel("Amplitude (dBm)")
                self._ax.grid(True)

                if isinstance(trace[0], (list, tuple)):
                    freqs_raw = [p[0] for p in trace]
                    amps      = [p[1] for p in trace]
                else:
                    freqs_raw = list(range(len(trace)))
                    amps      = trace

                # Auto-scale freq axis to best unit for display
                max_hz = max(freqs_raw) if freqs_raw else 1
                if max_hz >= 1e9:
                    freqs_disp = [f / 1e9 for f in freqs_raw]
                    self._ax.set_xlabel("Frequency (GHz)")
                elif max_hz >= 1e6:
                    freqs_disp = [f / 1e6 for f in freqs_raw]
                    self._ax.set_xlabel("Frequency (MHz)")
                elif max_hz >= 1e3:
                    freqs_disp = [f / 1e3 for f in freqs_raw]
                    self._ax.set_xlabel("Frequency (kHz)")
                else:
                    freqs_disp = freqs_raw
                    self._ax.set_xlabel("Frequency (Hz)")

                self._ax.plot(freqs_disp, amps, color="cyan", linewidth=1)
                self._plot_canvas.draw()

            self.status_lbl.config(
                text=f"Status: Trace captured ({len(trace)} points)",
                foreground="green")
            _logger.info(f"SpecAn trace captured: {len(trace)} points")
        except Exception as e:
            if not self._live_polling:
                messagebox.showerror("Error", str(e))
            _logger.error(f"SpecAn trace capture failed: {e}")

    def _clear_plot(self):
        if self._has_plot:
            self._ax.clear()
            self._ax.set_title("Spectrum Trace")
            self._ax.set_xlabel("Frequency (MHz)")
            self._ax.set_ylabel("Amplitude (dBm)")
            self._ax.grid(True)
            self._plot_canvas.draw()
        self._last_trace = []
        self.status_lbl.config(text="Status: Plot cleared", foreground="gray")

    def _save_trace(self):
        if not self._last_trace:
            messagebox.showwarning("No Data", "No trace data. Run a sweep first.")
            return
        from tkinter import filedialog
        import csv
        filepath = filedialog.asksaveasfilename(
            title="Save Trace",
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")]
        )
        if not filepath:
            return
        try:
            with open(filepath, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["Frequency (Hz)", "Amplitude (dBm)"])
                for point in self._last_trace:
                    writer.writerow(
                        point if isinstance(point, (list, tuple)) else ["-", point])
            self.status_lbl.config(
                text=f"Status: Saved to {filepath}", foreground="green")
            _logger.info(f"SpecAn trace saved to {filepath}")
        except Exception as e:
            messagebox.showerror("Save Error", str(e))
            _logger.error(f"SpecAn trace save failed: {e}")

    # ── get_settings / load_settings (sequencer + profiles) ───
    def get_settings(self) -> dict:
        return {
            "center_hz":    self.center_fe.get_hz(),
            "span_hz":      self.span_fe.get_hz(),
            "rbw_hz":       self.rbw_fe.get_hz(),
            "vbw_hz":       self.vbw_fe.get_hz(),
            "ref_dbm":      self.ref_var.get(),
            "acq_window_s": self.acq_var.get(),
        }

    def load_settings(self, settings: dict):
        if settings.get("center_hz"): self.center_fe.set_hz(float(settings["center_hz"]))
        if settings.get("span_hz"):   self.span_fe.set_hz(float(settings["span_hz"]))
        if settings.get("rbw_hz"):    self.rbw_fe.set_hz(float(settings["rbw_hz"]))
        if settings.get("vbw_hz"):    self.vbw_fe.set_hz(float(settings["vbw_hz"]))
        self.ref_var.set(settings.get("ref_dbm",      ""))
        self.acq_var.set(settings.get("acq_window_s", ""))
