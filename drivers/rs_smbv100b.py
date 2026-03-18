# drivers/rs_smbv100b.py
"""
Driver for Rohde & Schwarz SMBV100B signal generator.
"""

import os
from utils.visa_manager import get_visa_rm
from utils.logger import get_logger

WAVEFORM_DIR = "/var/user/waveform"


class RSSMBV100B:
    def __init__(self, visa_address: str, name: str = ""):
        self._logger       = get_logger(__name__)
        self._visa_address = visa_address
        self._name         = name or visa_address
        self._inst         = None

    def connect(self):
        rm = get_visa_rm()
        self._inst         = rm.open_resource(self._visa_address)
        self._inst.timeout = 10000
        try:
            self._inst.write("*RST")
            idn = self._inst.query("*IDN?").strip()
        except Exception:
            idn = "IDN failed"
        self._logger.info(f"Connected SMBV100B '{self._name}' at {self._visa_address}: {idn}")

    def close(self):
        if self._inst is None:
            return
        try:
            self.rf_on(False)
            self._inst.close()
            self._logger.info(f"Disconnected SMBV100B '{self._name}' at {self._visa_address}")
        finally:
            self._inst = None

    def idn(self) -> str:
        if self._inst is None:
            return "Not connected"
        try:
            return self._inst.query("*IDN?").strip()
        except Exception:
            return "IDN query failed"

    def set_freq(self, freq_hz: float):
        self._inst.write(f"SOUR:FREQ {freq_hz}")
        self._logger.info(f"{self._name} frequency set to {freq_hz} Hz")

    def set_power(self, level_dbm: float):
        self._inst.write(f"SOUR:POW:LEV:IMM:AMPL {level_dbm}")
        self._logger.info(f"{self._name} power set to {level_dbm} dBm")

    def rf_on(self, enable: bool):
        state = "ON" if enable else "OFF"
        self._inst.write(f"OUTP:STAT {state}")
        self._logger.info(f"{self._name} RF {state}")

    def list_waveforms(self) -> list:
        try:
            raw = self._inst.query("SOUR:BB:ARB:WAV:CAT?").strip()
            if raw:
                names = [n.strip().strip('"') for n in raw.split(",") if n.strip()]
                return [n for n in names if n]
        except Exception as e:
            self._logger.warning(f"{self._name} ARB CAT query failed, trying MMEM: {e}")
        try:
            raw   = self._inst.query(f"MMEM:CAT? '{WAVEFORM_DIR}'").strip()
            names = []
            parts = raw.split(",")
            i = 2
            while i < len(parts):
                entry = parts[i].strip().strip('"')
                if entry.lower().endswith((".wv", ".iq", ".bin")):
                    names.append(entry)
                i += 3
            return names
        except Exception as e:
            self._logger.error(f"{self._name} list_waveforms failed: {e}")
            return []

    def set_waveform(self, name: str):
        path = name if name.startswith("/") else f"{WAVEFORM_DIR}/{name}"
        self._inst.write(f'SOUR:BB:ARB:WAV:SEL "{path}"')
        self._inst.write("SOUR:BB:ARB:STAT ON")
        self._logger.info(f"{self._name} waveform selected: {path}")

    def upload_waveform(self, filepath: str):
        filename = os.path.basename(filepath)
        dest     = f"{WAVEFORM_DIR}/{filename}"
        with open(filepath, "rb") as f:
            data = f.read()
        length_str  = str(len(data))
        header      = f"#{len(length_str)}{length_str}".encode()
        cmd_prefix  = f'MMEM:DATA "{dest}",'.encode()
        old_timeout         = self._inst.timeout
        self._inst.timeout  = 30000
        try:
            self._inst.write_raw(cmd_prefix + header + data)
            self._inst.query("*OPC?")
            self._logger.info(f"{self._name} uploaded '{filename}' -> '{dest}' ({len(data)} bytes)")
        finally:
            self._inst.timeout = old_timeout

    def delete_waveform(self, name: str):
        path = name if name.startswith("/") else f"{WAVEFORM_DIR}/{name}"
        self._inst.write(f'MMEM:DEL "{path}"')
        self._logger.info(f"{self._name} deleted waveform: {path}")

    def get_freq_axis(self) -> list:
        try:
            center = float(self._inst.query("SOUR:FREQ?").strip())
            return [center]
        except Exception:
            return []
