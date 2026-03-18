# tabs/ramp_editor_tab.py - COMPLETE FILE
import tkinter as tk
from tkinter import ttk, messagebox
import json
import os
from utils.logger import get_logger

_logger = get_logger(__name__)

DEFAULT_STEPS = [
    {"label": "Gate Bias",  "supply": "Gate",  "voltage": -6.0, "current": 0.1, "delay_ms": 500},
    {"label": "Drain 0V",   "supply": "Drain", "voltage":  0.0, "current": 1.0, "delay_ms": 500},
    {"label": "Drain 10V",  "supply": "Drain", "voltage": 10.0, "current": 2.0, "delay_ms": 500},
    {"label": "Drain 48V",  "supply": "Drain", "voltage": 48.0, "current": 4.0, "delay_ms": 500},
    {"label": "Gate Final", "supply": "Gate",  "voltage": -3.0, "current": 0.1, "delay_ms": 500},
]

RAMP_FILE = "ramp_steps.json"


class RampEditorTab(ttk.Frame):

    def __init__(self, parent):
        super().__init__(parent)
        self._steps = []
        self._build_ui()
        self._load_from_file()

    def _build_ui(self):
        ttk.Label(self, text="Ramp Step Editor",
                  font=("Segoe UI", 14, "bold")).pack(pady=10)

        ttk.Label(self,
                  text="Define the voltage/current ramp steps the Sequencer will execute. "
                       "Changes are saved to ramp_steps.json and picked up automatically at run time.",
                  foreground="gray", wraplength=900).pack(padx=15)

        table_frame = ttk.LabelFrame(self, text="Ramp Steps")
        table_frame.pack(fill="both", expand=True, padx=15, pady=8)

        cols = ("#", "Label", "Supply Role", "Voltage (V)",
                "Current (A)", "Delay (ms)", "Valid")
        self.tree = ttk.Treeview(table_frame, columns=cols,
                                  show="headings", height=10)
        col_widths = {
            "#": 40, "Label": 180, "Supply Role": 120,
            "Voltage (V)": 110, "Current (A)": 110,
            "Delay (ms)": 100,  "Valid": 80,
        }
        for col in cols:
            self.tree.heading(col, text=col)
            self.tree.column(col, width=col_widths[col], anchor="center")

        self.tree.tag_configure("ok",   background="#e8f5e9")
        self.tree.tag_configure("warn", background="#fff8e1")
        self.tree.tag_configure("err",  background="#ffebee")

        self.tree.pack(fill="both", expand=True, padx=5, pady=5)
        self.tree.bind("<Double-1>", self._on_double_click)

        ttk.Label(table_frame,
                  text="Double-click a row to edit  |  "
                       "✅ OK   ⚠ Warning (safe but unusual)   ❌ Error (will block run)",
                  foreground="gray").pack(pady=2)

        btn_frame = ttk.Frame(self)
        btn_frame.pack(fill="x", padx=15, pady=4)

        ttk.Button(btn_frame, text="Add Step",
                   command=self._add_step).pack(side="left", padx=5)
        ttk.Button(btn_frame, text="Delete Selected",
                   command=self._delete_step).pack(side="left", padx=5)
        ttk.Button(btn_frame, text="Move Up",
                   command=lambda: self._move_step(-1)).pack(side="left", padx=5)
        ttk.Button(btn_frame, text="Move Down",
                   command=lambda: self._move_step(1)).pack(side="left", padx=5)

        ttk.Separator(btn_frame, orient="vertical").pack(
            side="left", fill="y", padx=10)

        ttk.Button(btn_frame, text="Validate All",
                   command=self._validate_and_report).pack(side="left", padx=5)
        ttk.Button(btn_frame, text="Save to File",
                   command=self._save_to_file).pack(side="left", padx=5)
        ttk.Button(btn_frame, text="Reset to Defaults",
                   command=self._reset_defaults).pack(side="left", padx=5)

        self.status_lbl = ttk.Label(self, text="", foreground="gray")
        self.status_lbl.pack(pady=4)

    # ── Tree refresh ───────────────────────────────────────────
    def _refresh_tree(self):
        self.tree.delete(*self.tree.get_children())
        for i, step in enumerate(self._steps, start=1):
            errors, warnings = _validate_step(step, i)
            if errors:
                badge = "❌ Error"
                tag   = "err"
            elif warnings:
                badge = "⚠ Warn"
                tag   = "warn"
            else:
                badge = "✅ OK"
                tag   = "ok"
            self.tree.insert("", "end", iid=str(i - 1), tags=(tag,),
                             values=(
                                 i,
                                 step.get("label", ""),
                                 step.get("supply", ""),
                                 step.get("voltage", 0),
                                 step.get("current", 0),
                                 step.get("delay_ms", 500),
                                 badge,
                             ))

    # ── Edit dialog ────────────────────────────────────────────
    def _on_double_click(self, event):
        sel = self.tree.selection()
        if sel:
            self._open_edit_dialog(int(sel[0]))

    def _open_edit_dialog(self, idx: int):
        step   = self._steps[idx]
        dialog = tk.Toplevel(self)
        dialog.title(f"Edit Step {idx + 1}")
        dialog.grab_set()
        dialog.resizable(False, False)

        fields = [
            ("Label",       "label",    str),
            ("Supply Role", "supply",   str),
            ("Voltage (V)", "voltage",  float),
            ("Current (A)", "current",  float),
            ("Delay (ms)",  "delay_ms", int),
        ]

        vars_ = {}
        for row_idx, (label, key, cast) in enumerate(fields):
            ttk.Label(dialog, text=label + ":").grid(
                row=row_idx, column=0, padx=12, pady=6, sticky="e")
            if key == "supply":
                var = tk.StringVar(value=step.get(key, "Drain"))
                ttk.Combobox(dialog, textvariable=var, state="readonly",
                             values=["Gate", "Drain"], width=16).grid(
                             row=row_idx, column=1, padx=10, pady=6)
            else:
                var = tk.StringVar(value=str(step.get(key, "")))
                ttk.Entry(dialog, textvariable=var, width=18).grid(
                          row=row_idx, column=1, padx=10, pady=6)
            vars_[key] = (var, cast)

        hint_lbl = ttk.Label(dialog, text="", foreground="orange",
                             wraplength=280)
        hint_lbl.grid(row=len(fields), column=0, columnspan=2,
                      padx=12, pady=(0, 4))

        def _check_live(*_):
            try:
                preview = {k: cast(v.get()) for k, (v, cast) in vars_.items()}
            except ValueError:
                hint_lbl.config(text="⚠ Non-numeric value", foreground="red")
                return
            errors, warnings = _validate_step(preview, idx + 1)
            if errors:
                hint_lbl.config(
                    text="❌ " + "  |  ".join(errors), foreground="red")
            elif warnings:
                hint_lbl.config(
                    text="⚠ " + "  |  ".join(warnings), foreground="orange")
            else:
                hint_lbl.config(text="✅ Looks good", foreground="green")

        for key, (var, _) in vars_.items():
            var.trace_add("write", _check_live)
        _check_live()

        def apply():
            try:
                updated = {k: cast(v.get())
                           for k, (v, cast) in vars_.items()}
            except ValueError as e:
                messagebox.showerror("Invalid Input", str(e), parent=dialog)
                return
            errors, _ = _validate_step(updated, idx + 1)
            if errors:
                if not messagebox.askyesno(
                        "Validation Errors",
                        "This step has errors that will block the sequencer:\n\n"
                        + "\n".join(f"• {e}" for e in errors)
                        + "\n\nSave anyway?",
                        parent=dialog):
                    return
            self._steps[idx] = updated
            self._refresh_tree()
            self._set_status("Step updated — remember to Save to File.")
            dialog.destroy()

        ttk.Button(dialog, text="Apply", command=apply).grid(
                   row=len(fields) + 1, column=0, columnspan=2, pady=10)

    # ── Step management ────────────────────────────────────────
    def _add_step(self):
        self._steps.append(
            {"label": "", "supply": "Drain",
             "voltage": 0.0, "current": 0.0, "delay_ms": 500}
        )
        self._refresh_tree()
        self._open_edit_dialog(len(self._steps) - 1)

    def _delete_step(self):
        sel = self.tree.selection()
        if not sel:
            return
        idx = int(sel[0])
        if messagebox.askyesno(
                "Delete Step",
                f"Delete step {idx + 1}: "
                f"{self._steps[idx].get('label', '')}?"):
            self._steps.pop(idx)
            self._refresh_tree()
            self._set_status("Step deleted.")

    def _move_step(self, direction: int):
        sel = self.tree.selection()
        if not sel:
            return
        idx     = int(sel[0])
        new_idx = idx + direction
        if 0 <= new_idx < len(self._steps):
            self._steps[idx], self._steps[new_idx] = \
                self._steps[new_idx], self._steps[idx]
            self._refresh_tree()
            self.tree.selection_set(str(new_idx))

    # ── File I/O ───────────────────────────────────────────────
    def _save_to_file(self):
        errors_found = self.validate_steps()
        if errors_found:
            if not messagebox.askyesno(
                    "Validation Errors",
                    f"{len(errors_found)} error(s) found:\n\n"
                    + "\n".join(f"• {e}" for e in errors_found)
                    + "\n\nSave anyway?"):
                return
        try:
            with open(RAMP_FILE, "w") as f:
                json.dump(self._steps, f, indent=2)
            self._set_status(
                f"Saved {len(self._steps)} steps to {RAMP_FILE}", "green")
            _logger.info(f"Ramp steps saved to {RAMP_FILE}")
        except Exception as e:
            messagebox.showerror("Save Error", str(e))
            _logger.error(f"Failed to save ramp steps: {e}")

    def _load_from_file(self):
        if os.path.exists(RAMP_FILE):
            try:
                with open(RAMP_FILE, "r") as f:
                    self._steps = json.load(f)
                self._refresh_tree()
                self._set_status(
                    f"Loaded {len(self._steps)} steps from {RAMP_FILE}")
                _logger.info(f"Ramp steps loaded from {RAMP_FILE}")
                return
            except Exception as e:
                _logger.warning(f"Could not load {RAMP_FILE}: {e}")
        self._reset_defaults(silent=True)

    def _reset_defaults(self, silent=False):
        if not silent and not messagebox.askyesno(
                "Reset", "Reset all steps to defaults?"):
            return
        self._steps = [dict(s) for s in DEFAULT_STEPS]
        self._refresh_tree()
        self._set_status("Reset to default ramp steps.")

    def _set_status(self, msg: str, color: str = "gray"):
        self.status_lbl.config(text=msg, foreground=color)

    # ── Validation ─────────────────────────────────────────────
    def _validate_and_report(self):
        errors = self.validate_steps()
        if not errors:
            messagebox.showinfo("Validation Passed",
                                f"All {len(self._steps)} steps are valid ✅")
            self._set_status("All steps valid.", "green")
        else:
            messagebox.showwarning(
                "Validation Issues",
                f"{len(errors)} issue(s) found:\n\n"
                + "\n".join(f"• {e}" for e in errors))
            self._set_status(
                f"{len(errors)} issue(s) — see Validate All report.", "red")

    def validate_steps(self) -> list:
        """
        Public method — called by SequencerTab before run.
        Returns a flat list of error strings.
        Warnings are NOT included — they won't block the run.
        Returns [] if everything is clean.
        """
        all_errors = []
        for i, step in enumerate(self._steps, start=1):
            errors, _ = _validate_step(step, i)
            all_errors.extend(errors)
        return all_errors

    def get_steps(self) -> list:
        """Returns raw steps as stored internally."""
        return list(self._steps)

    def get_ramp_steps(self) -> list:
        """
        Called by the run engine at runtime.
        Converts internal step format to engine-friendly dict:
          supply  → "Gate" or "Drain"
          voltage → float (V)
          current → float (A)
          dwell   → float (seconds, converted from delay_ms)
          label   → str
        """
        return [
            {
                "supply":  step.get("supply", "Drain"),
                "voltage": step.get("voltage", 0.0),
                "current": step.get("current", 0.0),
                "dwell":   step.get("delay_ms", 500) / 1000.0,
                "label":   step.get("label", ""),
            }
            for step in self._steps
        ]


