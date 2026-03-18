# tabs/device_info_tab.py
import tkinter as tk
from tkinter import ttk, messagebox
import threading
import json
import os
from utils.logger import get_logger
from utils.visa_helper import discover_instruments, load_driver, find_driver, get_visa_rm
from utils.ui_theme import (
    APP_COLORS,
    apply_zebra_tags,
    make_header,
    set_status_label,
    style_treeview_zebra,
)

_logger = get_logger(__name__)

ALIASES_FILE = "instrument_aliases.json"

# Role is inferred from the driver class name at connect-time
_CLASS_ROLE_MAP = {
    "KeysightE36xxSupply":  "Power Supply",
    "AgilentE3648ASupply":  "Power Supply",
    "HP6633BSupply":        "Power Supply",
    "Keysight3446xDMM":     "DMM",
    "PXAN9030A":            "Spectrum Analyzer",
    "RSSMBV100B":           "Signal Generator",
}


class DeviceInfoTab(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        self.configure(style="TFrame")

        self._driver_update_callback = None
        self._driver_registry        = {}
        self._alias_map              = self._load_aliases()
        self._scanning               = False

        self._build_ui()

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
            "Auto-discover instruments via VISA, verify communication, and manage aliases.",
        )

        top_shell = ttk.Frame(self)
        top_shell.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        content = ttk.Frame(top_shell)
        content.pack(fill="both", expand=True)

        left = ttk.Frame(content)
        left.pack(side="left", fill="both", expand=True, padx=(0, 8))

        right = ttk.LabelFrame(content, text="Selected Device",
                               style="Card.TLabelframe")
        right.pack(side="right", fill="y")
        right.configure(padding=12)

        # ── Toolbar ────────────────────────────────────────────
        toolbar = ttk.Frame(left, style="Panel.TFrame")
        toolbar.pack(fill="x", pady=(0, 8))
        toolbar.configure(padding=10)

        self.scan_btn = ttk.Button(
            toolbar, text="Scan & Connect All",
            command=self._start_scan,
            style="Primary.TButton")
        self.scan_btn.pack(side="left", padx=(0, 8))

        ttk.Button(toolbar, text="Reconnect Selected",
                   command=self._reconnect_selected).pack(side="left", padx=4)
        ttk.Button(toolbar, text="Self-Test",
                   command=self._self_test_selected).pack(side="left", padx=4)
        ttk.Button(toolbar, text="Reset",
                   command=self._reset_selected).pack(side="left", padx=4)
        ttk.Button(toolbar, text="Edit Alias",
                   command=self._edit_alias).pack(side="left", padx=4)
        ttk.Button(toolbar, text="Add Manual",
                   command=self._add_manual).pack(side="left", padx=4)
        ttk.Button(toolbar, text="Clear List",
                   command=self._clear_list).pack(side="left", padx=4)

        # ── Table ──────────────────────────────────────────────
        table_panel = ttk.Frame(left, style="Panel.TFrame")
        table_panel.pack(fill="both", expand=True)
        table_panel.configure(padding=10)

        cols = ("Name", "Alias", "Role", "Address", "IDN", "Driver", "Status")
        self.tree = ttk.Treeview(
            table_panel, columns=cols, show="headings", height=16)

        col_widths = {
            "Name":    180, "Alias": 140, "Role":   130,
            "Address": 250, "IDN":   260, "Driver": 160, "Status": 130,
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
            text="Tip: Click 'Scan & Connect All' to auto-discover all VISA instruments.  "
                 "Use 'Add Manual' to force-add a custom address.",
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(6, 0))

        # ── Right detail panel ─────────────────────────────────
        self.detail_name    = tk.StringVar(value="No device selected")
        self.detail_alias   = tk.StringVar(value="\u2014")
        self.detail_role    = tk.StringVar(value="\u2014")
        self.detail_address = tk.StringVar(value="\u2014")
        self.detail_driver  = tk.StringVar(value="\u2014")
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

        self.status_lbl = ttk.Label(self, text="Status: Ready — click Scan & Connect All",
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

    # ── Auto-discovery (threaded) ──────────────────────────────
    def _start_scan(self):
        if self._scanning:
            return
        self._scanning = True
        self.scan_btn.config(text="Scanning...", state="disabled")
        set_status_label(self.status_lbl,
                         "Status: Scanning VISA bus — please wait...", "info")
        self.tree.delete(*self.tree.get_children())
        threading.Thread(target=self._scan_worker, daemon=True).start()

    def _scan_worker(self):
        """Runs on a background thread — calls discover_instruments()."""
        try:
            registry = discover_instruments(timeout_ms=2000)
        except Exception as e:
            _logger.error(f"Discovery failed: {e}")
            registry = {}
        # Hand results back to the Tk main thread
        self.after(0, lambda: self._scan_done(registry))

    def _scan_done(self, registry: dict):
        """Called on the main thread after discovery finishes."""
        self._scanning = False
        self.scan_btn.config(text="Scan & Connect All", state="normal")

        # Merge newly discovered drivers into the registry,
        # preserving any manually-added entries already there.
        self._driver_registry.update(registry)

        self.tree.delete(*self.tree.get_children())
        for i, (name, drv) in enumerate(self._driver_registry.items()):
            self._insert_row(i, name, drv)

        apply_zebra_tags(self.tree)

        n = len(registry)
        tone = "success" if n > 0 else "warning"
        set_status_label(
            self.status_lbl,
            f"Status: Scan complete — {n} instrument(s) found",
            tone,
        )
        _logger.info(f"Scan complete: {n} instrument(s)")
        self._notify_driver_update()

    def _insert_row(self, index: int, name: str, drv):
        """Insert or refresh one row in the tree from a live driver object."""
        alias       = self._alias_map.get(name, "")
        driver_name = drv.__class__.__name__
        role        = _CLASS_ROLE_MAP.get(driver_name, "Unknown")
        address     = getattr(drv, "_address", "") or getattr(drv, "address", "")

        # Try to get IDN from the live instrument
        idn = ""
        try:
            if hasattr(drv, "_inst") and drv._inst:
                idn = drv._inst.query("*IDN?").strip()
            elif hasattr(drv, "query"):
                idn = drv.query("*IDN?").strip()
        except Exception:
            idn = "(connected)"

        tag = "even" if index % 2 else "odd"
        self.tree.insert(
            "", "end", iid=name,
            values=(name, alias, role, address, idn, driver_name, "Connected"),
            tags=(tag,),
        )

    # ── Manual add ─────────────────────────────────────────────
    def _add_manual(self):
        dialog = tk.Toplevel(self)
        dialog.title("Add Instrument Manually")
        dialog.resizable(False, False)
        dialog.grab_set()

        ttk.Label(dialog, text="VISA Address:",
                  font=("Segoe UI", 10, "bold")).grid(
                  row=0, column=0, padx=12, pady=(14, 4), sticky="e")
        addr_var = tk.StringVar(value="GPIB0::XX::INSTR")
        ttk.Entry(dialog, textvariable=addr_var, width=36).grid(
            row=0, column=1, padx=10, pady=(14, 4))

        ttk.Label(dialog,
                  text="Enter the full VISA resource string.\n"
                       "e.g.  GPIB0::15::INSTR  or  USB0::0x2A8D::0x3402::MY61002290::INSTR",
                  foreground=APP_COLORS["muted"], justify="left").grid(
                  row=1, column=0, columnspan=2, padx=12, pady=(0, 8))

        def connect():
            addr = addr_var.get().strip()
            if not addr:
                messagebox.showwarning("Missing Address",
                                       "Enter a VISA address.", parent=dialog)
                return
            dialog.destroy()
            self._connect_manual(addr)

        ttk.Button(dialog, text="Connect",
                   command=connect,
                   style="Primary.TButton").grid(
                   row=2, column=0, columnspan=2, pady=12)

    def _connect_manual(self, addr: str):
        set_status_label(self.status_lbl,
                         f"Status: Connecting to {addr}...", "info")
        try:
            drv = load_driver(addr)
            drv.connect()
        except Exception as e:
            messagebox.showerror("Connection Error", f"{addr}:\n{e}")
            set_status_label(self.status_lbl,
                             f"Status: Failed to connect {addr}", "danger")
            _logger.error(f"Manual connect failed for {addr}: {e}")
            return

        # Build registry name from IDN
        from utils.visa_helper import _make_registry_name
        idn = "(unknown)"
        try:
            if hasattr(drv, "_inst") and drv._inst:
                idn = drv._inst.query("*IDN?").strip()
        except Exception:
            pass

        name = _make_registry_name(idn, addr)
        base, counter = name, 2
        while name in self._driver_registry:
            name = f"{base}_{counter}"
            counter += 1

        self._driver_registry[name] = drv

        # Insert row if not already in tree
        existing = [self.tree.item(i, "values")[0]
                    for i in self.tree.get_children()]
        if name not in existing:
            idx = len(self.tree.get_children())
            self._insert_row(idx, name, drv)
            apply_zebra_tags(self.tree)

        set_status_label(self.status_lbl,
                         f"Status: Manually connected '{name}'", "success")
        _logger.info(f"Manual connect: '{name}' @ {addr}")
        self._notify_driver_update()

    # ── Reconnect selected ─────────────────────────────────────
    def _reconnect_selected(self):
        item_id = self._get_selected_item_id()
        if not item_id:
            return
        vals    = self.tree.item(item_id, "values")
        address = vals[3]
        if not address:
            messagebox.showerror("No Address",
                                 "No VISA address stored for this device.")
            return
        set_status_label(self.status_lbl,
                         f"Status: Reconnecting {item_id}...", "info")
        try:
            drv = load_driver(address)
            drv.connect()
            self._driver_registry[item_id] = drv

            idn = ""
            try:
                if hasattr(drv, "_inst") and drv._inst:
                    idn = drv._inst.query("*IDN?").strip()
            except Exception:
                idn = "(connected)"

            new_vals    = list(vals)
            new_vals[4] = idn
            new_vals[5] = drv.__class__.__name__
            new_vals[6] = "Connected"
            self.tree.item(item_id, values=new_vals, tags=("status_ok",))
            apply_zebra_tags(self.tree)
            self._on_tree_select()
            set_status_label(self.status_lbl,
                             f"Status: Reconnected '{item_id}'", "success")
            _logger.info(f"Reconnected: {item_id} @ {address}")
            self._notify_driver_update()
        except Exception as e:
            new_vals    = list(vals)
            new_vals[6] = "Connect Error"
            self.tree.item(item_id, values=new_vals, tags=("status_err",))
            apply_zebra_tags(self.tree)
            set_status_label(self.status_lbl,
                             f"Status: Reconnect failed — {item_id}", "danger")
            messagebox.showerror("Connection Error", f"{item_id}:\n{e}")
            _logger.error(f"Reconnect failed for {item_id}: {e}")
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
        self.detail_alias.set(vals[1] or "\u2014")
        self.detail_role.set(vals[2])
        self.detail_address.set(vals[3])
        self.detail_driver.set(vals[5] or "\u2014")
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
            text="Alias is a friendly label only.\nThe registry key stays the same.",
            foreground=APP_COLORS["muted"], justify="left",
        ).grid(row=2, column=0, columnspan=2, padx=12, pady=4)

        def apply():
            alias = alias_var.get().strip()
            self._alias_map[name] = alias
            self._save_aliases()
            new_vals    = list(vals)
            new_vals[1] = alias
            self.tree.item(item_id, values=new_vals)
            _logger.info(f"Alias set: {name} -> '{alias}'")
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
            messagebox.showerror("Not Connected", f"{name} is not connected.")
            return
        try:
            result = drv._inst.query("*TST?").strip()
            if result == "0":
                msg = f"{name} self-test PASSED (result: {result})"
                self._set_row_status(item_id, vals, "Self-Test OK", "ok")
                messagebox.showinfo("Self-Test Passed", msg)
            else:
                msg = f"{name} self-test FAILED (result: {result})"
                self._set_row_status(item_id, vals, f"Self-Test FAIL ({result})", "err")
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
            messagebox.showerror("Not Connected", f"{name} is not connected.")
            return
        if not messagebox.askyesno(
                "Confirm Reset",
                f"Send *RST to {name}?\nThis resets the instrument to factory defaults."):
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
        if tone == "ok":    tags.append("status_ok")
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
