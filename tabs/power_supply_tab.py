import tkinter as tk
from tkinter import ttk, messagebox
import json
import os
from utils.logger import get_logger
from utils.live_poll_manager import LivePollManager

_logger = get_logger(__name__)

# Channel counts per known supply model — used only to infer channels
# when a driver doesn't expose a _channels attribute.
_CHANNEL_COUNT_HINTS = {
    "Keysight_E36234A":      4,
    "Keysight_E36233A":      2,
    "Agilent_E3648A_GPIB15": 2,
    "Agilent_E3648A_GPIB11": 2,
    "Agilent_3648A":         2,
    "HP_6633B":              1,
}

_PS_ROLES = {"Power Supply", "power supply", "Power supply"}

_COL_CHECK   = 0
_COL_CHANNEL = 1
_COL_ROLE    = 2
_COL_MODE    = 3
_COL_SET_V   = 4
_COL_SET_A   = 5
_COL_PROT    = 6
_COL_MEAS_V  = 7
_COL_MEAS_A  = 8
_COL_OUTPUT  = 9

ALIASES_FILE         = "instrument_aliases.json"
READBACK_INTERVAL_MS = 1500
UI_REFRESH_MS        = 250

_LOCKED = "\u2014"


def _infer_channels(name: str, drv) -> int:
    """Return channel count for a driver object."""
    if hasattr(drv, "_channels"):
        return int(drv._channels)
    return _CHANNEL_COUNT_HINTS.get(name, 1)


def _is_power_supply(drv) -> bool:
    """Return True if the driver looks like a power supply."""
    cls = drv.__class__.__name__.lower()
    return any(k in cls for k in ("supply", "psu", "6633", "e364", "e362", "e363"))


