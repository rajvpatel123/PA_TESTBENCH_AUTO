# drivers/keysight_3446x_dmm.py
"""
Driver for Keysight 34465A / 34461A DMMs.
"""

from utils.visa_manager import get_visa_rm
from utils.logger import get_logger


class Keysight3446xDMM:
    def __init__(self, visa_address: str, name: str = ""):
        self._logger = get_logger(__name__)
        self._visa_address = visa_address
        self._name = name or visa_address
        self._inst = None

    def connect(self):
        rm = get_visa_rm()
        self._inst = rm.open_resource(self._visa_address)
        self._inst.timeout = 5000
        try:
            self._inst.write("*RST")
            idn = self._inst.query("*IDN?").strip()
        except Exception:
            idn = "IDN failed"
        self._logger.info(f"Connected DMM '{self._name}' at {self._visa_address}: {idn}")

    def close(self):
        if self._inst is None:
            return
        try:
            self._inst.close()
            self._logger.info(f"Disconnected DMM '{self._name}' at {self._visa_address}")
        finally:
            self._inst = None

    def idn(self) -> str:
        if self._inst is None:
            return "Not connected"
        try:
            return self._inst.query("*IDN?").strip()
        except Exception:
            return "IDN query failed"

    def measure_voltage_dc(self) -> float:
        self._inst.write("CONF:VOLT:DC")
        return float(self._inst.query("READ?"))

    def measure_current_dc(self) -> float:
        self._inst.write("CONF:CURR:DC")
        return float(self._inst.query("READ?"))
