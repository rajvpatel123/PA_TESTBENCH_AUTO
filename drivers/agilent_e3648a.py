# drivers/agilent_e3648a.py
"""
Driver for Agilent E3648A dual-output power supply (GPIB).
Channel selection uses INST:SEL OUT{n} — NOT INST:NSEL.

NOTE: The E3648A does not have a separate OCP protection register.
      The current limit IS the protection limit — CURR {amps} is the
      correct command for both set_current() and set_ocp(). Using
      CURR:PROT on this instrument causes it to revert to the hardware
      maximum (5 A) on some firmware versions.
"""
from utils.visa_manager import get_visa_rm
from utils.logger import get_logger


class AgilentE3648ASupply:
    def __init__(self, visa_address: str, name: str = ""):
        self._logger       = get_logger(__name__)
        self._visa_address = visa_address
        self._name         = name or visa_address
        self._inst         = None
        self._channels     = 2

    def connect(self):
        rm = get_visa_rm()
        self._inst         = rm.open_resource(self._visa_address)
        self._inst.timeout = 5000
        try:
            self._inst.write("*RST")
            idn = self._inst.query("*IDN?").strip()
        except Exception:
            idn = "IDN failed"
        self._logger.info(
            f"Connected E3648A '{self._name}' "
            f"at {self._visa_address}: {idn}")

    def close(self):
        if self._inst is None:
            return
        try:
            for ch in range(1, self._channels + 1):
                self.output_on(ch, False)
            self._inst.close()
            self._logger.info(
                f"Disconnected E3648A '{self._name}' at {self._visa_address}")
        finally:
            self._inst = None

    def idn(self) -> str:
        if self._inst is None:
            return "Not connected"
        try:
            return self._inst.query("*IDN?").strip()
        except Exception:
            return "IDN query failed"

    def _select_channel(self, channel: int):
        self._check_channel(channel)
        self._inst.write(f"INST:SEL OUT{channel}")

    def set_voltage(self, channel: int, volts: float):
        self._check_channel(channel)
        self._select_channel(channel)
        self._inst.write(f"VOLT {volts}")
        self._logger.info(f"{self._name} CH{channel} voltage set to {volts} V")

    def set_current(self, channel: int, amps: float):
        self._check_channel(channel)
        self._select_channel(channel)
        self._inst.write(f"CURR {amps}")
        self._logger.info(f"{self._name} CH{channel} current set to {amps} A")

    def set_ovp(self, channel: int, volts: float):
        self._check_channel(channel)
        self._select_channel(channel)
        self._inst.write(f"VOLT:PROT {volts}")
        self._logger.info(f"{self._name} CH{channel} OVP set to {volts} V")

    def set_ocp(self, channel: int, amps: float):
        """
        Set current limit (OCP) for the E3648A.
        CURR:PROT is not supported — CURR is used for both set_current and set_ocp.
        """
        self._check_channel(channel)
        self._select_channel(channel)
        self._inst.write(f"CURR {amps}")
        self._logger.info(f"{self._name} CH{channel} OCP (current limit) set to {amps} A")

    def output_on(self, channel: int, enable: bool):
        self._check_channel(channel)
        self._select_channel(channel)
        state = "ON" if enable else "OFF"
        self._inst.write(f"OUTP {state}")
        self._logger.info(f"{self._name} CH{channel} output {state}")

    def measure_voltage(self, channel: int) -> float:
        self._check_channel(channel)
        self._select_channel(channel)
        return float(self._inst.query("MEAS:VOLT?").strip())

    def measure_current(self, channel: int) -> float:
        self._check_channel(channel)
        self._select_channel(channel)
        return float(self._inst.query("MEAS:CURR?").strip())

    def _check_channel(self, channel: int):
        if not 1 <= channel <= self._channels:
            raise ValueError(f"Channel must be 1..{self._channels}, got {channel}")
        if self._inst is None:
            raise RuntimeError(f"E3648A '{self._name}' not connected")
