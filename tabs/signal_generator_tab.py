# tabs/signal_generator_tab.py
import os
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from utils.logger import get_logger
from utils.freq_entry import FreqEntry

_logger = get_logger(__name__)

# Paths on the INSTRUMENT filesystem, queried via MMEM:CAT? over VISA.
INSTRUMENT_ROOTS = ["/var/user", "/user", "/users", "/var/user/waveform"]
WAVEFORM_EXTS    = {".wv", ".iq", ".bin", ".csv"}


class SignalGeneratorTab(ttk.Frame):

    DRIVER_NAME = "RS_SMBV100B"

    def __init__(self, parent, driver_registry: dict):
        super().__init__(parent)
        self._registry = driver_registry
        self._build_ui()

    def set_driver_registry(self, registry: dict):
        self._registry = registry

    def _get_driver(self):
        drv = self._registry.get(self.DRIVER_NAME)
        if drv is None:
            messagebox.showerror(
                "Not Connected",
                f"{self.DRIVER_NAME} not connected.\n"
                "Go to Device Manager and click Connect All.")
        return drv

    # ── UI ──────────────────────────────────────────────────────
    def _build_ui(self):
        ttk.Label(self, text="Signal Generator - R&S SMBV100B",
                  font=("Segoe UI", 14, "bold")).pack(pady=10)

        main = ttk.Frame(self)
        main.pack(fill="both", expand=True, padx=15, pady=5)

        self._build_left(main)
        self._build_right(main)

        self.status_lbl = ttk.Label(self, text="Status: Idle", foreground="gray")
        self.status_lbl.pack(pady=5)

    # ── LEFT: RF Settings ───────────────────────────────────────
    def _build_left(self, parent):
        left = ttk.LabelFrame(parent, text="RF Settings")
        left.pack(side="left", fill="both", expand=True, padx=(0, 10))

        freq_frame = ttk.Frame(left)
        freq_frame.pack(fill="x", padx=10, pady=8)
        ttk.Label(freq_frame, text="Frequency:", width=18, anchor="e").pack(side="left")
        self.freq_fe = FreqEntry(freq_frame, width=14, default_unit="MHz")
        self.freq_fe.pack(side="left", padx=5)

        power_frame = ttk.Frame(left)
        power_frame.pack(fill="x", padx=10, pady=8)
        ttk.Label(power_frame, text="Power Level:", width=18, anchor="e").pack(side="left")
        self.power_var = tk.StringVar(value="")
        ttk.Entry(power_frame, textvariable=self.power_var, width=16).pack(side="left", padx=5)
        ttk.Label(power_frame, text="dBm").pack(side="left")

        mod_frame = ttk.Frame(left)
        mod_frame.pack(fill="x", padx=10, pady=8)
        ttk.Label(mod_frame, text="Modulation:", width=18, anchor="e").pack(side="left")
        self.mod_var = tk.StringVar(value="")
        ttk.Combobox(mod_frame, textvariable=self.mod_var, width=14,
                     values=["None", "AM", "FM", "PM", "IQ", "ARB"],
                     state="readonly").pack(side="left", padx=5)

        ttk.Button(left, text="Apply Settings",
                   command=self._apply_settings).pack(pady=10, padx=10, fill="x")
        ttk.Separator(left, orient="horizontal").pack(fill="x", padx=10, pady=5)

        rf_frame = ttk.Frame(left)
        rf_frame.pack(fill="x", padx=10, pady=8)
        ttk.Label(rf_frame, text="RF Output:", width=18, anchor="e").pack(side="left")
        self.rf_state_var = tk.StringVar(value="OFF")
        self.rf_btn = ttk.Button(rf_frame, text="RF OFF", command=self._toggle_rf)
        self.rf_btn.pack(side="left", padx=5)
        self.rf_status_lbl = ttk.Label(rf_frame, text="RF is OFF", foreground="red")
        self.rf_status_lbl.pack(side="left", padx=10)

        ttk.Separator(left, orient="horizontal").pack(fill="x", padx=10, pady=5)

        preset_frame = ttk.LabelFrame(left, text="Quick Presets")
        preset_frame.pack(fill="x", padx=10, pady=5)
        ttk.Button(preset_frame, text="1 GHz / 0 dBm",
                   command=lambda: self._apply_preset(1e9, 0)).pack(side="left", padx=5, pady=5)
        ttk.Button(preset_frame, text="2.4 GHz / -10 dBm",
                   command=lambda: self._apply_preset(2.4e9, -10)).pack(side="left", padx=5, pady=5)
        ttk.Button(preset_frame, text="5.8 GHz / -20 dBm",
                   command=lambda: self._apply_preset(5.8e9, -20)).pack(side="left", padx=5, pady=5)

    # ── RIGHT: Waveform Management ──────────────────────────────
    def _build_right(self, parent):
        right = ttk.LabelFrame(parent, text="Waveform Management")
        right.pack(side="right", fill="both", expand=True)

        # ── Upload from PC ─────────────────────────────────────
        upload_lf = ttk.LabelFrame(right, text="Upload from This PC")
        upload_lf.pack(fill="x", padx=8, pady=(6, 4))

        upload_row = ttk.Frame(upload_lf)
        upload_row.pack(fill="x", padx=8, pady=6)

        self._upload_path_var = tk.StringVar(value="")
        self._upload_path_entry = ttk.Entry(
            upload_row, textvariable=self._upload_path_var, width=34, state="readonly")
        self._upload_path_entry.pack(side="left", padx=(0, 4), fill="x", expand=True)

        ttk.Button(upload_row, text="Browse…",
                   command=self._upload_browse).pack(side="left", padx=(0, 4))
        ttk.Button(upload_row, text="Upload to Instrument",
                   command=self._upload_from_pc,
                   style="Primary.TButton").pack(side="left")

        self._upload_dest_row = ttk.Frame(upload_lf)
        self._upload_dest_row.pack(fill="x", padx=8, pady=(0, 6))
        ttk.Label(self._upload_dest_row,
                  text="Destination folder on instrument:").pack(side="left", padx=(0, 4))
        self._upload_dest_var = tk.StringVar(value="/var/user/waveform")
        ttk.Entry(self._upload_dest_row,
                  textvariable=self._upload_dest_var,
                  width=26).pack(side="left")

        # ── Instrument file browser ─────────────────────────────
        fb_lf = ttk.LabelFrame(right, text="Browse Instrument Files (via VISA)")
        fb_lf.pack(fill="both", expand=True, padx=8, pady=(0, 4))
        fb_lf.rowconfigure(1, weight=1)
        fb_lf.columnconfigure(0, weight=1)

        root_row = ttk.Frame(fb_lf)
        root_row.grid(row=0, column=0, columnspan=2, sticky="ew", padx=6, pady=(4, 2))
        ttk.Label(root_row, text="Instrument path:").pack(side="left", padx=(0, 4))
        self._fb_root_var = tk.StringVar(value=INSTRUMENT_ROOTS[0])
        self._fb_root_cb  = ttk.Combobox(
            root_row, textvariable=self._fb_root_var,
            values=INSTRUMENT_ROOTS, width=22)
        self._fb_root_cb.pack(side="left", padx=(0, 4))
        self._fb_root_cb.bind("<<ComboboxSelected>>", lambda e: self._fb_populate_tree())
        ttk.Button(root_row, text="↺  Browse",
                   command=self._fb_populate_tree).pack(side="left", padx=2)
        ttk.Label(root_row, text="(instrument must be connected)",
                  foreground="gray").pack(side="left", padx=(8, 0))

        tree_frame = ttk.Frame(fb_lf)
        tree_frame.grid(row=1, column=0, sticky="nsew", padx=6, pady=(2, 4))
        tree_frame.rowconfigure(0, weight=1)
        tree_frame.columnconfigure(0, weight=1)

        self._fb_tree = ttk.Treeview(
            tree_frame, columns=("size",), show="tree headings", height=8)
        self._fb_tree.heading("#0",   text="Name", anchor="w")
        self._fb_tree.heading("size", text="Size",  anchor="e")
        self._fb_tree.column("#0",   width=260, anchor="w")
        self._fb_tree.column("size", width=70,  anchor="e")
        fb_vsb = ttk.Scrollbar(tree_frame, orient="vertical",   command=self._fb_tree.yview)
        fb_hsb = ttk.Scrollbar(tree_frame, orient="horizontal", command=self._fb_tree.xview)
        self._fb_tree.configure(yscrollcommand=fb_vsb.set, xscrollcommand=fb_hsb.set)
        self._fb_tree.grid(row=0, column=0, sticky="nsew")
        fb_vsb.grid(row=0, column=1, sticky="ns")
        fb_hsb.grid(row=1, column=0, sticky="ew")

        self._fb_tree.bind("<<TreeviewOpen>>", self._fb_on_expand)
        self._fb_tree.bind("<Double-1>",       self._fb_on_double_click)

        fb_btn = ttk.Frame(fb_lf)
        fb_btn.grid(row=2, column=0, sticky="ew", padx=6, pady=(0, 4))
        ttk.Button(fb_btn, text="Set as Active Waveform",
                   command=self._fb_set_active,
                   style="Primary.TButton").pack(side="left", padx=(0, 4))

        self._fb_selected_path: str = ""
        self._fb_selected_lbl = ttk.Label(fb_lf, text="Selected: (none)", foreground="gray")
        self._fb_selected_lbl.grid(row=3, column=0, sticky="w", padx=6, pady=(0, 4))

        # ── Waveforms on device ────────────────────────────────
        dev_lf = ttk.LabelFrame(right, text="Waveforms on Device (ARB Catalogue)")
        dev_lf.pack(fill="x", padx=8, pady=(0, 6))

        ttk.Button(dev_lf, text="↺  Refresh Waveform List",
                   command=self._refresh_waveforms).pack(fill="x", padx=8, pady=(6, 4))
        self.waveform_list = tk.Listbox(dev_lf, height=5, width=40)
        self.waveform_list.pack(fill="x", padx=8, pady=4)

        wf_btn_frame = ttk.Frame(dev_lf)
        wf_btn_frame.pack(fill="x", padx=8, pady=4)
        ttk.Button(wf_btn_frame, text="Select Waveform",
                   command=self._select_waveform).pack(side="left", padx=5)
        ttk.Button(wf_btn_frame, text="Delete Waveform",
                   command=self._delete_waveform).pack(side="left", padx=5)

        self.selected_wf_lbl = ttk.Label(dev_lf, text="Selected: None", foreground="gray")
        self.selected_wf_lbl.pack(padx=8, pady=(0, 6))

    # ── Upload from PC logic ──────────────────────────────────
    def _upload_browse(self):
        path = filedialog.askopenfilename(
            title="Select waveform file from this PC",
            filetypes=[("Waveform files", "*.wv *.iq *.bin *.csv"),
                       ("All files", "*.*")])
        if path:
            self._upload_path_var.set(os.path.normpath(path))

    def _upload_from_pc(self):
        """Upload a local PC file to the instrument via MMEM:DATA."""
        local_path = self._upload_path_var.get().strip()
        if not local_path or not os.path.isfile(local_path):
            messagebox.showwarning(
                "No File", "Click Browse… to pick a file from this PC first.")
            return

        drv = self._get_driver()
        if drv is None:
            return

        dest_folder = self._upload_dest_var.get().strip().rstrip("/")
        filename    = os.path.basename(local_path)
        dest_path   = f"{dest_folder}/{filename}"

        try:
            # Use the driver's existing upload_waveform but temporarily
            # override its dest path by passing a patched call.
            # The driver already handles the IEEE 488.2 binary block transfer.
            drv.upload_waveform(local_path, dest_override=dest_path)
        except TypeError:
            # Older driver signature without dest_override — fall back
            drv.upload_waveform(local_path)

        self.status_lbl.config(
            text=f"Status: Uploaded {filename} → {dest_path}",
            foreground="green")
        _logger.info(f"SigGen PC upload: {local_path} → {dest_path}")
        self._refresh_waveforms()
        self._fb_populate_tree()

    # ── Instrument file browser logic ───────────────────────────
    def _mmem_cat(self, path: str) -> list[dict]:
        drv = self._registry.get(self.DRIVER_NAME)
        if drv is None or drv._inst is None:
            return []
        try:
            raw = drv._inst.query(f"MMEM:CAT? '{path}'").strip()
        except Exception as e:
            _logger.warning(f"MMEM:CAT? '{path}' failed: {e}")
            return []

        entries = []
        parts   = raw.split(",")
        i = 2
        while i + 2 < len(parts):
            name  = parts[i].strip().strip('"')
            ftype = parts[i + 1].strip().strip('"').upper()
            try:
                size = int(parts[i + 2].strip().strip('"'))
            except ValueError:
                size = 0
            if name:
                entries.append({"name": name, "type": ftype, "size": size})
            i += 3
        return entries

    def _fb_populate_tree(self):
        root = self._fb_root_var.get().strip()
        if not root:
            return
        self._fb_tree.delete(*self._fb_tree.get_children())
        drv = self._registry.get(self.DRIVER_NAME)
        if drv is None:
            self._fb_tree.insert("", "end",
                                  text="⚠  Instrument not connected — connect first",
                                  values=("",))
            return
        self._fb_insert_level("", root)

    def _fb_insert_level(self, parent_iid: str, path: str):
        entries = self._mmem_cat(path)
        if not entries:
            self._fb_tree.insert(parent_iid, "end",
                                  text="(empty or inaccessible)",
                                  values=("",), tags=("placeholder",))
            return

        folders = [e for e in entries if e["type"] == "DIR"]
        files   = [e for e in entries
                   if e["type"] != "DIR"
                   and any(e["name"].lower().endswith(x) for x in WAVEFORM_EXTS)]

        for folder in sorted(folders, key=lambda e: e["name"].lower()):
            full = f"{path.rstrip('/')}/{folder['name']}"
            iid  = self._fb_tree.insert(
                parent_iid, "end", text=folder["name"],
                values=("",), open=False, tags=("dir", full))
            self._fb_tree.insert(iid, "end", text="loading…", tags=("placeholder",))

        for f in sorted(files, key=lambda e: e["name"].lower()):
            full    = f"{path.rstrip('/')}/{f['name']}"
            size_kb = f["size"] // 1024
            self._fb_tree.insert(
                parent_iid, "end", text=f["name"],
                values=(f"{size_kb} KB" if size_kb else "< 1 KB",),
                tags=("file", full))

    def _fb_on_expand(self, event=None):
        iid = self._fb_tree.focus()
        if not iid:
            return
        children = self._fb_tree.get_children(iid)
        if len(children) == 1:
            first_tags = self._fb_tree.item(children[0], "tags")
            if "placeholder" in first_tags:
                full_path = self._fb_path_from_tags(iid)
                if full_path:
                    self._fb_tree.delete(children[0])
                    self._fb_insert_level(iid, full_path)

    def _fb_path_from_tags(self, iid: str) -> str:
        tags = self._fb_tree.item(iid, "tags")
        for tag in tags:
            if tag.startswith("/"):
                return tag
        return ""

    def _fb_on_double_click(self, event=None):
        iid = self._fb_tree.focus()
        if not iid:
            return
        tags = self._fb_tree.item(iid, "tags")
        if "file" in tags:
            path = self._fb_path_from_tags(iid)
            if path:
                self._fb_selected_path = path
                name = path.split("/")[-1]
                self._fb_selected_lbl.config(
                    text=f"Selected: {name}", foreground="#1a5c1a")

    def _fb_set_active(self):
        path = self._fb_selected_path
        if not path:
            iid = self._fb_tree.focus()
            if iid:
                self._fb_on_double_click()
                path = self._fb_selected_path
        if not path:
            messagebox.showwarning(
                "No File", "Double-click a waveform file in the tree first.")
            return
        drv = self._get_driver()
        if drv is None:
            return
        name = path.split("/")[-1]
        try:
            drv.set_waveform(path)
            self.selected_wf_lbl.config(text=f"Selected: {name}", foreground="green")
            self.status_lbl.config(
                text=f"Status: Active waveform → {name}", foreground="green")
            _logger.info(f"SigGen active waveform set: {path}")
        except Exception as e:
            messagebox.showerror("Error", str(e))
            _logger.error(f"SigGen set active waveform failed: {e}")

    # ── Settings ────────────────────────────────────────────────
    def _apply_settings(self):
        drv = self._get_driver()
        if drv is None:
            return
        freq_hz = self.freq_fe.get_hz()
        if freq_hz is None:
            messagebox.showwarning("Missing Values", "Enter a frequency.")
            return
        power_str = self.power_var.get().strip()
        if not power_str:
            messagebox.showwarning("Missing Values", "Enter a power level.")
            return
        try:
            power = float(power_str)
        except ValueError:
            messagebox.showerror("Invalid Input", "Power must be a number.")
            return
        try:
            drv.set_freq(freq_hz)
            drv.set_power(power)
            self.status_lbl.config(
                text=f"Status: Set {freq_hz/1e6:.3f} MHz / {power} dBm",
                foreground="green")
            _logger.info(f"SigGen: freq={freq_hz} Hz, power={power} dBm")
        except Exception as e:
            messagebox.showerror("Hardware Error", str(e))
            _logger.error(f"SigGen apply settings failed: {e}")

    def _apply_preset(self, freq: float, power: float):
        self.freq_fe.set_hz(freq)
        self.power_var.set(str(power))
        self._apply_settings()

    # ── RF toggle ───────────────────────────────────────────────
    def _toggle_rf(self):
        drv = self._get_driver()
        if drv is None:
            return
        new_state = "OFF" if self.rf_state_var.get() == "ON" else "ON"
        try:
            drv.rf_on(new_state == "ON")
            self.rf_state_var.set(new_state)
            self.rf_btn.config(text=f"RF {new_state}")
            color = "green" if new_state == "ON" else "red"
            self.rf_status_lbl.config(text=f"RF is {new_state}", foreground=color)
            self.status_lbl.config(text=f"Status: RF {new_state}", foreground=color)
            _logger.info(f"SigGen RF {new_state}")
        except Exception as e:
            messagebox.showerror("Hardware Error", str(e))
            _logger.error(f"SigGen RF toggle failed: {e}")

    # ── Waveforms on device ─────────────────────────────────────
    def _refresh_waveforms(self):
        drv = self._get_driver()
        if drv is None:
            return
        try:
            waveforms = drv.list_waveforms() if hasattr(drv, "list_waveforms") else []
            self.waveform_list.delete(0, tk.END)
            for wf in waveforms:
                self.waveform_list.insert(tk.END, wf)
            self.status_lbl.config(
                text=f"Status: {len(waveforms)} waveform(s) on device",
                foreground="green")
            _logger.info(f"SigGen waveform list refreshed: {len(waveforms)} items")
        except Exception as e:
            messagebox.showerror("Error", str(e))
            _logger.error(f"SigGen waveform list failed: {e}")

    def _select_waveform(self):
        drv = self._get_driver()
        if drv is None:
            return
        sel = self.waveform_list.curselection()
        if not sel:
            messagebox.showwarning("No Selection", "Select a waveform from the list.")
            return
        wf_name = self.waveform_list.get(sel[0])
        try:
            drv.set_waveform(wf_name)
            self.selected_wf_lbl.config(text=f"Selected: {wf_name}", foreground="green")
            self.status_lbl.config(
                text=f"Status: Waveform set to {wf_name}", foreground="green")
            _logger.info(f"SigGen waveform selected: {wf_name}")
        except Exception as e:
            messagebox.showerror("Error", str(e))
            _logger.error(f"SigGen set waveform failed: {e}")

    def _delete_waveform(self):
        drv = self._get_driver()
        if drv is None:
            return
        sel = self.waveform_list.curselection()
        if not sel:
            messagebox.showwarning("No Selection", "Select a waveform to delete.")
            return
        wf_name = self.waveform_list.get(sel[0])
        if not messagebox.askyesno("Confirm Delete",
                                   f"Delete waveform '{wf_name}' from device?"):
            return
        try:
            if hasattr(drv, "delete_waveform"):
                drv.delete_waveform(wf_name)
            self.waveform_list.delete(sel[0])
            self.status_lbl.config(text=f"Status: Deleted {wf_name}", foreground="gray")
            _logger.info(f"SigGen waveform deleted: {wf_name}")
        except Exception as e:
            messagebox.showerror("Error", str(e))
            _logger.error(f"SigGen delete waveform failed: {e}")

    # ── get_settings / load_settings ────────────────────────────
    def get_settings(self) -> dict:
        return {
            "freq_hz":    self.freq_fe.get_hz(),
            "power_dbm":  self.power_var.get(),
            "modulation": self.mod_var.get(),
            "rf_on":      self.rf_state_var.get() == "ON",
            "waveform":   self.selected_wf_lbl.cget("text").replace("Selected: ", ""),
        }

    def load_settings(self, settings: dict):
        if settings.get("freq_hz"):
            self.freq_fe.set_hz(float(settings["freq_hz"]))
        self.power_var.set(settings.get("power_dbm", ""))
        self.mod_var.set(settings.get("modulation", ""))
        rf = settings.get("rf_on", False)
        self.rf_state_var.set("ON" if rf else "OFF")
        self.selected_wf_lbl.config(
            text=f"Selected: {settings.get('waveform', 'None')}")
