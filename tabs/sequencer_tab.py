# tabs/sequencer_tab.py
import tkinter as tk
from tkinter import ttk, messagebox
import threading
import time
import datetime
from utils.logger import get_logger, session_logger

_logger = get_logger(__name__)

IDQ_STEP_SETTLE_S = 0.15
IDQ_MAX_STEPS     = 200
MAX_GATE_V_GAN    = 0.0

ACTIONS = [
    "Set Values",
    "Output ON",
    "Output OFF",
    "Wait (s)",
    "Idq Target",
    "Read Meas",
]

ACTION_PARAMS = {
    "Set Values":  [],
    "Output ON":   [],
    "Output OFF":  [],
    "Wait (s)":    [("Seconds", "0.5")],
    "Idq Target":  [("Target (mA)", ""), ("Tol (mA)", "5"),
                    ("Step (mV)", "50"), ("Max (mA)", "")],
    "Read Meas":   [],
}

# colours
COL_SELECTED  = "#cce5ff"   # light blue  — selected channel row
COL_HAS_STEPS = "#d4edda"   # light green — row with steps
COL_DEFAULT   = "#f8f8f8"   # alternating row bg
COL_ALT       = "#ffffff"


class SequencerTab(ttk.Frame):

    def __init__(self, parent, driver_registry: dict,
                 test_profiles: dict, profile_save_callback):
        super().__init__(parent)
        self._registry       = driver_registry
        self._profiles       = test_profiles or {}
        self._save_callback  = profile_save_callback
        self._power_tab_ref  = None
        self._siggen_tab_ref = None
        self._specan_tab_ref = None
        self._dmm_tab_ref    = None
        self._ramp_editor    = None
        self._results_tab    = None
        self._sweep_plan_tab = None
        self._running        = False

        self._channel_steps: dict = {}   # ch_id -> [{action, params}]
        self._roster: list        = []   # ordered list of ch_ids
        self._ch_info: dict       = {}   # ch_id -> info dict from power tab
        self._selected_ch: str    = ""
        self._check_vars: dict    = {}   # ch_id -> tk.BooleanVar
        self._row_frames: dict    = {}   # ch_id -> tk.Frame (roster row)

        self._build_ui()

    # ── Public API ─────────────────────────────────────────────
    def set_driver_registry(self, registry: dict):
        self._registry = registry

    def set_tab_refs(self, power_tab, siggen_tab, specan_tab):
        self._power_tab_ref  = power_tab
        self._siggen_tab_ref = siggen_tab
        self._specan_tab_ref = specan_tab

    def set_dmm_tab_ref(self, dmm_tab):
        self._dmm_tab_ref = dmm_tab

    def set_ramp_editor(self, ramp_editor):
        self._ramp_editor = ramp_editor

    def set_results_tab_ref(self, results_tab):
        self._results_tab = results_tab

    def set_sweep_plan_tab_ref(self, sweep_plan_tab):
        self._sweep_plan_tab = sweep_plan_tab

    # ── UI Build ───────────────────────────────────────────────
    def _build_ui(self):
        ttk.Label(self, text="Sequencer",
                  font=("Segoe UI", 14, "bold")).pack(pady=(8, 4))

        body = ttk.Frame(self)
        body.pack(fill="both", expand=True, padx=8, pady=4)
        body.columnconfigure(0, weight=1, minsize=260)
        body.columnconfigure(1, weight=2, minsize=360)
        body.columnconfigure(2, weight=2, minsize=320)
        body.rowconfigure(0, weight=1)

        self._build_left(body)
        self._build_middle(body)
        self._build_right(body)

        self.status_lbl = ttk.Label(self, text="Status: Idle",
                                     foreground="gray")
        self.status_lbl.pack(pady=(2, 6))

    # ══════════════════════════════════════════════════════════
    # LEFT PANEL — Channel Roster (real checkbutton rows)
    # ══════════════════════════════════════════════════════════
    def _build_left(self, parent):
        outer = ttk.LabelFrame(parent, text="Channel Roster")
        outer.grid(row=0, column=0, sticky="nsew", padx=(0, 4), pady=2)
        outer.rowconfigure(1, weight=1)
        outer.columnconfigure(0, weight=1)

        # ── toolbar ──────────────────────────────────────────
        tb = ttk.Frame(outer)
        tb.grid(row=0, column=0, sticky="ew", padx=4, pady=(4, 2))
        ttk.Button(tb, text="↺  Refresh",
                   command=self._refresh_roster).pack(side="left", padx=(0, 4))
        ttk.Button(tb, text="↑", width=3,
                   command=lambda: self._move_roster(-1)).pack(side="left", padx=1)
        ttk.Button(tb, text="↓", width=3,
                   command=lambda: self._move_roster(1)).pack(side="left", padx=1)

        # ── scrollable canvas for rows ────────────────────────
        canvas_frame = ttk.Frame(outer)
        canvas_frame.grid(row=1, column=0, sticky="nsew", padx=2, pady=2)
        canvas_frame.rowconfigure(0, weight=1)
        canvas_frame.columnconfigure(0, weight=1)

        self._roster_canvas = tk.Canvas(canvas_frame, highlightthickness=0,
                                         bg="#f0f0f0")
        vsb = ttk.Scrollbar(canvas_frame, orient="vertical",
                             command=self._roster_canvas.yview)
        self._roster_canvas.configure(yscrollcommand=vsb.set)
        self._roster_canvas.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")

        self._roster_inner = tk.Frame(self._roster_canvas, bg="#f0f0f0")
        self._roster_window = self._roster_canvas.create_window(
            (0, 0), window=self._roster_inner, anchor="nw")
        self._roster_inner.bind("<Configure>", self._on_roster_inner_configure)
        self._roster_canvas.bind("<Configure>", self._on_roster_canvas_configure)

        # column headers
        hdr = tk.Frame(self._roster_inner, bg="#d0d0d0")
        hdr.pack(fill="x", pady=(0, 1))
        tk.Label(hdr, text="Run",     width=4,  bg="#d0d0d0",
                 font=("Segoe UI", 8, "bold"), anchor="c").pack(side="left")
        tk.Label(hdr, text="Channel", width=18, bg="#d0d0d0",
                 font=("Segoe UI", 8, "bold"), anchor="w").pack(side="left")
        tk.Label(hdr, text="Role",    width=6,  bg="#d0d0d0",
                 font=("Segoe UI", 8, "bold"), anchor="c").pack(side="left")
        tk.Label(hdr, text="Mode",    width=5,  bg="#d0d0d0",
                 font=("Segoe UI", 8, "bold"), anchor="c").pack(side="left")
        tk.Label(hdr, text="Steps",   width=5,  bg="#d0d0d0",
                 font=("Segoe UI", 8, "bold"), anchor="c").pack(side="left")

        # ── bottom: check all / uncheck all ───────────────────
        bot = ttk.Frame(outer)
        bot.grid(row=2, column=0, sticky="ew", padx=4, pady=(2, 4))
        ttk.Button(bot, text="Check All",
                   command=lambda: self._check_all(True)).pack(
                   side="left", padx=(0, 4))
        ttk.Button(bot, text="Uncheck All",
                   command=lambda: self._check_all(False)).pack(side="left")

    def _on_roster_inner_configure(self, event=None):
        self._roster_canvas.configure(
            scrollregion=self._roster_canvas.bbox("all"))

    def _on_roster_canvas_configure(self, event=None):
        self._roster_canvas.itemconfig(
            self._roster_window, width=event.width)

    # ── build / rebuild roster rows ───────────────────────────
    def _refresh_roster(self):
        if self._power_tab_ref is None:
            messagebox.showwarning("Not linked",
                                   "Power supply tab not linked.")
            return
        channels = self._power_tab_ref.get_active_channels()
        new_ids  = [ch["ch_id"] for ch in channels]
        for ch_id in new_ids:
            if ch_id not in self._channel_steps:
                self._channel_steps[ch_id] = []
        existing = [c for c in self._roster if c in new_ids]
        added    = [c for c in new_ids if c not in existing]
        self._roster  = existing + added
        self._ch_info = {ch["ch_id"]: ch for ch in channels}
        self._rebuild_roster_rows()
        self._log(f"Roster refreshed — {len(self._roster)} channel(s)")

    def _rebuild_roster_rows(self):
        # Destroy existing rows
        for ch_id, fr in self._row_frames.items():
            fr.destroy()
        self._row_frames.clear()
        # Preserve existing BooleanVars so checked state survives refresh
        for ch_id in list(self._check_vars.keys()):
            if ch_id not in self._roster:
                del self._check_vars[ch_id]

        for i, ch_id in enumerate(self._roster):
            info    = self._ch_info.get(ch_id, {})
            label   = info.get("label", ch_id)
            role    = info.get("role",  "")
            mode    = info.get("mode",  "")
            n_steps = len(self._channel_steps.get(ch_id, []))

            bg = COL_HAS_STEPS if n_steps else \
                 (COL_DEFAULT if i % 2 == 0 else COL_ALT)

            row_fr = tk.Frame(self._roster_inner, bg=bg,
                              relief="flat", bd=1, cursor="hand2")
            row_fr.pack(fill="x", pady=1)
            self._row_frames[ch_id] = row_fr

            # Real Checkbutton
            if ch_id not in self._check_vars:
                self._check_vars[ch_id] = tk.BooleanVar(value=True)
            cb = tk.Checkbutton(row_fr,
                                variable=self._check_vars[ch_id],
                                bg=bg, activebackground=bg,
                                relief="flat", bd=0)
            cb.pack(side="left", padx=(4, 0))

            # Channel label
            lbl_text = label if len(label) <= 22 else label[:20] + "…"
            ch_lbl = tk.Label(row_fr, text=lbl_text, width=18, anchor="w",
                              bg=bg, font=("Segoe UI", 9))
            ch_lbl.pack(side="left", padx=(2, 0))

            # Role
            tk.Label(row_fr, text=role, width=6, anchor="center",
                     bg=bg, font=("Segoe UI", 8),
                     foreground="#555").pack(side="left")

            # Mode
            tk.Label(row_fr, text=mode, width=5, anchor="center",
                     bg=bg, font=("Segoe UI", 8),
                     foreground="#555").pack(side="left")

            # Step count badge
            badge_bg  = "#1a7a1a" if n_steps else "#aaa"
            badge_txt = str(n_steps) if n_steps else "-"
            tk.Label(row_fr, text=badge_txt, width=4, anchor="center",
                     bg=badge_bg, fg="white",
                     font=("Segoe UI", 8, "bold"),
                     relief="flat").pack(side="left", padx=(4, 4))

            # Bind entire row + children to select on click
            for widget in (row_fr, ch_lbl):
                widget.bind("<Button-1>",
                            lambda e, cid=ch_id: self._select_channel(cid))

        # Re-apply selection highlight
        if self._selected_ch:
            self._highlight_selected(self._selected_ch)

    def _select_channel(self, ch_id: str):
        prev = self._selected_ch
        self._selected_ch = ch_id

        # Reset previous row colour
        if prev and prev in self._row_frames:
            i       = self._roster.index(prev) if prev in self._roster else 0
            n_steps = len(self._channel_steps.get(prev, []))
            old_bg  = COL_HAS_STEPS if n_steps else \
                      (COL_DEFAULT if i % 2 == 0 else COL_ALT)
            self._set_row_bg(prev, old_bg)

        self._highlight_selected(ch_id)

        # Update step builder header
        info  = self._ch_info.get(ch_id, {})
        label = info.get("label", ch_id)
        role  = info.get("role", "")
        n     = len(self._channel_steps.get(ch_id, []))
        self.step_header_var.set(
            f"▶  Editing:  {label}   [{role}]   —  {n} step{'s' if n != 1 else ''}")
        self._repopulate_step_tree(ch_id)

    def _highlight_selected(self, ch_id: str):
        if ch_id in self._row_frames:
            self._set_row_bg(ch_id, COL_SELECTED)

    def _set_row_bg(self, ch_id: str, color: str):
        fr = self._row_frames.get(ch_id)
        if fr is None:
            return
        fr.config(bg=color)
        for child in fr.winfo_children():
            try:
                child.config(bg=color, activebackground=color)
            except tk.TclError:
                pass

    def _move_roster(self, direction: int):
        if not self._selected_ch or self._selected_ch not in self._roster:
            return
        idx  = self._roster.index(self._selected_ch)
        new_ = idx + direction
        if 0 <= new_ < len(self._roster):
            self._roster.insert(new_, self._roster.pop(idx))
            self._rebuild_roster_rows()

    def _check_all(self, state: bool):
        for var in self._check_vars.values():
            var.set(state)

    def _get_checked_roster(self) -> list:
        return [ch for ch in self._roster
                if self._check_vars.get(ch, tk.BooleanVar()).get()]

    # ══════════════════════════════════════════════════════════
    # MIDDLE PANEL — Step Builder
    # ══════════════════════════════════════════════════════════
    def _build_middle(self, parent):
        mf = ttk.LabelFrame(parent, text="Step Builder")
        mf.grid(row=0, column=1, sticky="nsew", padx=4, pady=2)
        mf.rowconfigure(1, weight=1)
        mf.columnconfigure(0, weight=1)

        # ── Bold header showing which channel is being edited ─
        self.step_header_var = tk.StringVar(
            value="▶  Select a channel from the roster")
        hdr_lbl = tk.Label(mf, textvariable=self.step_header_var,
                           font=("Segoe UI", 10, "bold"),
                           fg="#1a3a6a", bg="#dce8f8",
                           anchor="w", padx=8, pady=5,
                           relief="groove", bd=1)
        hdr_lbl.grid(row=0, column=0, columnspan=2,
                     sticky="ew", padx=4, pady=(6, 4))

        # ── Step list treeview ────────────────────────────────
        step_cols = ("#", "Action", "Params")
        self.step_tree = ttk.Treeview(mf, columns=step_cols,
                                       show="headings", height=13)
        for col, w in {"#": 30, "Action": 110, "Params": 210}.items():
            self.step_tree.heading(col, text=col)
            self.step_tree.column(
                col, width=w,
                anchor="w" if col == "Params" else "center")
        vsb2 = ttk.Scrollbar(mf, orient="vertical",
                              command=self.step_tree.yview)
        self.step_tree.configure(yscrollcommand=vsb2.set)
        self.step_tree.grid(row=1, column=0, sticky="nsew",
                             padx=(4, 0), pady=2)
        vsb2.grid(row=1, column=1, sticky="ns", pady=2)

        # ── Add-step controls ─────────────────────────────────
        add_frame = ttk.LabelFrame(mf, text="Add Step")
        add_frame.grid(row=2, column=0, columnspan=2,
                       sticky="ew", padx=4, pady=(2, 4))
        add_frame.columnconfigure(1, weight=1)

        ttk.Label(add_frame, text="Action:").grid(
            row=0, column=0, padx=6, pady=4, sticky="e")
        self.action_var = tk.StringVar(value=ACTIONS[0])
        self.action_cb  = ttk.Combobox(
            add_frame, textvariable=self.action_var,
            values=ACTIONS, state="readonly", width=14)
        self.action_cb.grid(row=0, column=1, padx=4, pady=4, sticky="w")
        self.action_cb.bind("<<ComboboxSelected>>", self._on_action_changed)

        self.param_frame = ttk.Frame(add_frame)
        self.param_frame.grid(row=1, column=0, columnspan=2,
                               sticky="ew", padx=6, pady=2)
        self._param_vars: list = []
        self._render_param_fields()

        btn_row = ttk.Frame(add_frame)
        btn_row.grid(row=2, column=0, columnspan=2, pady=(2, 6))
        ttk.Button(btn_row, text="+ Add Step",
                   command=self._add_step).pack(side="left", padx=4)
        ttk.Button(btn_row, text="Remove",
                   command=self._remove_step).pack(side="left", padx=4)
        ttk.Button(btn_row, text="↑", width=3,
                   command=lambda: self._move_step(-1)).pack(side="left", padx=2)
        ttk.Button(btn_row, text="↓", width=3,
                   command=lambda: self._move_step(1)).pack(side="left", padx=2)
        ttk.Button(btn_row, text="Clear All",
                   command=self._clear_steps).pack(side="left", padx=4)

    # ══════════════════════════════════════════════════════════
    # RIGHT PANEL — Run Control
    # ══════════════════════════════════════════════════════════
    def _build_right(self, parent):
        rf = ttk.LabelFrame(parent, text="Run Control")
        rf.grid(row=0, column=2, sticky="nsew", padx=(4, 0), pady=2)
        rf.columnconfigure(0, weight=1)

        # Run mode
        mode_lf = ttk.LabelFrame(rf, text="Run Mode")
        mode_lf.pack(fill="x", padx=6, pady=(6, 4))
        self.run_mode_var = tk.StringVar(value="sequence")
        ttk.Radiobutton(mode_lf,
                        text="Run in Sequence  (top → bottom)",
                        variable=self.run_mode_var,
                        value="sequence").pack(anchor="w", padx=10, pady=3)
        ttk.Radiobutton(mode_lf,
                        text="Run Simultaneously  (all at once)",
                        variable=self.run_mode_var,
                        value="simultaneous").pack(anchor="w", padx=10, pady=3)

        # Settling
        settle_lf = ttk.LabelFrame(rf, text="Settling Delays")
        settle_lf.pack(fill="x", padx=6, pady=4)

        def settle_row(p, lbl, default, hint):
            r = ttk.Frame(p)
            r.pack(fill="x", padx=8, pady=3)
            ttk.Label(r, text=lbl, width=16, anchor="e").pack(side="left")
            v = tk.StringVar(value=default)
            ttk.Entry(r, textvariable=v, width=7).pack(side="left", padx=4)
            ttk.Label(r, text=hint, foreground="gray").pack(side="left")
            return v

        self.bias_settle_var = settle_row(
            settle_lf, "Bias Settle (s):", "0.5", "after Idq → before RF")
        self.rf_settle_var   = settle_row(
            settle_lf, "RF Settle (s):",   "0.05", "RF ON → before acq")

        # Pre-flight
        pf_lf = ttk.LabelFrame(rf, text="Pre-flight")
        pf_lf.pack(fill="x", padx=6, pady=4)
        self.check_vars = {}
        for key, lbl in [
            ("devices",  "Instruments connected"),
            ("channels", "Checked channels with steps"),
            ("siggen",   "Signal generator configured"),
            ("specan",   "Spectrum analyzer configured"),
        ]:
            var = tk.StringVar(value="⬜  " + lbl)
            self.check_vars[key] = var
            ttk.Label(pf_lf, textvariable=var,
                      font=("Segoe UI", 9)).pack(anchor="w", padx=8, pady=2)
        ttk.Button(pf_lf, text="Run Pre-flight Check",
                   command=self._run_preflight).pack(
                   fill="x", padx=8, pady=(2, 6))

        # RUN / ABORT
        self.run_btn = tk.Button(
            rf, text="▶  RUN",
            font=("Segoe UI", 14, "bold"),
            bg="#1a7a1a", fg="white",
            activebackground="#145a14", activeforeground="white",
            height=2, command=self._run_test,
        )
        self.run_btn.pack(fill="x", padx=6, pady=(6, 2))

        self.abort_btn = tk.Button(
            rf, text="■  ABORT",
            font=("Segoe UI", 11, "bold"),
            bg="#8b0000", fg="white",
            activebackground="#5a0000", activeforeground="white",
            command=self._abort_test, state="disabled",
        )
        self.abort_btn.pack(fill="x", padx=6, pady=(0, 4))

        ttk.Separator(rf, orient="horizontal").pack(fill="x", padx=6, pady=4)

        ttk.Label(rf, text="Test Log:",
                  font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=6)
        log_frame = ttk.Frame(rf)
        log_frame.pack(fill="both", expand=True, padx=6, pady=(2, 6))
        self.log_text = tk.Text(
            log_frame, height=12, state="disabled",
            font=("Consolas", 8), wrap="word")
        log_sb = ttk.Scrollbar(log_frame, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_sb.set)
        self.log_text.pack(side="left", fill="both", expand=True)
        log_sb.pack(side="right", fill="y")

    # ══════════════════════════════════════════════════════════
    # Step Builder helpers
    # ══════════════════════════════════════════════════════════
    def _on_action_changed(self, event=None):
        self._render_param_fields()

    def _render_param_fields(self):
        for w in self.param_frame.winfo_children():
            w.destroy()
        self._param_vars = []
        action = self.action_var.get()
        for i, (lbl, default) in enumerate(ACTION_PARAMS.get(action, [])):
            ttk.Label(self.param_frame, text=lbl + ":",
                      width=12, anchor="e").grid(
                      row=0, column=i * 2, padx=2, pady=2, sticky="e")
            var = tk.StringVar(value=default)
            ttk.Entry(self.param_frame, textvariable=var,
                      width=8).grid(row=0, column=i * 2 + 1,
                                    padx=2, pady=2, sticky="w")
            self._param_vars.append((lbl, var))

    def _add_step(self):
        if not self._selected_ch:
            messagebox.showwarning(
                "No Channel", "Click a channel in the roster first.")
            return
        action = self.action_var.get()
        params = {lbl: var.get().strip() for lbl, var in self._param_vars}
        self._channel_steps[self._selected_ch].append(
            {"action": action, "params": params})
        self._repopulate_step_tree(self._selected_ch)
        self._refresh_row_badge(self._selected_ch)
        self._update_step_header()

    def _remove_step(self):
        sel = self.step_tree.selection()
        if not sel or not self._selected_ch:
            return
        idx   = int(sel[0])
        steps = self._channel_steps.get(self._selected_ch, [])
        if 0 <= idx < len(steps):
            steps.pop(idx)
        self._repopulate_step_tree(self._selected_ch)
        self._refresh_row_badge(self._selected_ch)
        self._update_step_header()

    def _move_step(self, direction: int):
        sel = self.step_tree.selection()
        if not sel or not self._selected_ch:
            return
        idx   = int(sel[0])
        steps = self._channel_steps.get(self._selected_ch, [])
        new_  = idx + direction
        if 0 <= new_ < len(steps):
            steps.insert(new_, steps.pop(idx))
            self._repopulate_step_tree(self._selected_ch)
            self.step_tree.selection_set(str(new_))

    def _clear_steps(self):
        if not self._selected_ch:
            return
        if messagebox.askyesno(
                "Clear Steps",
                f"Clear all steps for {self._selected_ch}?"):
            self._channel_steps[self._selected_ch] = []
            self._repopulate_step_tree(self._selected_ch)
            self._refresh_row_badge(self._selected_ch)
            self._update_step_header()

    def _repopulate_step_tree(self, ch_id: str):
        self.step_tree.delete(*self.step_tree.get_children())
        for i, step in enumerate(self._channel_steps.get(ch_id, [])):
            param_str = "  ".join(
                f"{k}={v}" for k, v in step["params"].items() if v)
            self.step_tree.insert("", "end", iid=str(i),
                                   values=(i + 1, step["action"], param_str))

    def _refresh_row_badge(self, ch_id: str):
        """Update the step-count badge and row colour for a single channel."""
        fr = self._row_frames.get(ch_id)
        if fr is None:
            return
        n_steps   = len(self._channel_steps.get(ch_id, []))
        # find the badge label (last child with width=4)
        children  = fr.winfo_children()
        # badge is the last Label we packed
        badge_lbl = None
        for w in reversed(children):
            if isinstance(w, tk.Label) and w.cget("width") == 4:
                badge_lbl = w
                break
        if badge_lbl:
            badge_lbl.config(
                text=str(n_steps) if n_steps else "-",
                bg="#1a7a1a" if n_steps else "#aaa")
        # Update row bg (skip if currently selected)
        if ch_id != self._selected_ch:
            i  = self._roster.index(ch_id) if ch_id in self._roster else 0
            bg = COL_HAS_STEPS if n_steps else \
                 (COL_DEFAULT if i % 2 == 0 else COL_ALT)
            self._set_row_bg(ch_id, bg)

    def _update_step_header(self):
        if not self._selected_ch:
            return
        info  = self._ch_info.get(self._selected_ch, {})
        label = info.get("label", self._selected_ch)
        role  = info.get("role", "")
        n     = len(self._channel_steps.get(self._selected_ch, []))
        self.step_header_var.set(
            f"▶  Editing:  {label}   [{role}]   —  "
            f"{n} step{'s' if n != 1 else ''}")

    # ══════════════════════════════════════════════════════════
    # Pre-flight
    # ══════════════════════════════════════════════════════════
    def _run_preflight(self) -> bool:
        ok = True

        if self._registry:
            self.check_vars["devices"].set("✅  Instruments connected")
        else:
            self.check_vars["devices"].set("❌  No instruments connected")
            ok = False

        checked   = self._get_checked_roster()
        has_steps = [c for c in checked if self._channel_steps.get(c)]
        if has_steps:
            self.check_vars["channels"].set(
                f"✅  {len(has_steps)} channel(s) checked with steps")
        else:
            self.check_vars["channels"].set(
                "❌  No checked channels have steps")
            ok = False

        if self._siggen_tab_ref:
            s = self._siggen_tab_ref.get_settings()
            if s.get("freq_hz") and s.get("power_dbm"):
                self.check_vars["siggen"].set("✅  Signal generator configured")
            else:
                self.check_vars["siggen"].set(
                    "⚠️  SigGen: missing freq or power")
        else:
            self.check_vars["siggen"].set("⬜  SigGen tab not linked")

        if self._specan_tab_ref:
            s = self._specan_tab_ref.get_settings()
            if s.get("center_hz") and s.get("span_hz"):
                self.check_vars["specan"].set("✅  Spectrum analyzer configured")
            else:
                self.check_vars["specan"].set(
                    "⚠️  SpecAn: missing center or span")
        else:
            self.check_vars["specan"].set("⬜  SpecAn tab not linked")

        return ok

    # ══════════════════════════════════════════════════════════
    # Run / Abort
    # ══════════════════════════════════════════════════════════
    def _run_test(self):
        if self._running:
            return
        if not self._run_preflight():
            messagebox.showerror(
                "Pre-flight Failed",
                "Fix the issues shown in Pre-flight before running.")
            return
        self._running = True
        self.run_btn.config(state="disabled")
        self.abort_btn.config(state="normal")
        self.status_lbl.config(text="Status: Running...", foreground="orange")
        mode = self.run_mode_var.get()
        threading.Thread(
            target=self._execute_simultaneous
                   if mode == "simultaneous"
                   else self._execute_sequence,
            daemon=True,
        ).start()

    def _abort_test(self):
        self._running = False
        self._log("■ ABORT requested by user")
        self.after(0, lambda: self.status_lbl.config(
            text="Status: Aborted", foreground="red"))

    def _finish_run(self, success: bool):
        self._running = False
        self.after(0, lambda: self.run_btn.config(state="normal"))
        self.after(0, lambda: self.abort_btn.config(state="disabled"))
        msg = "Status: Complete ✓" if success \
              else "Status: Finished with errors — check log"
        col = "green" if success else "red"
        self.after(0, lambda: self.status_lbl.config(text=msg,
                                                      foreground=col))

    # ── Sequence mode ──────────────────────────────────────────
    def _execute_sequence(self):
        checked = self._get_checked_roster()
        self._log(f"=== SEQUENCE RUN — {len(checked)} channel(s) ===")
        success = True
        try:
            session_logger.start(metadata={"run_mode": "sequence"})
            for ch_id in checked:
                if not self._running:
                    break
                self._log(f"--- Channel: {ch_id} ---")
                if not self._run_channel_steps(ch_id):
                    success = False
            self._log("=== SEQUENCE RUN COMPLETE ===")
            session_logger.stop()
        except Exception as e:
            self._log(f"ERROR: {e}")
            _logger.error(f"Sequence run error: {e}", exc_info=True)
            success = False
            try: session_logger.stop()
            except Exception: pass
        finally:
            self._finish_run(success)

    # ── Simultaneous mode ──────────────────────────────────────
    def _execute_simultaneous(self):
        checked = self._get_checked_roster()
        self._log(f"=== SIMULTANEOUS RUN — {len(checked)} channel(s) ===")
        results, threads = {}, []
        try:
            session_logger.start(metadata={"run_mode": "simultaneous"})
            for ch_id in checked:
                def _worker(cid=ch_id):
                    results[cid] = self._run_channel_steps(cid)
                t = threading.Thread(target=_worker, daemon=True)
                threads.append(t)
                t.start()
            for t in threads:
                t.join()
            success = all(results.values())
            self._log("=== SIMULTANEOUS RUN COMPLETE ===")
            session_logger.stop()
        except Exception as e:
            self._log(f"ERROR: {e}")
            _logger.error(f"Simultaneous run error: {e}", exc_info=True)
            success = False
            try: session_logger.stop()
            except Exception: pass
        finally:
            self._finish_run(success)

    # ── Per-channel step executor ──────────────────────────────
    def _run_channel_steps(self, ch_id: str) -> bool:
        steps = self._channel_steps.get(ch_id, [])
        info  = self._ch_info.get(ch_id, {})
        if not steps:
            self._log(f"  {ch_id}: no steps — skipping")
            return True
        drv  = self._registry.get(info.get("supply", ""))
        ch   = info.get("channel", 1)
        mode = info.get("mode", "CV")
        for i, step in enumerate(steps):
            if not self._running:
                return True
            action, params = step["action"], step["params"]
            self._log(f"  [{ch_id}] Step {i+1}: {action}  {params}")
            self.after(0, lambda c=ch_id, a=action, n=i+1:
                       self.status_lbl.config(
                           text=f"Status: {c}  Step {n}: {a}",
                           foreground="orange"))
            try:
                if not self._exec_step(drv, ch, mode, info, action, params):
                    return False
            except Exception as e:
                self._log(f"  ERROR [{ch_id}] step {i+1} ({action}): {e}")
                _logger.error(f"{ch_id} step {i+1} error: {e}",
                              exc_info=True)
                return False
        return True

    def _exec_step(self, drv, ch: int, mode: str,
                   info: dict, action: str, params: dict) -> bool:
        if drv is None and action not in ("Wait (s)", "Read Meas"):
            self._log(f"    ⚠  Driver not connected — skipping {action}")
            return True

        if action == "Set Values":
            if mode == "CV":
                v = info.get("volt_var", "")
                if v: drv.set_voltage(ch, float(v))
                ocp = info.get("ocp_var", "")
                if ocp: drv.set_ocp(ch, float(ocp))
                self._log(f"    Set CV: {v} V  OCP={ocp} A")
            else:
                a = info.get("curr_var", "")
                if a: drv.set_current(ch, float(a))
                ovp = info.get("ovp_var", "")
                if ovp: drv.set_ovp(ch, float(ovp))
                self._log(f"    Set CC: {a} A  OVP={ovp} V")

        elif action == "Output ON":
            drv.output_on(ch, True)
            self._log("    Output ON")

        elif action == "Output OFF":
            drv.output_on(ch, False)
            self._log("    Output OFF")

        elif action == "Wait (s)":
            secs = float(params.get("Seconds") or 0.5)
            self._log(f"    Waiting {secs} s...")
            deadline = time.time() + secs
            while time.time() < deadline:
                if not self._running:
                    return True
                time.sleep(0.05)

        elif action == "Idq Target":
            return self._exec_idq_target(drv, ch, params)

        elif action == "Read Meas":
            try:
                v = drv.measure_voltage(ch)
                a = drv.measure_current(ch)
                self._log(f"    Meas: {v:.4f} V  {a*1000:.2f} mA")
                session_logger.log(
                    instrument=info.get("supply", ""), channel=ch,
                    meas_v=round(v, 5), meas_a=round(a, 6),
                    notes="Read Meas step")
            except Exception as e:
                self._log(f"    Read Meas error: {e}")
        return True

    def _exec_idq_target(self, drv, ch: int, params: dict) -> bool:
        try:
            target_ma    = float(params.get("Target (mA)") or 0)
            tolerance_ma = float(params.get("Tol (mA)")    or 5.0)
            step_mv      = float(params.get("Step (mV)")   or 50.0)
            max_raw      = params.get("Max (mA)", "")
            max_idq_ma   = float(max_raw) if max_raw else target_ma * 3.0
        except (ValueError, TypeError):
            self._log("    Idq Target: invalid params — skipping")
            return True
        if target_ma <= 0:
            self._log("    Idq Target: no target set — skipping")
            return True
        target_a    = target_ma    / 1000.0
        tolerance_a = tolerance_ma / 1000.0
        max_idq_a   = max_idq_ma   / 1000.0
        step_v      = step_mv      / 1000.0
        self._log(f"    Idq walk: target={target_ma} mA ±{tolerance_ma} mA "
                  f"step={step_mv} mV abort>{max_idq_ma} mA")
        try:
            gate_v = drv.measure_voltage(ch)
        except Exception:
            gate_v = 0.0
        for i in range(IDQ_MAX_STEPS):
            if not self._running:
                return True
            try:
                idq_a  = drv.measure_current(ch)
                idq_ma = idq_a * 1000.0
            except Exception as e:
                self._log(f"    Idq read error: {e}")
                return False
            self._log(f"    [{i+1:03d}] Gate={gate_v:.4f}V  Idq={idq_ma:.2f} mA")
            if idq_a > max_idq_a:
                self._log(f"    !! ABORT: Idq={idq_ma:.2f} > {max_idq_ma:.1f} mA")
                return False
            if abs(idq_a - target_a) <= tolerance_a:
                self._log(f"    ✓ Converged: {idq_ma:.2f} mA  Gate={gate_v:.4f} V")
                return True
            if idq_a > target_a:
                self._log(f"    Overshot at {idq_ma:.2f} mA — holding")
                return True
            gate_v = min(round(gate_v + step_v, 6), MAX_GATE_V_GAN)
            try:
                drv.set_voltage(ch, gate_v)
            except Exception as e:
                self._log(f"    Gate set error: {e}")
                return False
            time.sleep(IDQ_STEP_SETTLE_S)
        self._log(f"    Did not converge after {IDQ_MAX_STEPS} steps — holding")
        return True

    # ── Log helper ─────────────────────────────────────────────
    def _log(self, message: str):
        ts   = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
        line = f"[{ts}] {message}\n"
        _logger.info(message)
        def _upd():
            self.log_text.config(state="normal")
            self.log_text.insert(tk.END, line)
            self.log_text.see(tk.END)
            self.log_text.config(state="disabled")
        self.after(0, _upd)