# ── Step validation logic (module-level, testable independently) ───
def _validate_step(step: dict, step_num: int) -> tuple:
    """
    Validate a single ramp step dict.

    Returns:
        (errors, warnings)
        errors   — list of strings that WILL block the sequencer
        warnings — list of strings that are unusual but safe
    """
    errors   = []
    warnings = []

    label   = step.get("label", "")
    supply  = step.get("supply", "")
    voltage = step.get("voltage", None)
    current = step.get("current", None)
    delay   = step.get("delay_ms", None)

    if not str(label).strip():
        warnings.append(f"Step {step_num}: No label set")

    if supply not in ("Gate", "Drain"):
        errors.append(
            f"Step {step_num}: Supply must be 'Gate' or 'Drain', got '{supply}'")

    try:
        v = float(voltage)
        if supply == "Gate" and v > 0:
            warnings.append(
                f"Step {step_num}: Gate voltage {v} V is positive "
                f"(GaN gate should be ≤ 0 V)")
        if supply == "Drain" and v < 0:
            warnings.append(
                f"Step {step_num}: Drain voltage {v} V is negative")
        if supply == "Drain" and v > 60:
            errors.append(
                f"Step {step_num}: Drain voltage {v} V exceeds 60 V safety limit")
    except (TypeError, ValueError):
        errors.append(f"Step {step_num}: Voltage is not a valid number")

    try:
        a = float(current)
        if a < 0:
            errors.append(
                f"Step {step_num}: Current {a} A cannot be negative")
        if a == 0:
            warnings.append(
                f"Step {step_num}: Current limit is 0 A — output will trip immediately")
        if supply == "Drain" and a > 10:
            warnings.append(
                f"Step {step_num}: Drain current {a} A is unusually high (> 10 A)")
    except (TypeError, ValueError):
        errors.append(f"Step {step_num}: Current is not a valid number")

    try:
        d = int(delay)
        if d < 0:
            errors.append(f"Step {step_num}: Delay {d} ms cannot be negative")
        if d == 0:
            warnings.append(
                f"Step {step_num}: Delay is 0 ms — no settling time")
        if d > 30000:
            warnings.append(
                f"Step {step_num}: Delay {d} ms is very long (> 30 s)")
    except (TypeError, ValueError):
        errors.append(f"Step {step_num}: Delay is not a valid integer")

    return errors, warnings
