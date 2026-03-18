import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import csv
import os
import glob
import shutil
from datetime import datetime

try:
    import matplotlib
    matplotlib.use("TkAgg")
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
    HAS_MPL = True
except ImportError:
    HAS_MPL = False

from utils.logger import get_logger
_logger = get_logger(__name__)

RESULTS_DIR  = "results"
CHART_COLORS = ["#2196F3", "#F44336", "#4CAF50", "#FF9800",
                "#9C27B0", "#00BCD4", "#795548", "#607D8B"]

CHART_DEFS = [
    ("Pout vs Pin",  "pin_dbm", "pout_dbm",  "Pin (dBm)",  "Pout (dBm)"),
    ("Gain vs Pin",  "pin_dbm", "gain_db",   "Pin (dBm)",  "Gain (dB)"),
    ("PAE vs Pout",  "pout_dbm","pae_pct",   "Pout (dBm)", "PAE (%)"),
    ("DE vs Pout",   "pout_dbm","de_pct",    "Pout (dBm)", "DE (%)"),
    ("PAE vs Pin",   "pin_dbm", "pae_pct",   "Pin (dBm)",  "PAE (%)"),
    ("Idd vs Pout",  "pout_dbm","idd_a",     "Pout (dBm)", "Idd (A)"),
]


