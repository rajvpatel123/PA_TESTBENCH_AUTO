# tabs/device_info_tab.py
import tkinter as tk
from tkinter import ttk, messagebox
import json
import os
from utils.logger import get_logger
from utils.visa_helper import load_driver
from utils.ui_theme import (
    APP_COLORS,
    apply_zebra_tags,
    make_header,
    set_status_label,
    style_treeview_zebra,
)

_logger = get_logger(__name__)

ALIASES_FILE = "instrument_aliases.json"

COMPANY_INSTRUMENTS = [
    {"name": "Keysight_E36234A_90",      "address": "USB0::0x2A8D::0x3402::MY61002290::INSTR", "role": "Power Supply"},
    {"name": "Keysight_E36233A_32",      "address": "USB0::0x2A8D::0x3302::MY61003932::INSTR", "role": "Power Supply"},
    {"name": "Agilent_E3648A_GPIB15", "address": "GPIB0::15::INSTR",                        "role": "Power Supply"},
    {"name": "Agilent_E3648A_GPIB11", "address": "GPIB0::11::INSTR",                        "role": "Power Supply"},
    {"name": "Agilent_3648A",         "address": "GPIB0::10::INSTR",                        "role": "Power Supply"},
    {"name": "Keysight_34465A_1",     "address": "USB0::0x2A8D::0x0101::MY60050792::INSTR", "role": "DMM"},
    {"name": "Keysight_34465A_2",     "address": "USB0::0x2A8D::0x0101::MY59001442::INSTR", "role": "DMM"},
    {"name": "Keysight_34461A",       "address": "USB0::0x2A8D::0x1301::MY57206934::0::INSTR", "role": "DMM"},
    {"name": "PXA_N9030A",            "address": "GPIB0::18::INSTR",                        "role": "Spectrum Analyzer"},
    {"name": "RS_SMBV100B",           "address": "GPIB0::28::INSTR",                        "role": "Signal Generator"},
]