class PowerSupplyTab(ttk.Frame):
    def __init__(self, parent, driver_registry: dict):
        super().__init__(parent)
        self._registry      = driver_registry
        self._channels      = {}
        self._active_rows   = []
        self._row_checked   = {}
        self._output_state  = {}
        self._output_btns   = {}
        self._alias_map     = self._load_aliases()
        self._inline_widget = None
        self._ui_refresh_job = None
        self._poll_manager = LivePollManager(
            registry_getter=lambda: self._registry,
            channels_getter=lambda: self._channels,
        )
        self._build_ui()
        self._init_channel_store()

    # ── Public API ─────────────────────────────────────────────
    def set_driver_registry(self, registry: dict):
        self._registry = registry
        self._init_channel_store()

    def set_aliases(self, alias_map: dict):
        self._alias_map = alias_map
        self._init_channel_store()
        self._populate_available_tree()

    def stop_polling(self):
        self._stop_live_readback()

    def get_pairs(self) -> list:
        return []

    def get_active_channels(self) -> list:
        result = []
        for ch_id in self._active_rows:
            if not self._row_checked.get(ch_id, tk.BooleanVar(value=False)).get():
                continue
            info = self._channels[ch_id]
            result.append({
                "ch_id":            ch_id,
                "supply":           info["supply"],
                "channel":          info["channel"],
                "label":            info["label"],
                "role":             info["role"],
                "mode":             info["mode"],
                "volt_var":         info["volt_var"].get(),
                "curr_var":         info["curr_var"].get(),
                "ocp_var":          info["ocp_var"].get(),
                "ovp_var":          info["ovp_var"].get(),
                "target_idq_ma":    info["target_idq_ma"].get(),
                "idq_tolerance_ma": info["idq_tolerance_ma"].get(),
                "idq_step_mv":      info["idq_step_mv"].get(),
                "max_idq_ma":       info["max_idq_ma"].get(),
            })
        return result

    # ── Alias helpers ──────────────────────────────────────────
    def _load_aliases(self) -> dict:
        if os.path.exists(ALIASES_FILE):
            try:
                with open(ALIASES_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def _ch_label(self, supply_name: str, ch: int) -> str:
        alias = self._alias_map.get(supply_name, "")
        if alias:
            return f"{alias} CH{ch}  ({supply_name})"
        return f"{supply_name} CH{ch}"

    # ── Connected power supply helpers ─────────────────────────
    def _connected_supplies(self) -> list:
        """
        Return list of dicts for every power-supply driver currently in the
        registry: {name, channels}.
        Only drivers whose class name looks like a power supply are included.
        """
        result = []
        for name, drv in self._registry.items():
            if _is_power_supply(drv):
                result.append({"name": name, "channels": _infer_channels(name, drv)})
        return result

    # ── UI build ───────────────────────────────────────────────
    def _build_ui(self):
        ttk.Label(
            self, text="Power Supply Configuration",
            font=("Segoe UI", 14, "bold"),
        ).pack(pady=10)

        top = ttk.Frame(self)
        top.pack(fill="x", padx=10, pady=(0, 4))
        ttk.Button(top, text="+ Add Supply", command=self._open_add_dialog).pack(side="left", padx=(0, 4))
        ttk.Button(top, text="\u21bb Refresh", command=self._init_channel_store).pack(side="left", padx=(0, 4))
        ttk.Label(
            top,
            text="Click a cell to edit inline.  Double-click opens full edit dialog.  \u2014 = locked by mode.",
            foreground="gray",
        ).pack(side="left", padx=12)

        pane = ttk.PanedWindow(self, orient="vertical")
        pane.pack(fill="both", expand=True, padx=10, pady=4)

        avail_frame = ttk.LabelFrame(pane, text="Connected Power Supplies  (select then click + Add Supply)")
        pane.add(avail_frame, weight=1)
        av_cols = ("Supply", "Alias", "Outputs")
        self.avail_tree = ttk.Treeview(avail_frame, columns=av_cols, show="headings", height=5)
        for col, w in {"Supply": 260, "Alias": 220, "Outputs": 80}.items():
            self.avail_tree.heading(col, text=col)
            self.avail_tree.column(col, width=w, anchor="center")
        self.avail_tree.pack(fill="both", expand=True, padx=5, pady=5)

        active_frame = ttk.LabelFrame(pane, text="Active Supplies")
        pane.add(active_frame, weight=4)

        act_cols = ("\u2611", "Channel", "Role", "Mode", "Set V", "Set A", "Prot Limit", "Meas V", "Meas A", "Output")
        self.tree = ttk.Treeview(active_frame, columns=act_cols, show="headings", height=13)
        for col, w in {
            "\u2611": 34, "Channel": 260, "Role": 75, "Mode": 55,
            "Set V": 80, "Set A": 80, "Prot Limit": 110,
            "Meas V": 90, "Meas A": 90, "Output": 70,
        }.items():
            self.tree.heading(col, text=col)
            self.tree.column(col, width=w, anchor="center")

        self.tree.tag_configure("locked", foreground="#888888")

        self.tree.pack(fill="both", expand=True, padx=5, pady=5)
        self.tree.bind("<Button-1>",  self._on_click)
        self.tree.bind("<Double-1>",  self._on_double_click)
        self.tree.bind("<Configure>", lambda e: self._reposition_output_btns())

        bot = ttk.Frame(active_frame)
        bot.pack(fill="x", padx=5, pady=(0, 4))
        ttk.Button(bot, text="Edit Selected",   command=self._edit_selected).pack(side="left", padx=(0, 4))
        ttk.Button(bot, text="Remove Selected", command=self._remove_selected).pack(side="left", padx=4)
        ttk.Button(bot, text="Read Once",       command=self._read_once).pack(side="left", padx=4)
        ttk.Separator(bot, orient="vertical").pack(side="left", fill="y", padx=8, pady=2)
        ttk.Button(bot, text="Set Checked", command=self._set_checked_rows).pack(side="left", padx=4)
        tk.Button(
            bot, text="  ON (all checked)  ",
            bg="#1a7a1a", fg="white",
            activebackground="#145a14", activeforeground="white",
            font=("Segoe UI", 9, "bold"),
            command=lambda: self._output_checked(True),
        ).pack(side="left", padx=4)
        tk.Button(
            bot, text="  OFF (all checked)  ",
            bg="#8b0000", fg="white",
            activebackground="#5a0000", activeforeground="white",
            font=("Segoe UI", 9, "bold"),
            command=lambda: self._output_checked(False),
        ).pack(side="left", padx=4)

        rb = ttk.Frame(active_frame)
        rb.pack(fill="x", padx=5, pady=(0, 6))
        ttk.Label(rb, text="Readback interval (ms):").pack(side="left", padx=(0, 4))
        self.rb_interval_var = tk.StringVar(value=str(READBACK_INTERVAL_MS))
        ttk.Entry(rb, textvariable=self.rb_interval_var, width=7).pack(side="left", padx=4)
        self.rb_btn = ttk.Button(rb, text="Start Live Readback", command=self._toggle_readback)
        self.rb_btn.pack(side="left", padx=8)

        self.status_lbl = ttk.Label(self, text="Status: Idle", foreground="gray")
        self.status_lbl.pack(pady=5)

    # ── Channel store ──────────────────────────────────────────
    def _init_channel_store(self):
        existing = {k: v for k, v in self._channels.items()}
        self._channels.clear()

        for ps in self._connected_supplies():
            name = ps["name"]
            for ch in range(1, ps["channels"] + 1):
                ch_id = f"{name}_CH{ch}"
                prev  = existing.get(ch_id, {})
                self._channels[ch_id] = {
                    "supply":           name,
                    "channel":          ch,
                    "label":            self._ch_label(name, ch),
                    "role":             prev.get("role",  "None"),
                    "mode":             prev.get("mode",  "CV"),
                    "volt_var":         prev.get("volt_var",         tk.StringVar(value="")),
                    "curr_var":         prev.get("curr_var",         tk.StringVar(value="")),
                    "ovp_var":          prev.get("ovp_var",          tk.StringVar(value="")),
                    "ocp_var":          prev.get("ocp_var",          tk.StringVar(value="")),
                    "target_idq_ma":    prev.get("target_idq_ma",    tk.StringVar(value="")),
                    "idq_tolerance_ma": prev.get("idq_tolerance_ma", tk.StringVar(value="5")),
                    "idq_step_mv":      prev.get("idq_step_mv",      tk.StringVar(value="50")),
                    "max_idq_ma":       prev.get("max_idq_ma",       tk.StringVar(value="")),
                }
                self._poll_manager.ensure_channel(ch_id)

        # Remove active rows whose supply is no longer connected
        self._active_rows = [r for r in self._active_rows if r in self._channels]
        self._poll_manager.remove_missing_channels(self._channels.keys())
        self._populate_available_tree()
        self._refresh_active_tree()

    def _populate_available_tree(self):
        self.avail_tree.delete(*self.avail_tree.get_children())
        for ps in self._connected_supplies():
            name  = ps["name"]
            alias = self._alias_map.get(name, "")
            self.avail_tree.insert("", "end", iid=name,
                                   values=(name, alias, ps["channels"]))

    # ── Active row management ──────────────────────────────────
    def _open_add_dialog(self):
        sel = self.avail_tree.selection()
        if not sel:
            messagebox.showwarning("No Selection", "Select a supply from the Connected list first.")
            return
        supply_name = sel[0]
        ps = next((x for x in self._connected_supplies() if x["name"] == supply_name), None)
        if not ps:
            return
        dlg = tk.Toplevel(self)
        dlg.title(f"Add: {supply_name}")
        dlg.grab_set()
        dlg.resizable(False, False)
        alias   = self._alias_map.get(supply_name, "")
        display = f"{alias}  ({supply_name})" if alias else supply_name
        ttk.Label(dlg, text=display, font=("Segoe UI", 10, "bold")).pack(padx=14, pady=(12, 4))
        ttk.Label(dlg, text="Select which output(s) to add:", foreground="gray").pack(padx=14, pady=(0, 8))
        ch_vars = {}
        for ch in range(1, ps["channels"] + 1):
            var = tk.BooleanVar(value=True)
            ch_vars[ch] = var
            ttk.Checkbutton(
                dlg,
                text=f"Output {ch}  ({self._ch_label(supply_name, ch)})",
                variable=var,
            ).pack(anchor="w", padx=18, pady=3)

        def _do_add():
            added = 0
            for ch, var in ch_vars.items():
                if var.get():
                    self._add_active_row(f"{supply_name}_CH{ch}")
                    added += 1
            if added == 0:
                messagebox.showwarning("Nothing Selected", "Check at least one output to add.")
                return
            dlg.destroy()

        btn_row = ttk.Frame(dlg)
        btn_row.pack(pady=12)
        ttk.Button(btn_row, text="Add Selected", command=_do_add).pack(side="left", padx=6)
        ttk.Button(btn_row, text="Cancel",       command=dlg.destroy).pack(side="left", padx=6)

    def _add_active_row(self, ch_id: str):
        if ch_id not in self._channels:
            return
        if ch_id not in self._active_rows:
            self._active_rows.append(ch_id)
            self._row_checked[ch_id]  = tk.BooleanVar(value=True)
            self._output_state[ch_id] = False
        self._refresh_active_tree()

    def _remove_selected(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showwarning("No Selection", "Select an active row first.")
            return
        self._dismiss_inline()
        ch_id = sel[0]
        if ch_id in self._active_rows:
            self._active_rows.remove(ch_id)
        self._row_checked.pop(ch_id, None)
        self._output_state.pop(ch_id, None)
        self._destroy_output_btn(ch_id)
        self._refresh_active_tree()

    # ── Row values helper ────────────────────────────────────────
    def _row_values(self, ch_id: str, checked_str: str, meas_v="---", meas_a="---") -> tuple:
        info = self._channels[ch_id]
        mode = info["mode"]
        if mode == "CV":
            set_v = info["volt_var"].get() or ""
            set_a = _LOCKED
            prot  = f"OCP {info['ocp_var'].get()} A" if info["ocp_var"].get() else ""
        else:
            set_v = _LOCKED
            set_a = info["curr_var"].get() or ""
            prot  = f"OVP {info['ovp_var'].get()} V" if info["ovp_var"].get() else ""
        return (checked_str, info["label"], info["role"], mode,
                set_v, set_a, prot, meas_v, meas_a, "")

    def _refresh_active_tree(self):
        for ch_id in list(self._output_btns):
            self._destroy_output_btn(ch_id)
        self.tree.delete(*self.tree.get_children())
        for ch_id in self._active_rows:
            info    = self._channels[ch_id]
            checked = "\u2611" if self._row_checked.get(ch_id, tk.BooleanVar(value=True)).get() else "\u2610"
            vals    = self._row_values(ch_id, checked)
            tag = "locked" if info["mode"] in ("CV", "CC") else ""
            self.tree.insert("", "end", iid=ch_id, values=vals, tags=(tag,))
        self.tree.after(30, self._reposition_output_btns)

    # ── Per-row output toggle buttons ────────────────────────────
    def _get_output_col_id(self) -> str:
        cols = self.tree["columns"]
        return f"#{cols.index('Output') + 1}"

    def _reposition_output_btns(self):
        col_id = self._get_output_col_id()
        for ch_id in self._active_rows:
            bbox = self.tree.bbox(ch_id, col_id)
            if not bbox:
                btn = self._output_btns.get(ch_id)
                if btn:
                    btn.place_forget()
                continue
            x, y, w, h = bbox
            is_on = self._output_state.get(ch_id, False)
            if ch_id not in self._output_btns:
                btn = tk.Button(
                    self.tree,
                    font=("Segoe UI", 8, "bold"),
                    relief="flat", bd=0, cursor="hand2",
                )
                self._output_btns[ch_id] = btn
            else:
                btn = self._output_btns[ch_id]
            if is_on:
                btn.config(
                    text="ON",
                    bg="#1a7a1a", fg="white",
                    activebackground="#145a14", activeforeground="white",
                    command=lambda cid=ch_id: self._toggle_output_btn(cid),
                )
            else:
                btn.config(
                    text="OFF",
                    bg="#555555", fg="white",
                    activebackground="#333333", activeforeground="white",
                    command=lambda cid=ch_id: self._toggle_output_btn(cid),
                )
            btn.place(x=x + 2, y=y + 1, width=w - 4, height=h - 2)

    def _toggle_output_btn(self, ch_id: str):
        self._channel_output(ch_id, not self._output_state.get(ch_id, False))

    def _destroy_output_btn(self, ch_id: str):
        btn = self._output_btns.pop(ch_id, None)
        if btn:
            try: btn.destroy()
            except Exception: pass

    # ── Inline cell editing ────────────────────────────────────
    _INLINE_COLS = {
        _COL_ROLE:  "combo",
        _COL_MODE:  "combo",
        _COL_SET_V: "entry",
        _COL_SET_A: "entry",
        _COL_PROT:  "entry",
    }
    _COMBO_VALUES = {
        _COL_ROLE: ["None", "Gate", "Drain"],
        _COL_MODE: ["CV", "CC"],
    }

    def _is_locked_col(self, ch_id: str, col_idx: int) -> bool:
        mode = self._channels[ch_id]["mode"]
        if col_idx == _COL_SET_A and mode == "CV":
            return True
        if col_idx == _COL_SET_V and mode == "CC":
            return True
        return False

    def _on_click(self, event):
        region  = self.tree.identify_region(event.x, event.y)
        col_id  = self.tree.identify_column(event.x)
        ch_id   = self.tree.identify_row(event.y)
        self._dismiss_inline(commit=True)
        if region != "cell" or not ch_id:
            return
        col_idx = int(col_id.lstrip("#")) - 1
        if col_idx == _COL_CHECK:
            if ch_id in self._row_checked:
                var = self._row_checked[ch_id]
                var.set(not var.get())
                self._refresh_active_tree()
            return
        if col_idx not in self._INLINE_COLS:
            return
        if self._is_locked_col(ch_id, col_idx):
            return
        self._open_inline(ch_id, col_idx, col_id, self._INLINE_COLS[col_idx])

    def _on_double_click(self, event):
        col_idx = int(self.tree.identify_column(event.x).lstrip("#")) - 1
        if col_idx == _COL_CHECK:
            return
        sel = self.tree.selection()
        if sel:
            self._dismiss_inline(commit=False)
            self._open_edit_dialog(sel[0])

    def _open_inline(self, ch_id, col_idx, col_id, edit_type):
        bbox = self.tree.bbox(ch_id, col_id)
        if not bbox:
            return
        x, y, w, h = bbox
        info = self._channels[ch_id]
        if col_idx == _COL_ROLE:   cur_val = info["role"]
        elif col_idx == _COL_MODE: cur_val = info["mode"]
        elif col_idx == _COL_SET_V: cur_val = info["volt_var"].get()
        elif col_idx == _COL_SET_A: cur_val = info["curr_var"].get()
        elif col_idx == _COL_PROT:
            cur_val = info["ocp_var"].get() if info["mode"] == "CV" else info["ovp_var"].get()
        else: cur_val = ""
        var = tk.StringVar(value=cur_val)
        if edit_type == "combo":
            widget = ttk.Combobox(
                self.tree, textvariable=var,
                values=self._COMBO_VALUES[col_idx],
                state="readonly", width=max(w // 8, 8),
            )
            widget.set(cur_val)
        else:
            widget = ttk.Entry(self.tree, textvariable=var, width=max(w // 8, 6))
        widget.place(x=x, y=y, width=w, height=h)
        widget.focus_set()
        if edit_type == "entry":
            widget.select_range(0, "end")

        def _commit(e=None):
            self._apply_inline(ch_id, col_idx, var.get())
            self._dismiss_inline(commit=False)

        def _cancel(e=None):
            self._dismiss_inline(commit=False)

        widget.bind("<Return>",   _commit)
        widget.bind("<Tab>",      _commit)
        widget.bind("<Escape>",   _cancel)
        widget.bind("<FocusOut>", _commit)
        if edit_type == "combo":
            widget.bind("<<ComboboxSelected>>", _commit)
        self._inline_widget = widget

    def _apply_inline(self, ch_id, col_idx, value):
        info  = self._channels[ch_id]
        value = value.strip()
        if col_idx == _COL_ROLE:    info["role"] = value
        elif col_idx == _COL_MODE:
            if value in ("CV", "CC"): info["mode"] = value
        elif col_idx == _COL_SET_V: info["volt_var"].set(value)
        elif col_idx == _COL_SET_A: info["curr_var"].set(value)
        elif col_idx == _COL_PROT:
            if info["mode"] == "CV": info["ocp_var"].set(value)
            else:                    info["ovp_var"].set(value)
        self._update_tree_row(ch_id)

    def _dismiss_inline(self, commit=False):
        if self._inline_widget is not None:
            try: self._inline_widget.destroy()
            except Exception: pass
            self._inline_widget = None

    # ── Full edit dialog ─────────────────────────────────────────
    def _edit_selected(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showwarning("No Selection", "Select a row to edit.")
            return
        self._dismiss_inline(commit=False)
        self._open_edit_dialog(sel[0])

    def _open_edit_dialog(self, ch_id):
        info   = self._channels[ch_id]
        dialog = tk.Toplevel(self)
        dialog.title(f"Configure: {info['label']}")
        dialog.grab_set()
        dialog.resizable(False, False)
        ttk.Label(dialog, text=info["label"], font=("Segoe UI", 10, "bold")).grid(
            row=0, column=0, columnspan=2, padx=15, pady=10)
        role_var = tk.StringVar(value=info["role"])
        mode_var = tk.StringVar(value=info["mode"])

        role_frame = ttk.LabelFrame(dialog, text="Role")
        role_frame.grid(row=1, column=0, columnspan=2, padx=12, pady=4, sticky="ew")
        ttk.Label(role_frame, text="Role:", width=14, anchor="e").grid(row=0, column=0, padx=8, pady=6, sticky="e")
        ttk.Combobox(role_frame, textvariable=role_var, values=["None", "Gate", "Drain"],
                     state="readonly", width=14).grid(row=0, column=1, padx=8, pady=6, sticky="w")

        mode_frame = ttk.LabelFrame(dialog, text="Output Mode")
        mode_frame.grid(row=2, column=0, columnspan=2, padx=12, pady=4, sticky="ew")
        ttk.Radiobutton(mode_frame, text="CV \u2014 Constant Voltage", variable=mode_var, value="CV",
                        command=lambda: _refresh_val_rows()).grid(row=0, column=0, padx=12, pady=(8, 2), sticky="w")
        ttk.Label(mode_frame,
                  text="You set: Voltage (V)  +  Current Limit / OCP (A)\nSupply holds the voltage. Current limit caps output current.",
                  foreground="gray", justify="left").grid(row=1, column=0, padx=28, pady=(0, 6), sticky="w")
        ttk.Radiobutton(mode_frame, text="CC \u2014 Constant Current", variable=mode_var, value="CC",
                        command=lambda: _refresh_val_rows()).grid(row=2, column=0, padx=12, pady=(4, 2), sticky="w")
        ttk.Label(mode_frame,
                  text="You set: Current (A)  +  OVP Limit (V)\nSupply holds the current. Trips off if voltage exceeds OVP.",
                  foreground="gray", justify="left").grid(row=3, column=0, padx=28, pady=(0, 8), sticky="w")

        vals_frame = ttk.LabelFrame(dialog, text="Values")
        vals_frame.grid(row=3, column=0, columnspan=2, padx=12, pady=4, sticky="ew")
        lbl_volt  = ttk.Label(vals_frame, text="Set Voltage (V):", width=20, anchor="e")
        ent_volt  = ttk.Entry(vals_frame, textvariable=info["volt_var"], width=14)
        lbl_ocp   = ttk.Label(vals_frame, text="Current Limit / OCP (A):", width=24, anchor="e")
        ent_ocp   = ttk.Entry(vals_frame, textvariable=info["ocp_var"],  width=14)
        lbl_curr  = ttk.Label(vals_frame, text="Set Current (A):", width=20, anchor="e")
        ent_curr  = ttk.Entry(vals_frame, textvariable=info["curr_var"], width=14)
        lbl_ovp   = ttk.Label(vals_frame, text="OVP Limit (V):",   width=20, anchor="e")
        ent_ovp   = ttk.Entry(vals_frame, textvariable=info["ovp_var"],  width=14)
        gate_warn = ttk.Label(vals_frame,
                              text="Gate voltage must be negative for GaN (e.g. -3.0 V)",
                              foreground="orange")

        def _refresh_val_rows():
            for w in (lbl_volt, ent_volt, lbl_ocp, ent_ocp,
                      lbl_curr, ent_curr, lbl_ovp, ent_ovp, gate_warn):
                w.grid_remove()
            if mode_var.get() == "CV":
                lbl_volt.grid(row=0, column=0, padx=8, pady=5, sticky="e")
                ent_volt.grid(row=0, column=1, padx=8, pady=5, sticky="w")
                lbl_ocp.grid( row=1, column=0, padx=8, pady=5, sticky="e")
                ent_ocp.grid( row=1, column=1, padx=8, pady=5, sticky="w")
                gate_warn.grid(row=2, column=0, columnspan=2, padx=8, pady=(0, 6))
            else:
                lbl_curr.grid(row=0, column=0, padx=8, pady=5, sticky="e")
                ent_curr.grid(row=0, column=1, padx=8, pady=5, sticky="w")
                lbl_ovp.grid( row=1, column=0, padx=8, pady=5, sticky="e")
                ent_ovp.grid( row=1, column=1, padx=8, pady=5, sticky="w")
        _refresh_val_rows()

        idq_frame = ttk.LabelFrame(dialog, text="Idq Targeting  (Drain channel only)")
        idq_frame.grid(row=4, column=0, columnspan=2, padx=12, pady=4, sticky="ew")

        def idq_row(parent, label, var, row, hint=""):
            ttk.Label(parent, text=label, width=22, anchor="e").grid(row=row, column=0, padx=8, pady=4, sticky="e")
            ttk.Entry(parent, textvariable=var, width=12).grid(row=row, column=1, padx=8, pady=4, sticky="w")
            if hint:
                ttk.Label(parent, text=hint, foreground="gray").grid(row=row, column=2, padx=4, sticky="w")

        idq_row(idq_frame, "Target Idq (mA):",       info["target_idq_ma"],    0, "Leave blank to skip")
        idq_row(idq_frame, "Tolerance \u00b1 (mA):", info["idq_tolerance_ma"], 1, "Default: 5 mA")
        idq_row(idq_frame, "Gate Step Size (mV):",   info["idq_step_mv"],      2, "Default: 50 mV")
        idq_row(idq_frame, "Hard Abort > (mA):",     info["max_idq_ma"],       3, "Leave blank = 3\u00d7 target")
        ttk.Label(idq_frame,
                  text="Set on the DRAIN channel. The sequencer walks gate voltage\ntoward final gate V while monitoring drain current.",
                  foreground="gray").grid(row=4, column=0, columnspan=3, padx=8, pady=(0, 6))

        btn_frame = ttk.Frame(dialog)
        btn_frame.grid(row=5, column=0, columnspan=2, pady=10)

        def _apply_meta():
            info["role"] = role_var.get()
            info["mode"] = mode_var.get()
            self._update_tree_row(ch_id)

        ttk.Button(btn_frame, text="Apply (no hardware)",
                   command=lambda: (_apply_meta(), dialog.destroy())).pack(side="left", padx=6)
        ttk.Button(btn_frame, text="Set Values",
                   command=lambda: (_apply_meta(), dialog.destroy(), self._set_channel_values(ch_id))).pack(side="left", padx=6)
        ttk.Button(btn_frame, text="Set + ON",
                   command=lambda: (_apply_meta(), dialog.destroy(),
                                    self._set_channel_values(ch_id), self._channel_output(ch_id, True))).pack(side="left", padx=6)

    # ── Tree row refresh ─────────────────────────────────────────
    def _update_tree_row(self, ch_id):
        if not self.tree.exists(ch_id):
            return
        vals    = list(self.tree.item(ch_id, "values"))
        checked = vals[_COL_CHECK]
        new_vals = self._row_values(ch_id, checked,
                                    meas_v=vals[_COL_MEAS_V],
                                    meas_a=vals[_COL_MEAS_A])
        self.tree.item(ch_id, values=new_vals, tags=("locked",))
        self.tree.after(20, self._reposition_output_btns)

    # ── Group actions ───────────────────────────────────────────
    def _set_checked_rows(self):
        did_any = False
        for ch_id in self._active_rows:
            if self._row_checked.get(ch_id, tk.BooleanVar(value=False)).get():
                self._set_channel_values(ch_id)
                did_any = True
        if not did_any:
            messagebox.showwarning("Nothing Checked", "Check at least one active row first.")

    def _output_checked(self, enable: bool):
        did_any = False
        for ch_id in self._active_rows:
            if self._row_checked.get(ch_id, tk.BooleanVar(value=False)).get():
                self._channel_output(ch_id, enable)
                did_any = True
        if not did_any:
            messagebox.showwarning("Nothing Checked", "Check at least one active row first.")

    # ── Hardware actions ───────────────────────────────────────
    def _set_channel_values(self, ch_id):
        info = self._channels[ch_id]
        drv  = self._registry.get(info["supply"])
        if drv is None:
            messagebox.showerror("Not Connected", f"{info['supply']} not in driver registry.")
            return
        try:
            if info["mode"] == "CV":
                volt_str = info["volt_var"].get().strip()
                ocp_str  = info["ocp_var"].get().strip()
                if not volt_str:
                    messagebox.showwarning("Missing Value", f"Enter a voltage for {ch_id}.")
                    return
                volts = float(volt_str)
                if info["role"] == "Gate" and volts > 0:
                    if not messagebox.askyesno(
                        "Gate Warning",
                        f"Gate voltage {volts} V is positive.\nGate should normally be negative for GaN.\nSend anyway?",
                    ):
                        return
                drv.set_voltage(info["channel"], volts)
                if ocp_str:
                    amps = float(ocp_str)
                    # set_current sets the hardware current limit (CURR command).
                    # set_ocp sets the protection trip threshold (CURR:PROT on Keysight).
                    # Both are sent so instruments with separate registers (e.g. Keysight)
                    # have the current limit correctly applied, not just the OCP trip point.
                    if hasattr(drv, "set_current"):
                        drv.set_current(info["channel"], amps)
                    drv.set_ocp(info["channel"], amps)
                self.status_lbl.config(
                    text=f"Set {info['label']}: {volts} V  | Curr Limit = {ocp_str or 'unchanged'} A",
                    foreground="blue")
                _logger.info(f"Set {ch_id} CV: {volts} V  curr_limit/OCP={ocp_str}")
            else:
                curr_str = info["curr_var"].get().strip()
                ovp_str  = info["ovp_var"].get().strip()
                if not curr_str:
                    messagebox.showwarning("Missing Value", f"Enter a current for {ch_id}.")
                    return
                amps = float(curr_str)
                drv.set_current(info["channel"], amps)
                if ovp_str: drv.set_ovp(info["channel"], float(ovp_str))
                self.status_lbl.config(
                    text=f"Set {info['label']}: {amps} A  | OVP = {ovp_str or 'unchanged'} V",
                    foreground="blue")
                _logger.info(f"Set {ch_id} CC: {amps} A  OVP={ovp_str}")
            self._update_tree_row(ch_id)
        except ValueError:
            messagebox.showerror("Invalid Input", "Values must be numbers.")
        except Exception as e:
            messagebox.showerror("Hardware Error", str(e))
            _logger.error(f"Set values failed {ch_id}: {e}")

    def _channel_output(self, ch_id, enable: bool):
        info = self._channels[ch_id]
        drv  = self._registry.get(info["supply"])
        if drv is None:
            messagebox.showerror("Not Connected", f"{info['supply']} not in driver registry.")
            return
        try:
            drv.output_on(info["channel"], enable)
            self._output_state[ch_id] = enable
            color = "green" if enable else "gray"
            self.status_lbl.config(
                text=f"{info['label']} output {'ON' if enable else 'OFF'}",
                foreground=color)
            _logger.info(f"{ch_id} output {'ON' if enable else 'OFF'}")
            self._reposition_output_btns()
        except Exception as e:
            messagebox.showerror("Hardware Error", str(e))
            _logger.error(f"Output toggle failed {ch_id}: {e}")

    # ── Live readback ──────────────────────────────────────────
    def _toggle_readback(self):
        if self._poll_manager.is_running():
            self._stop_live_readback()
        else:
            self._start_live_readback()

    def _start_live_readback(self):
        try:
            interval_ms = int(self.rb_interval_var.get())
            if interval_ms < 100: raise ValueError
        except ValueError:
            messagebox.showerror("Invalid Interval", "Interval must be an integer >= 100 ms.")
            return
        self._poll_manager.start(interval_ms)
        self.rb_btn.config(text="Stop Live Readback")
        self.status_lbl.config(text="Status: Readback running...", foreground="orange")
        self._schedule_ui_refresh()

    def _stop_live_readback(self):
        self._poll_manager.stop()
        self.rb_btn.config(text="Start Live Readback")
        self.status_lbl.config(text="Status: Readback stopped", foreground="gray")
        if self._ui_refresh_job is not None:
            try: self.after_cancel(self._ui_refresh_job)
            except Exception: pass
            self._ui_refresh_job = None

    def _read_once(self):
        self._poll_manager.poll_once()
        self._refresh_readback_ui()
        self.status_lbl.config(text="Status: Readback complete", foreground="green")

    def _schedule_ui_refresh(self):
        if self._ui_refresh_job is not None:
            try: self.after_cancel(self._ui_refresh_job)
            except Exception: pass
        self._ui_refresh_job = self.after(UI_REFRESH_MS, self._refresh_readback_ui)

    def _refresh_readback_ui(self):
        snapshot = self._poll_manager.get_cache_snapshot()
        for ch_id, cache in snapshot.items():
            if not self.tree.exists(ch_id):
                continue
            vals              = list(self.tree.item(ch_id, "values"))
            vals[_COL_MEAS_V] = cache.get("meas_v", "---")
            vals[_COL_MEAS_A] = cache.get("meas_a", "---")
            self.tree.item(ch_id, values=vals)
        self._reposition_output_btns()
        if self._poll_manager.is_running():
            self._schedule_ui_refresh()
        else:
            self._ui_refresh_job = None