class ResultsViewerTab(ttk.Frame):

    def __init__(self, parent):
        super().__init__(parent)
        self._rows        = []
        self._filtered    = []
        self._current_file = None
        self._group_var   = None
        self._build_ui()
        self._scan_results_dir()

    # ══════════════════════════════════════════════════════════
    #  UI BUILD
    # ══════════════════════════════════════════════════════════
    def _build_ui(self):
        # ── Toolbar ───────────────────────────────────────────
        toolbar = ttk.Frame(self)
        toolbar.pack(fill="x", padx=6, pady=(6, 2))

        ttk.Button(toolbar, text="📂 Open CSV",
                   command=self._open_csv).pack(side="left", padx=(0, 3))
        ttk.Button(toolbar, text="💾 Export Filtered",
                   command=self._export_filtered).pack(side="left", padx=3)
        ttk.Button(toolbar, text="🔄 Refresh",
                   command=self._scan_results_dir).pack(side="left", padx=3)

        ttk.Separator(toolbar, orient="vertical").pack(side="left", fill="y", padx=8)

        ttk.Label(toolbar, text="Filter command:").pack(side="left", padx=(0, 4))
        self._cmd_filter_var = tk.StringVar(value="ALL")
        self._cmd_filter_cb  = ttk.Combobox(toolbar, textvariable=self._cmd_filter_var,
                                             values=["ALL"], width=18, state="readonly")
        self._cmd_filter_cb.pack(side="left", padx=3)
        self._cmd_filter_cb.bind("<<ComboboxSelected>>", lambda e: self._apply_filter())

        ttk.Separator(toolbar, orient="vertical").pack(side="left", fill="y", padx=8)

        ttk.Label(toolbar, text="Group by:").pack(side="left", padx=(0, 4))
        self._group_var = tk.StringVar(value="freq_ghz")
        self._group_cb  = ttk.Combobox(toolbar, textvariable=self._group_var,
                                        values=["freq_ghz", "vdd_v", "idq_ma", "none"],
                                        width=12, state="readonly")
        self._group_cb.pack(side="left", padx=3)
        self._group_cb.bind("<<ComboboxSelected>>", lambda e: self._draw_charts())

        self._file_lbl = ttk.Label(toolbar, text="No file loaded",
                                   foreground="gray", font=("Segoe UI", 8))
        self._file_lbl.pack(side="right", padx=8)

        ttk.Separator(self, orient="horizontal").pack(fill="x", padx=6)

        # ── Body: session list | table + charts ───────────────
        body = ttk.Frame(self)
        body.pack(fill="both", expand=True, padx=6, pady=4)

        # Left: session history
        left = ttk.Frame(body, width=200)
        left.pack(side="left", fill="y", padx=(0, 4))
        left.pack_propagate(False)
        self._build_session_list(left)

        ttk.Separator(body, orient="vertical").pack(side="left", fill="y", padx=2)

        # Right: notebook with Table + Charts tabs
        right = ttk.Frame(body)
        right.pack(side="left", fill="both", expand=True)

        self._nb = ttk.Notebook(right)
        self._nb.pack(fill="both", expand=True)

        self._table_frame = ttk.Frame(self._nb)
        self._chart_frame = ttk.Frame(self._nb)
        self._nb.add(self._table_frame, text="  Table  ")
        self._nb.add(self._chart_frame, text="  Charts  ")

        self._build_table(self._table_frame)
        self._build_charts(self._chart_frame)

        # ── Status bar ────────────────────────────────────────
        self._status_var = tk.StringVar(value="No data loaded")
        ttk.Label(self, textvariable=self._status_var,
                  foreground="gray", font=("Segoe UI", 8)).pack(
                  anchor="w", padx=8, pady=(0, 4))

    # ── Session history list ───────────────────────────────────
    def _build_session_list(self, parent):
        ttk.Label(parent, text="Sessions",
                  font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=6, pady=(6, 2))

        frame = ttk.Frame(parent)
        frame.pack(fill="both", expand=True)

        self._session_lb = tk.Listbox(frame, font=("Segoe UI", 8),
                                       activestyle="dotbox", selectmode="single")
        vsb = ttk.Scrollbar(frame, orient="vertical", command=self._session_lb.yview)
        self._session_lb.configure(yscrollcommand=vsb.set)
        self._session_lb.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        self._session_lb.bind("<<ListboxSelect>>", self._on_session_select)

    # ── Table ─────────────────────────────────────────────────
    def _build_table(self, parent):
        frame = ttk.Frame(parent)
        frame.pack(fill="both", expand=True)

        self._tree = ttk.Treeview(frame, show="headings", height=20)
        xsb = ttk.Scrollbar(frame, orient="horizontal", command=self._tree.xview)
        ysb = ttk.Scrollbar(frame, orient="vertical",   command=self._tree.yview)
        self._tree.configure(xscrollcommand=xsb.set, yscrollcommand=ysb.set)

        self._tree.grid(row=0, column=0, sticky="nsew")
        ysb.grid(row=0, column=1, sticky="ns")
        xsb.grid(row=1, column=0, sticky="ew")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)

        self._row_count_lbl = ttk.Label(parent, text="",
                                         foreground="gray", font=("Segoe UI", 8))
        self._row_count_lbl.pack(anchor="w", padx=6, pady=2)

    # ── Charts ────────────────────────────────────────────────
    def _build_charts(self, parent):
        if not HAS_MPL:
            ttk.Label(parent, text="matplotlib not installed.\npip install matplotlib",
                      foreground="gray", font=("Segoe UI", 10),
                      justify="center").pack(expand=True, pady=40)
            return

        # Chart selector row
        sel_frame = ttk.Frame(parent)
        sel_frame.pack(fill="x", padx=6, pady=(4, 2))
        ttk.Label(sel_frame, text="Chart:").pack(side="left", padx=(0, 4))
        self._chart_sel_var = tk.StringVar(value=CHART_DEFS[0][0])
        for title, *_ in CHART_DEFS:
            ttk.Radiobutton(sel_frame, text=title,
                            variable=self._chart_sel_var, value=title,
                            command=self._draw_charts).pack(side="left", padx=4)

        # Canvas
        self._fig, self._ax = plt.subplots(figsize=(8, 4.5), dpi=96)
        self._fig.patch.set_facecolor("#1e1e1e")
        self._ax.set_facecolor("#2a2a2a")
        self._canvas = FigureCanvasTkAgg(self._fig, master=parent)
        self._canvas.get_tk_widget().pack(fill="both", expand=True, padx=4, pady=4)

        toolbar_frame = ttk.Frame(parent)
        toolbar_frame.pack(fill="x", padx=4)
        NavigationToolbar2Tk(self._canvas, toolbar_frame)

    # ══════════════════════════════════════════════════════════
    #  DATA LOADING
    # ══════════════════════════════════════════════════════════
    def _scan_results_dir(self):
        self._session_lb.delete(0, "end")
        if not os.path.isdir(RESULTS_DIR):
            return
        files = sorted(
            glob.glob(os.path.join(RESULTS_DIR, "*.csv")),
            key=os.path.getmtime, reverse=True)
        for fp in files:
            self._session_lb.insert("end", os.path.basename(fp))
        self._session_files = files

    def _on_session_select(self, event):
        sel = self._session_lb.curselection()
        if not sel:
            return
        idx = sel[0]
        if idx < len(self._session_files):
            self._load_csv(self._session_files[idx])

    def _open_csv(self):
        path = filedialog.askopenfilename(
            title="Open Results CSV",
            filetypes=[("CSV", "*.csv"), ("All Files", "*.*")])
        if path:
            self._load_csv(path)

    def _load_csv(self, path: str):
        try:
            with open(path, "r", newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                self._rows = [row for row in reader]
            self._current_file = path
            self._file_lbl.config(
                text=os.path.basename(path), foreground="gray")
            self._update_cmd_filter()
            self._apply_filter()
            _logger.info(f"Results loaded: {path}  ({len(self._rows)} rows)")
        except Exception as e:
            messagebox.showerror("Load Error", str(e))

    def refresh(self):
        """Called by sweep_plan_tab when a run completes."""
        self._scan_results_dir()
        # Auto-load the most recent file
        if os.path.isdir(RESULTS_DIR):
            files = sorted(
                glob.glob(os.path.join(RESULTS_DIR, "*.csv")),
                key=os.path.getmtime, reverse=True)
            if files:
                self._load_csv(files[0])
                self._session_lb.selection_clear(0, "end")
                self._session_lb.selection_set(0)

    # ══════════════════════════════════════════════════════════
    #  FILTER + TABLE
    # ══════════════════════════════════════════════════════════
    def _update_cmd_filter(self):
        cmds = sorted({r.get("command", "") for r in self._rows if r.get("command", "")})
        self._cmd_filter_cb.configure(values=["ALL"] + cmds)
        self._cmd_filter_var.set("ALL")

        # Also update group-by options based on available columns
        if self._rows:
            cols = list(self._rows[0].keys())
            group_opts = ["none"] + [c for c in cols
                                      if c not in ("command", "timestamp", "text")]
            self._group_cb.configure(values=group_opts)

    def _apply_filter(self):
        cmd = self._cmd_filter_var.get()
        self._filtered = [r for r in self._rows
                          if cmd == "ALL" or r.get("command", "") == cmd]
        self._populate_table()
        self._draw_charts()
        self._status_var.set(
            f"{len(self._filtered)} rows shown  "
            f"(total {len(self._rows)})  —  "
            f"{os.path.basename(self._current_file) if self._current_file else ''}")

    def _populate_table(self):
        self._tree.delete(*self._tree.get_children())
        if not self._filtered:
            self._row_count_lbl.config(text="0 rows")
            return

        cols = list(self._filtered[0].keys())
        self._tree.configure(columns=cols)
        for col in cols:
            self._tree.heading(col, text=col,
                               command=lambda c=col: self._sort_table(c))
            self._tree.column(col, width=max(80, len(col) * 10), anchor="w")

        for row in self._filtered:
            self._tree.insert("", "end", values=[row.get(c, "") for c in cols])

        self._row_count_lbl.config(text=f"{len(self._filtered)} rows")

    def _sort_table(self, col: str):
        data = [(self._tree.set(iid, col), iid)
                for iid in self._tree.get_children("")]
        try:
            data.sort(key=lambda x: float(x[0]) if x[0] else -999)
        except ValueError:
            data.sort(key=lambda x: x[0])
        for i, (_, iid) in enumerate(data):
            self._tree.move(iid, "", i)

    # ══════════════════════════════════════════════════════════
    #  CHARTS
    # ══════════════════════════════════════════════════════════
    def _draw_charts(self):
        if not HAS_MPL:
            return
        if not self._filtered:
            self._ax.clear()
            self._ax.set_facecolor("#2a2a2a")
            self._ax.text(0.5, 0.5, "No data", color="gray",
                          ha="center", va="center", transform=self._ax.transAxes,
                          fontsize=13)
            self._canvas.draw()
            return

        # Find selected chart def
        sel   = self._chart_sel_var.get() if hasattr(self, "_chart_sel_var") else CHART_DEFS[0][0]
        chart = next((c for c in CHART_DEFS if c[0] == sel), CHART_DEFS[0])
        _, x_col, y_col, x_label, y_label = chart

        group_col = self._group_var.get() if self._group_var else "none"

        # Only use POWER_SWEEP rows for charts
        plot_rows = [r for r in self._filtered
                     if r.get("command", "") == "POWER_SWEEP"]

        if not plot_rows:
            # Try all filtered rows
            plot_rows = self._filtered

        self._ax.clear()
        self._ax.set_facecolor("#2a2a2a")
        self._fig.patch.set_facecolor("#1e1e1e")

        if group_col == "none" or group_col not in (plot_rows[0].keys() if plot_rows else []):
            # Single series
            x_vals, y_vals = self._extract_xy(plot_rows, x_col, y_col)
            if x_vals:
                self._ax.plot(x_vals, y_vals, color=CHART_COLORS[0],
                              linewidth=2, marker="o", markersize=4, label="Series 1")
        else:
            # Group by column
            groups = {}
            for row in plot_rows:
                key = row.get(group_col, "")
                groups.setdefault(key, []).append(row)

            for ci, (key, group_rows) in enumerate(sorted(groups.items())):
                x_vals, y_vals = self._extract_xy(group_rows, x_col, y_col)
                if x_vals:
                    color = CHART_COLORS[ci % len(CHART_COLORS)]
                    label = f"{group_col}={key}"
                    self._ax.plot(x_vals, y_vals, color=color,
                                  linewidth=2, marker="o", markersize=4, label=label)

        # Styling
        self._ax.set_xlabel(x_label, color="white", fontsize=10)
        self._ax.set_ylabel(y_label, color="white", fontsize=10)
        self._ax.set_title(sel, color="white", fontsize=11, pad=10)
        self._ax.tick_params(colors="white")
        self._ax.spines[:].set_color("#555555")
        self._ax.grid(True, color="#444444", linestyle="--", linewidth=0.5)
        self._ax.legend(fontsize=8, facecolor="#2a2a2a",
                        edgecolor="#555555", labelcolor="white")

        self._fig.tight_layout()
        self._canvas.draw()

    @staticmethod
    def _extract_xy(rows, x_col, y_col):
        x_vals, y_vals = [], []
        for row in rows:
            try:
                x = float(row[x_col])
                y = float(row[y_col])
                x_vals.append(x)
                y_vals.append(y)
            except (ValueError, KeyError):
                pass
        paired = sorted(zip(x_vals, y_vals), key=lambda p: p[0])
        return ([p[0] for p in paired],
                [p[1] for p in paired])

    # ══════════════════════════════════════════════════════════
    #  EXPORT
    # ══════════════════════════════════════════════════════════
    def _export_filtered(self):
        if not self._filtered:
            messagebox.showwarning("No Data", "Nothing to export.")
            return
        path = filedialog.asksaveasfilename(
            title="Export Filtered Results",
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv")])
        if not path:
            return
        try:
            keys = list(self._filtered[0].keys())
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=keys)
                writer.writeheader()
                writer.writerows(self._filtered)
            self._status_var.set(f"Exported {len(self._filtered)} rows to {os.path.basename(path)}")
        except Exception as e:
            messagebox.showerror("Export Error", str(e))
