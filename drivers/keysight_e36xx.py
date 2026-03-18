# drivers/keysight_e36xx.py
"""
Driver for Keysight E362xx / E3623x series power supplies.
"""
import time
from typing import List, Optional
from utils.visa_manager import get_visa_rm
from utils.logger import get_logger

INTER_CMD_DELAY = 0.02
DEFAULT_TIMEOUT = 10000


class KeysightE36xxSupply:
    def __init__(self, visa_address, name="", channels=2, debug=False):
        self._logger       = get_logger(__name__)
        self._visa_address = visa_address
        self._name         = name or visa_address
        self._inst         = None
        self._channels     = channels
        self._debug        = debug

    def connect(self):
        rm = get_visa_rm()
        inst = rm.open_resource(self._visa_address)
        inst.timeout           = DEFAULT_TIMEOUT
        inst.read_termination  = "\n"
        inst.write_termination = "\n"
        inst.send_end          = True
        self._inst = inst
        self._write_raw("*CLS")
        self._write_raw("*RST")
        time.sleep(0.3)
        idn = self._query_raw("*IDN?") or "IDN failed"
        self._logger.info(
            "Connected Keysight E36xx '{}' @ {} ({}ch): {}".format(
                self._name, self._visa_address, self._channels, idn))

    def close(self):
        if self._inst is None:
            return
        try:
            for ch in range(1, self._channels + 1):
                try:
                    self.output_on(ch, False)
                except Exception:
                    pass
            self._inst.close()
            self._logger.info("Disconnected Keysight E36xx '{}'".format(self._name))
        finally:
            self._inst = None

    def query(self, cmd: str) -> str:
        return self._query_raw(cmd) or ""

    def write(self, cmd: str):
        self._write_raw(cmd)

    def idn(self):
        if self._inst is None:
            return "Not connected"
        return self._query_raw("*IDN?") or "IDN query failed"

    def _select_channel(self, channel):
        self._check(channel)
        self._write_raw("INST:NSEL {}".format(channel))

    def set_vi(self, channel, volts, amps):
        self.set_voltage(channel, volts)
        self.set_current(channel, amps)

    def setVI(self, channel, volts, amps):
        self.set_vi(channel, volts, amps)

    def set_voltage(self, channel, volts):
        self._select_channel(channel)
        self._write_raw("VOLT {:.6f}".format(volts))
        self._logger.info("{} CH{} VOLT -> {} V".format(self._name, channel, volts))

    def set_current(self, channel, amps):
        self._select_channel(channel)
        self._write_raw("CURR {:.6f}".format(amps))
        self._logger.info("{} CH{} CURR -> {} A".format(self._name, channel, amps))

    def set_ovp(self, channel, volts):
        self._select_channel(channel)
        self._write_raw("VOLT:PROT {:.6f}".format(volts))
        self._logger.info("{} CH{} OVP -> {} V".format(self._name, channel, volts))

    def set_ocp(self, channel, amps):
        self._select_channel(channel)
        self._write_raw("CURR:PROT {:.6f}".format(amps))
        self._logger.info("{} CH{} OCP -> {} A".format(self._name, channel, amps))

    def output_on(self, channel, enable):
        self._select_channel(channel)
        state = "ON" if enable else "OFF"
        self._write_raw("OUTP {}".format(state))
        self._logger.info("{} CH{} OUTPUT {}".format(self._name, channel, state))

    def outOnOff(self, channel, state):
        self.output_on(channel, bool(state))

    def set_ocp_delay_start_cc(self, channel):
        self._select_channel(channel)
        self._write_raw("CURR:PROT:DEL:STAR CC")

    def setCurrProtectionDelayStartCC(self, channel):
        self.set_ocp_delay_start_cc(channel)

    def set_ocp_delay(self, channel, seconds):
        self._select_channel(channel)
        self._write_raw("CURR:PROT:DEL {:.3f}".format(seconds))

    def setCurrProtectionDelay(self, channel, seconds):
        self.set_ocp_delay(channel, seconds)

    def ocp_enable(self, channel, enable):
        self._select_channel(channel)
        state = "ON" if enable else "OFF"
        self._write_raw("CURR:PROT:STAT {}".format(state))

    def currProtectionOnOff(self, channel, state):
        self.ocp_enable(channel, bool(state))

    def ocp_tripped(self, channel):
        self._select_channel(channel)
        raw = self._query_raw("CURR:PROT:TRIP?")
        try:
            return bool(int(raw))
        except (TypeError, ValueError):
            return False

    def askCurrProtectionTripped(self, channel=1):
        return self.ocp_tripped(channel)

    def ocp_clear(self, channel):
        self._select_channel(channel)
        self._write_raw("CURR:PROT:CLE")

    def clrOverCurrProtectionEvent(self, channel):
        self.ocp_clear(channel)

    def measure_voltage(self, channel):
        self._select_channel(channel)
        raw = self._query_raw("MEAS:VOLT?")
        return self._parse_float(raw, "measure_voltage CH{}".format(channel))

    def measure_current(self, channel):
        self._select_channel(channel)
        raw = self._query_raw("MEAS:CURR?")
        return self._parse_float(raw, "measure_current CH{}".format(channel))

    def measVolt(self, channel):
        return self.measure_voltage(channel)

    def measCurr(self, channel):
        return self.measure_current(channel)

    def measure_all(self, channel):
        return {"volt": self.measure_voltage(channel), "curr": self.measure_current(channel)}

    def check_errors(self):
        errors = []
        if self._inst is None:
            return errors
        for _ in range(20):
            resp = self._query_raw("SYST:ERR?")
            if resp is None or resp.startswith("+0") or resp.startswith("0,"):
                break
            errors.append(resp)
        return errors

    def _check_error(self, context):
        errs = self.check_errors()
        if errs:
            self._logger.error("{} [{}] SCPI errors: {}".format(self._name, context, errs))

    def _write_raw(self, cmd):
        self._ensure_connected()
        self._inst.write(cmd)
        time.sleep(INTER_CMD_DELAY)

    def _query_raw(self, cmd):
        self._ensure_connected()
        try:
            resp = self._inst.query(cmd)
            time.sleep(INTER_CMD_DELAY)
            return resp.strip()
        except Exception as e:
            self._logger.error("{} query '{}' failed: {}".format(self._name, cmd, e))
            return None

    def _parse_float(self, raw, context):
        if raw is None:
            raise RuntimeError("{} [{}]: no response from instrument".format(self._name, context))
        try:
            return float(raw)
        except ValueError:
            raise RuntimeError("{} [{}]: cannot parse '{}' as float".format(self._name, context, raw))

    def _ensure_connected(self):
        if self._inst is None:
            raise RuntimeError("{} is not connected. Call connect() first.".format(self._name))

    def _check(self, channel):
        self._ensure_connected()
        if not 1 <= channel <= self._channels:
            raise ValueError("{}: channel must be 1-{}, got {}".format(self._name, self._channels, channel))
