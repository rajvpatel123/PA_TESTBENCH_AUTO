# main.py
"""
PA_TESTBENCH_AUTO - entry point.

On startup, auto-discovers all connected VISA instruments via *IDN? query
and wires the populated registry into all tabs. No manual address config needed.
"""

import tkinter as tk
from tkinter import ttk
import threading
import json
import os

import matplotlib
matplotlib.use("TkAgg")

from utils.logger import get_logger
from utils.visa_helper import discover_instruments

from tabs.device_info_tab import DeviceInfoTab
from tabs.power_supply_tab import PowerSupplyTab
from tabs.signal_generator_tab import SignalGeneratorTab
from tabs.spectrum_analyzer_tab import SpectrumAnalyzerTab
from tabs.sequencer_tab import SequencerTab
from tabs.dmm_tab import DMMTab
from tabs.ramp_editor_tab import RampEditorTab
from tabs.results_viewer_tab import ResultsViewerTab
from tabs.sweep_plan_tab import SweepPlanTab

_logger = get_logger(__name__)

PROFILES_FILE = "test_profiles.json"


def load_profiles() -> dict:
    if os.path.exists(PROFILES_FILE):
        try:
            with open(PROFILES_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_profiles(profiles: dict):
    try:
        with open(PROFILES_FILE, "w", encoding="utf-8") as f:
            json.dump(profiles, f, indent=2)
    except Exception as e:
        _logger.error(f"Failed to save profiles: {e}")


# ── Colour palette (kept identical to original) ───────────────
APP_COLORS = {
    "header":     "#1E3A5F",
    "bg":         "#F1F5F9",
    "card":       "#FFFFFF",
    "accent":     "#2563EB",
    "success":    "#16A34A",
    "warning":    "#D97706",
    "danger":     "#DC2626",
    "text":       "#1E293B",
    "text_muted": "#64748B",
    "border":     "#E2E8F0",
}


class PaTestBenchAutoApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("PA Testbench AUTO")
        self.root.geometry("1380x860")
        self.root.minsize(1180, 760)

        self.profiles        = load_profiles()
        self.driver_registry = {}

        self._build_shell()
        self._build_tabs()
        self._wire_tabs()
        self._set_status("Starting auto-discovery...", tone="info")

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # Run auto-discovery in background so the UI appears immediately
        threading.Thread(target=self._auto_discover, daemon=True).start()

    # ── Shell ──────────────────────────────────────────────────
    def _build_shell(self):
        self.shell = ttk.Frame(self.root)
        self.shell.pack(fill="both", expand=True)

        self.header = tk.Frame(
            self.shell, bg=APP_COLORS["header"], height=64,
            highlightthickness=0, bd=0)
        self.header.pack(fill="x")
        self.header.pack_propagate(False)

        left = tk.Frame(self.header, bg=APP_COLORS["header"])
        left.pack(side="left", fill="y", padx=16)
        tk.Label(left, text="PA Testbench AUTO",
                 bg=APP_COLORS["header"], fg="white",
                 font=("Segoe UI", 16, "bold")).pack(anchor="w", pady=(10, 0))
        tk.Label(left, text="Auto-discovery mode",
                 bg=APP_COLORS["header"], fg="#CBD5E1",
                 font=("Segoe UI", 9)).pack(anchor="w", pady=(2, 10))

        right = tk.Frame(self.header, bg=APP_COLORS["header"])
        right.pack(side="right", fill="y", padx=16)
        self.header_conn_var   = tk.StringVar(value="Connected: 0")
        self.header_status_var = tk.StringVar(value="Discovering...")
        tk.Label(right, textvariable=self.header_conn_var,
                 bg=APP_COLORS["header"], fg="white",
                 font=("Segoe UI", 10, "bold")).pack(anchor="e", pady=(12, 0))
        tk.Label(right, textvariable=self.header_status_var,
                 bg=APP_COLORS["header"], fg="#CBD5E1",
                 font=("Segoe UI", 9)).pack(anchor="e", pady=(2, 10))

        self.content  = ttk.Frame(self.shell)
        self.content.pack(fill="both", expand=True, padx=10, pady=10)
        self.notebook = ttk.Notebook(self.content)
        self.notebook.pack(fill="both", expand=True)

        self.footer = tk.Frame(self.shell, bg="#E5E7EB", height=28,
                               highlightthickness=0, bd=0)
        self.footer.pack(fill="x", side="bottom")
        self.footer.pack_propagate(False)
        self.footer_status_var = tk.StringVar(value="Starting...")
        self.footer_status_lbl = tk.Label(
            self.footer, textvariable=self.footer_status_var,
            bg="#E5E7EB", fg="#475569",
            font=("Segoe UI", 9), anchor="w")
        self.footer_status_lbl.pack(fill="x", padx=12, pady=4)

    # ── Tabs ───────────────────────────────────────────────────
    def _build_tabs(self):
        self.device_tab  = DeviceInfoTab(self.notebook)
        self.power_tab   = PowerSupplyTab(self.notebook, self.driver_registry)
        self.siggen_tab  = SignalGeneratorTab(self.notebook, self.driver_registry)
        self.specan_tab  = SpectrumAnalyzerTab(self.notebook, self.driver_registry)
        self.seq_tab     = SequencerTab(self.notebook, self.driver_registry, self.profiles, save_profiles)
        self.dmm_tab     = DMMTab(self.notebook, self.driver_registry)
        self.ramp_tab    = RampEditorTab(self.notebook)
        self.sweep_tab   = SweepPlanTab(self.notebook, self.driver_registry)
        self.results_tab = ResultsViewerTab(self.notebook)

        self.notebook.add(self.device_tab,  text=" Device Manager ")
        self.notebook.add(self.power_tab,   text=" Power Supplies ")
        self.notebook.add(self.siggen_tab,  text=" Signal Generator ")
        self.notebook.add(self.specan_tab,  text=" Spectrum Analyzer ")
        self.notebook.add(self.seq_tab,     text=" Sequencer ")
        self.notebook.add(self.dmm_tab,     text=" DMMs ")
        self.notebook.add(self.ramp_tab,    text=" Ramp Editor ")
        self.notebook.add(self.sweep_tab,   text=" Sweep Plan ")
        self.notebook.add(self.results_tab, text=" Results ")

    def _wire_tabs(self):
        self.sweep_tab.set_ramp_tab_ref(self.ramp_tab)
        self.sweep_tab.set_results_tab_ref(self.results_tab)
        self.seq_tab.set_tab_refs(self.power_tab, self.siggen_tab, self.specan_tab)
        self.seq_tab.set_ramp_editor(self.ramp_tab)
        self.seq_tab.set_dmm_tab_ref(self.dmm_tab)
        self.seq_tab.set_sweep_plan_tab_ref(self.sweep_tab)
        self.seq_tab.set_results_tab_ref(self.results_tab)
        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

    # ── Auto-discovery (runs in background thread) ─────────────
    def _auto_discover(self):
        """Scan VISA bus, build registry, then push to all tabs on the main thread."""
        try:
            registry = discover_instruments(timeout_ms=2000)
        except Exception as e:
            _logger.error(f"Auto-discovery failed: {e}")
            registry = {}
        # Schedule UI update back on main thread
        self.root.after(0, lambda: self._apply_registry(registry))

    def _apply_registry(self, registry: dict):
        """Called on main thread after discovery completes."""
        self.driver_registry.clear()
        self.driver_registry.update(registry)

        self.power_tab.set_driver_registry(self.driver_registry)
        self.siggen_tab.set_driver_registry(self.driver_registry)
        self.specan_tab.set_driver_registry(self.driver_registry)
        self.seq_tab.set_driver_registry(self.driver_registry)
        self.dmm_tab.set_driver_registry(self.driver_registry)
        self.sweep_tab.set_driver_registry(self.driver_registry)

        # Populate Device Manager tab with discovered instruments
        if hasattr(self.device_tab, "populate_discovered"):
            self.device_tab.populate_discovered(self.driver_registry)

        self.header_conn_var.set(f"Connected: {len(registry)}")
        tone = "success" if registry else "warning"
        msg  = (f"Auto-discovery complete: {len(registry)} instrument(s) found"
                if registry else "No instruments found — check VISA connections")
        self._set_status(msg, tone=tone)
        _logger.info(f"Registry applied: {list(registry.keys())}")

    # ── Helpers ────────────────────────────────────────────────
    def _set_status(self, text: str, tone: str = "muted"):
        self.footer_status_var.set(text)
        self.header_status_var.set(text)
        color_map = {
            "muted":   "#475569",
            "success": "#166534",
            "warning": "#92400E",
            "danger":  "#991B1B",
            "info":    "#0F766E",
        }
        self.footer_status_lbl.config(fg=color_map.get(tone, "#475569"))

    def _on_tab_changed(self, _event=None):
        try:
            current = self.notebook.tab(self.notebook.select(), "text").strip()
            self._set_status(f"Viewing: {current}", tone="muted")
        except Exception:
            pass

    def _on_close(self):
        for tab in (self.dmm_tab, self.power_tab, self.specan_tab):
            for method in ("stop_polling", "stop_live"):
                try:
                    getattr(tab, method)()
                except Exception:
                    pass
        # Close all driver connections cleanly
        for name, drv in self.driver_registry.items():
            try:
                drv.close()
                _logger.info(f"Closed driver: {name}")
            except Exception:
                pass
        self.root.destroy()


def main():
    root = tk.Tk()
    app  = PaTestBenchAutoApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
