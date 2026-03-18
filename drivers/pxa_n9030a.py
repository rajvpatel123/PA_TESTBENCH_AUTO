# drivers/pxa_n9030a.py
"""
Driver for Keysight PXA N9030A spectrum analyzer.
"""

from utils.visa_manager import get_visa_rm
from utils.logger import get_logger


class PXAN9030A:
    def __init__(self, visa_address: str, name: str = ""):
        self._logger = get_logger(__name__)
        self._visa_address = visa_address
        self._name = name or visa_address
        self._inst = None

    def connect(self):
        rm = get_visa_rm()
        self._inst = rm.open_resource(self._visa_address)
        self._inst.timeout = 10000
        try:
            self._inst.write("*RST")
            idn = self._inst.query("*IDN?").strip()
        except Exception:
            idn = "IDN failed"
        self._logger.info(f"Connected PXA '{self._name}' at {self._visa_address}: {idn}")

    def close(self):
        if self._inst is None:
            return
        try:
            self._inst.close()
            self._logger.info(f"Disconnected PXA '{self._name}' at {self._visa_address}")
        finally:
            self._inst = None

    def idn(self) -> str:
        if self._inst is None:
            return "Not connected"
        try:
            return self._inst.query("*IDN?").strip()
        except Exception:
            return "IDN query failed"

    def set_center(self, freq_hz: float):
        self._inst.write(f"FREQ:CENT {freq_hz}")

    def set_span(self, span_hz: float):
        self._inst.write(f"FREQ:SPAN {span_hz}")

    def set_rbw(self, rbw_hz: float):
        self._inst.write(f"BAND {rbw_hz}")

    def set_vbw(self, vbw_hz: float):
        self._inst.write(f"BAND:VID {vbw_hz}")

    def set_ref_level(self, level_dbm: float):
        self._inst.write(f"DISP:WIND:TRAC:Y:SCAL:RLEV {level_dbm}")

    def acquire_trace(self):
        return []