class DeviceInfoTab(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        self.configure(style="TFrame")

        self._driver_update_callback = None
        self._driver_registry        = {}
        self._alias_map              = self._load_aliases()

        self._build_ui()
        self._populate_devices()

    def set_driver_update_callback(self, callback):
        self._driver_update_callback = callback

    def register_driver_callback(self, callback):
        self.set_driver_update_callback(callback)

    def get_driver_registry(self) -> dict:
        return self._driver_registry

    def set_driver_registry(self, registry: dict):
        self._driver_registry = registry or {}
        self._notify_driver_update()

    # ── Aliases ────────────────────────────────────────────────
    def _load_aliases(self) -> dict:
        if os.path.exists(ALIASES_FILE):
            try:
                with open(ALIASES_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                _logger.warning(f"Failed to load aliases: {e}")
        return {}

    def _save_aliases(self):
        try:
            with open(ALIASES_FILE, "w", encoding="utf-8") as f:
                json.dump(self._alias_map, f, indent=2)
        except Exception as e:
            _logger.error(f"Failed to save aliases: {e}")

    # ── UI ─────────────────────────────────────────────────────
    def _build_ui(self):
        make_header(
            self,
            "Device Manager",
            "Connect instruments, verify communication, and manage friendly aliases.",
        )

        top_shell = ttk.Frame(self)
        top_shell.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        # Main content split
        content = ttk.Frame(top_shell)
        content.pack(fill="both", expand=True)

        left  = ttk.Frame(content)
        left.pack(side="left", fill="both", expand=True, padx=(0, 8))

        right = ttk.LabelFrame(content, text="Selected Device",
                               style="Card.TLabelframe")
        right.pack(side="right", fill="y")
        right.configure(padding=12)

        # Toolbar
        toolbar = ttk.Frame(left, style="Panel.TFrame")
        toolbar.pack(fill="x", pady=(0, 8))
        toolbar.configure(padding=10)

        ttk.Button(toolbar, text="Connect All",
                   command=self._connect_all,
                   style="Primary.TButton").pack(side="left", padx=(0, 8))
        ttk.Button(toolbar, text="Reconnect Selected",
                   command=self._reconnect_selected).pack(side="left", padx=4)
        ttk.Button(toolbar, text="Self-Test",
                   command=self._self_test_selected).pack(side="left", padx=4)
        ttk.Button(toolbar, text="Reset",
                   command=self._reset_selected).pack(side="left", padx=4)
        ttk.Button(toolbar, text="Edit Alias",
                   command=self._edit_alias).pack(side="left", padx=4)
        ttk.Button(toolbar, text="Clear List",
                   command=self._clear_list).pack(side="left", padx=4)

        # Table panel
        table_panel = ttk.Frame(left, style="Panel.TFrame")
        table_panel.pack(fill="both", expand=True)
        table_panel.configure(padding=10)

        cols = ("Name", "Alias", "Role", "Address", "IDN", "Driver", "Status")
        self.tree = ttk.Treeview(
            table_panel, columns=cols, show="headings", height=16)

        col_widths = {
            "Name":    180, "Alias": 140, "Role":   130,
            "Address": 250, "IDN":   260, "Driver": 140, "Status": 120,
        }
        for col in cols:
            self.tree.heading(col, text=col)
            anchor = "center" if col == "Status" else "w"
            self.tree.column(col, width=col_widths[col], anchor=anchor)

        style_treeview_zebra(self.tree)

        vsb = ttk.Scrollbar(table_panel, orient="vertical",
                             command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)
        self.tree.bind("<Double-1>", lambda e: self._edit_alias())

        ttk.Label(
            left,
            text="Tip: Select a device to see details and actions on the right.",
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(6, 0))

        # Right-side details panel
        self.detail_name    = tk.StringVar(value="No device selected")
        self.detail_alias   = tk.StringVar(value="—")
        self.detail_role    = tk.StringVar(value="—")
        self.detail_address = tk.StringVar(value="—")
        self.detail_driver  = tk.StringVar(value="—")
        self.detail_status  = tk.StringVar(value="Idle")

        ttk.Label(right, textvariable=self.detail_name,
                  font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=(0, 8))
        self._detail_status_lbl = ttk.Label(
            right, textvariable=self.detail_status,
            foreground=APP_COLORS["muted"])
        self._detail_status_lbl.pack(anchor="w", pady=(0, 12))

        self._detail_row(right, "Alias",   self.detail_alias)
        self._detail_row(right, "Role",    self.detail_role)
        self._detail_row(right, "Address", self.detail_address, wrap=True)
        self._detail_row(right, "Driver",  self.detail_driver)

        ttk.Separator(right, orient="horizontal").pack(fill="x", pady=12)

        ttk.Button(right, text="Reconnect Selected",
                   command=self._reconnect_selected,
                   style="Primary.TButton").pack(fill="x", pady=4)
        ttk.Button(right, text="Self-Test Selected",
                   command=self._self_test_selected).pack(fill="x", pady=4)
        ttk.Button(right, text="Reset Selected",
                   command=self._reset_selected).pack(fill="x", pady=4)
        ttk.Button(right, text="Edit Alias",
                   command=self._edit_alias).pack(fill="x", pady=4)

        self.status_lbl = ttk.Label(self, text="Status: Ready",
                                     foreground=APP_COLORS["muted"])
        self.status_lbl.pack(anchor="w", padx=12, pady=(0, 12))

    def _detail_row(self, parent, label: str,
                    var: tk.StringVar, wrap: bool = False):
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=4)
        ttk.Label(row, text=f"{label}:",
                  font=("Segoe UI", 9, "bold"),
                  width=10).pack(side="left", anchor="n")
        ttk.Label(
            row, textvariable=var,
            foreground=APP_COLORS["text"],
            wraplength=280 if wrap else 0,
            justify="left",
        ).pack(side="left", fill="x", expand=True)

    # ── Populate table ─────────────────────────────────────────
    def _populate_devices(self):
        self.tree.delete(*self.tree.get_children())
        for i, inst in enumerate(COMPANY_INSTRUMENTS):
            alias = self._alias_map.get(inst["name"], "")
            self.tree.insert(
                "", "end", iid=inst["name"],
                values=(
                    inst["name"], alias, inst["role"],
                    inst["address"], "", "", "Not Connected",
                ),
                tags=("even" if i % 2 else "odd",),
            )
        apply_zebra_tags(self.tree)
        self._notify_driver_update()

    # ── Selection helpers ──────────────────────────────────────
    def _get_selected_item_id(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showwarning("No Selection", "Select a device first.")
            return None
        return sel[0]

    def _get_selected_item_id_silent(self):
        sel = self.tree.selection()
        return sel[0] if sel else None

    def _on_tree_select(self, _event=None):
        item_id = self._get_selected_item_id_silent()
        if not item_id:
            return
        vals = self.tree.item(item_id, "values")
        self.detail_name.set(vals[0])
        self.detail_alias.set(vals[1] or "—")
        self.detail_role.set(vals[2])
        self.detail_address.set(vals[3])
        self.detail_driver.set(vals[5] or "—")
        self.detail_status.set(vals[6] or "Idle")

        tone        = "muted"
        status_text = (vals[6] or "").lower()
        if "connected" in status_text or "ok" in status_text:
            tone = "success"
        elif "fail" in status_text or "error" in status_text:
            tone = "danger"
        elif "not connected" in status_text:
            tone = "warning"
        set_status_label(self._detail_status_lbl, vals[6] or "Idle", tone)

    def _find_company_instrument(self, name: str):
        for inst in COMPANY_INSTRUMENTS:
            if inst["name"] == name:
                return inst
        return None

    # ── Connect / reconnect ────────────────────────────────────
    def _connect_all(self):
        connected = failed = 0
        for inst in COMPANY_INSTRUMENTS:
            if self._connect_one(inst["name"], silent=True):
                connected += 1
            else:
                failed += 1
        tone = "success" if failed == 0 else "warning"
        set_status_label(
            self.status_lbl,
            f"Status: Connected {connected} device(s), {failed} issue(s)",
            tone,
        )

    def _reconnect_selected(self):
        item_id = self._get_selected_item_id()
        if not item_id:
            return
        ok = self._connect_one(item_id, silent=False)
        if ok:
            self._on_tree_select()

    def _connect_one(self, name: str, silent: bool = False):
        inst = self._find_company_instrument(name)
        if not inst:
            if not silent:
                messagebox.showerror("Missing Device",
                                     f"No config found for {name}.")
            return False
        try:
            drv         = load_driver(inst["address"])
            self._driver_registry[inst["name"]] = drv
            driver_name = drv.__class__.__name__
            idn         = ""
            try:
                if hasattr(drv, "query"):
                    idn = drv.query("*IDN?").strip()
                elif hasattr(drv, "_inst"):
                    idn = drv._inst.query("*IDN?").strip()
            except Exception:
                idn = "(connected)"

            vals       = list(self.tree.item(inst["name"], "values"))
            vals[4]    = idn
            vals[5]    = driver_name
            vals[6]    = "Connected"
            self.tree.item(inst["name"], values=vals, tags=("status_ok",))
            apply_zebra_tags(self.tree)
            _logger.info(f"Connected: {inst['name']} @ {inst['address']}")
            self._notify_driver_update()
            return True

        except Exception as e:
            vals    = list(self.tree.item(inst["name"], "values"))
            vals[4] = vals[5] = ""
            vals[6] = "Connect Error"
            self.tree.item(inst["name"], values=vals, tags=("status_err",))
            apply_zebra_tags(self.tree)
            _logger.error(f"Connect failed for {inst['name']}: {e}")
            if not silent:
                messagebox.showerror("Connection Error",
                                     f"{inst['name']}:\n{e}")
            self._notify_driver_update()
            return False

    # ── Alias editing ──────────────────────────────────────────
    def _edit_alias(self):
        item_id = self._get_selected_item_id()
        if not item_id:
            return
        vals          = self.tree.item(item_id, "values")
        name          = vals[0]
        current_alias = vals[1]

        dialog = tk.Toplevel(self)
        dialog.title("Edit Alias")
        dialog.resizable(False, False)
        dialog.grab_set()

        ttk.Label(dialog, text=name,
                  font=("Segoe UI", 10, "bold")).grid(
                  row=0, column=0, columnspan=2, padx=12, pady=(12, 4))
        ttk.Label(dialog, text="Alias:").grid(
            row=1, column=0, padx=10, sticky="e")
        alias_var = tk.StringVar(value=current_alias)
        ttk.Entry(dialog, textvariable=alias_var, width=28).grid(
            row=1, column=1, padx=10, pady=8)
        ttk.Label(
            dialog,
            text="Alias is a friendly label only.\n"
                 "The registry key stays the same.",
            foreground=APP_COLORS["muted"], justify="left",
        ).grid(row=2, column=0, columnspan=2, padx=12, pady=4)

        def apply():
            alias = alias_var.get().strip()
            self._alias_map[name] = alias
            self._save_aliases()
            new_vals    = list(vals)
            new_vals[1] = alias
            self.tree.item(item_id, values=new_vals)
            _logger.info(f"Alias set: {name} → '{alias}'")
            self._on_tree_select()
            dialog.destroy()

        def clear_alias():
            self._alias_map.pop(name, None)
            self._save_aliases()
            new_vals    = list(vals)
            new_vals[1] = ""
            self.tree.item(item_id, values=new_vals)
            _logger.info(f"Alias cleared for {name}")
            self._on_tree_select()
            dialog.destroy()

        ttk.Button(dialog, text="Apply",
                   command=apply,
                   style="Primary.TButton").grid(
                   row=3, column=0, pady=10, padx=10)
        ttk.Button(dialog, text="Clear Alias",
                   command=clear_alias).grid(
                   row=3, column=1, pady=10, padx=10)

    # ── Self-test ──────────────────────────────────────────────
    def _self_test_selected(self):
        item_id = self._get_selected_item_id()
        if not item_id:
            return
        vals = self.tree.item(item_id, "values")
        name = vals[0]
        drv  = self._driver_registry.get(name)
        if drv is None:
            messagebox.showerror("Not Connected",
                                 f"{name} is not connected.")
            return
        try:
            result = drv._inst.query("*TST?").strip()
            if result == "0":
                msg  = f"{name} self-test PASSED (result: {result})"
                self._set_row_status(item_id, vals, "Self-Test OK", "ok")
                messagebox.showinfo("Self-Test Passed", msg)
            else:
                msg  = f"{name} self-test FAILED (result: {result})"
                self._set_row_status(
                    item_id, vals, f"Self-Test FAIL ({result})", "err")
                messagebox.showwarning("Self-Test Failed", msg)
            set_status_label(self.status_lbl, f"Status: {msg}", "info")
            _logger.info(msg)
            self._on_tree_select()
        except Exception as e:
            messagebox.showerror("Self-Test Error", f"{name}:\n{e}")
            _logger.error(f"Self-test error for {name}: {e}")

    # ── Reset ──────────────────────────────────────────────────
    def _reset_selected(self):
        item_id = self._get_selected_item_id()
        if not item_id:
            return
        vals = self.tree.item(item_id, "values")
        name = vals[0]
        drv  = self._driver_registry.get(name)
        if drv is None:
            messagebox.showerror("Not Connected",
                                 f"{name} is not connected.")
            return
        if not messagebox.askyesno(
                "Confirm Reset",
                f"Send *RST to {name}?\n"
                "This resets the instrument to factory defaults."):
            return
        try:
            drv._inst.write("*RST")
            drv._inst.write("*CLS")
            self._set_row_status(item_id, vals, "Reset OK", "ok")
            set_status_label(self.status_lbl,
                             f"Status: {name} reset", "success")
            _logger.info(f"Reset sent to {name}")
            self._on_tree_select()
        except Exception as e:
            messagebox.showerror("Reset Error", f"{name}:\n{e}")
            _logger.error(f"Reset error for {name}: {e}")

    # ── Helpers ────────────────────────────────────────────────
    def _set_row_status(self, item_id, vals, status: str, tone: str = ""):
        new_vals    = list(vals)
        new_vals[6] = status
        tags        = []
        if tone == "ok":   tags.append("status_ok")
        elif tone == "err": tags.append("status_err")
        elif tone == "warn": tags.append("status_warn")
        self.tree.item(item_id, values=new_vals, tags=tuple(tags))
        apply_zebra_tags(self.tree)

    def _clear_list(self):
        self.tree.delete(*self.tree.get_children())
        self._driver_registry.clear()
        set_status_label(self.status_lbl, "Status: Cleared", "muted")
        self._notify_driver_update()

    def _notify_driver_update(self):
        if self._driver_update_callback:
            try:
                self._driver_update_callback(self._driver_registry)
            except Exception as e:
                _logger.warning(f"Driver update callback failed: {e}")
