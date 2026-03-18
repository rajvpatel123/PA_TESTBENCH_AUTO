# utils/visa_helper.py
"""
VISA helper for PA_TESTBENCH_AUTO.

Auto-discovers all connected VISA instruments by:
  1. Listing all resources from the VISA ResourceManager.
  2. Sending *IDN? to each resource.
  3. Matching the IDN response against a driver map.
  4. Registering the driver under an auto-generated name.

No hardcoded GPIB addresses or USB IDs required.
"""

from utils.visa_manager import get_visa_rm  # no circular dep - visa_manager imports nothing from here
from utils.logger import get_logger

from drivers import (
    KeysightE36xxSupply,
    AgilentE3648ASupply,
    HP6633BSupply,
    Keysight3446xDMM,
    PXAN9030A,
    RSSMBV100B,
)

_logger = get_logger(__name__)

# ── IDN-to-driver map ─────────────────────────────────────────────────────
# Each entry: (list of IDN substrings to match, driver class)
# Matching is case-insensitive. First match wins.
_IDN_MAP = [
    (["E36234A", "E36233A"],  KeysightE36xxSupply),
    (["E3648A"],              AgilentE3648ASupply),
    (["6633B"],               HP6633BSupply),
    (["34465A", "34461A",
      "34411A", "34401A"],    Keysight3446xDMM),
    (["N9030A"],              PXAN9030A),
    (["SMBV100B"],            RSSMBV100B),
]

# ── Role hints for find_driver() ─────────────────────────────────────────────
_ROLE_HINTS = {
    "siggen":  ["SMBV", "SMB", "SMF", "SMA", "E8257", "E8267",
                "MG369", "Signal", "SigGen"],
    "specan":  ["N9030", "PXA", "N9020", "MXA", "FSV", "FSW",
                "RSA", "Spectrum", "SpecAn"],
    "psu":     ["E3623", "E3624", "E3648", "E3631", "6633",
                "6634", "6643", "Supply", "PSU"],
    "dmm":     ["34465", "34461", "34411", "34401", "DMM",
                "Multimeter"],
}


def _match_idn(idn: str):
    """
    Given a raw *IDN? response string, return the matching driver class
    or None if no match is found.
    """
    idn_upper = idn.upper()
    for keywords, cls in _IDN_MAP:
        for kw in keywords:
            if kw.upper() in idn_upper:
                return cls
    return None


def _make_registry_name(idn: str, addr: str) -> str:
    """
    Build a human-readable registry key from the IDN response and address.
    Example: 'Agilent_E3648A_GPIB10'  or  'Keysight_E36234A_USB'
    """
    parts        = [p.strip() for p in idn.split(",")]
    manufacturer = parts[0] if len(parts) > 0 else "Unknown"
    model        = parts[1] if len(parts) > 1 else "Device"

    mfr_map = {
        "agilent":         "Agilent",
        "keysight":        "Keysight",
        "hewlett-packard": "HP",
        "rohde&schwarz":   "RS",
        "rohde & schwarz": "RS",
    }
    mfr_short = mfr_map.get(manufacturer.lower(), manufacturer.split()[0])

    if "GPIB" in addr.upper():
        import re
        m = re.search(r"GPIB\d+::(\d+)", addr, re.IGNORECASE)
        addr_tag = f"GPIB{m.group(1)}" if m else "GPIB"
    elif "USB" in addr.upper():
        addr_tag = "USB"
    else:
        addr_tag = addr.split("::")[0]

    return f"{mfr_short}_{model}_{addr_tag}"


def load_driver(address: str):
    """
    Open a raw VISA resource, send *IDN?, match to a driver class,
    and return an unconnected driver instance.
    Raises if the address is unreachable or IDN doesn't match any driver.
    """
    rm  = get_visa_rm()
    res = rm.open_resource(address)
    res.timeout = 3000
    try:
        idn = res.query("*IDN?").strip()
    finally:
        try: res.close()
        except Exception: pass

    driver_cls = _match_idn(idn)
    if driver_cls is None:
        raise ValueError(f"No driver match for IDN: '{idn}' at {address}")
    return driver_cls(address)


def discover_instruments(timeout_ms: int = 2000) -> dict:
    """
    Scan all VISA resources, query *IDN?, match to a driver, connect, and
    return a registry dict {name: driver_instance}.

    Instruments that don't respond or don't match any driver are skipped
    with a warning log.
    """
    rm       = get_visa_rm()
    registry = {}

    try:
        resources = rm.list_resources()
    except Exception as e:
        _logger.error(f"Failed to list VISA resources: {e}")
        return registry

    _logger.info(f"Auto-discovery: found {len(resources)} VISA resource(s)")

    for addr in resources:
        res = None
        try:
            res = rm.open_resource(addr)
            res.timeout = timeout_ms
            idn = res.query("*IDN?").strip()
            _logger.debug(f"  {addr}  ->  IDN: {idn}")
        except Exception as e:
            _logger.warning(f"  {addr}: IDN query failed ({e}), skipping")
            if res:
                try: res.close()
                except Exception: pass
            continue

        try: res.close()
        except Exception: pass

        driver_cls = _match_idn(idn)
        if driver_cls is None:
            _logger.warning(f"  {addr}: no driver match for IDN '{idn}', skipping")
            continue

        name = _make_registry_name(idn, addr)

        base_name = name
        counter   = 2
        while name in registry:
            name = f"{base_name}_{counter}"
            counter += 1

        try:
            drv = driver_cls(addr)
            drv.connect()
            registry[name] = drv
            _logger.info(f"  Registered '{name}' ({driver_cls.__name__}) @ {addr}")
        except Exception as e:
            _logger.error(f"  {addr}: driver connect failed ({e}), skipping")

    _logger.info(f"Auto-discovery complete: {len(registry)} instrument(s) registered")
    return registry


def find_driver(registry: dict, role: str, name_hint: str = ""):
    """
    Fuzzy-search the driver registry for an instrument by role or name.

    Priority:
      1. Exact key match on name_hint
      2. Partial name match on name_hint against registry keys
      3. Role-based match using _ROLE_HINTS tags

    Returns the driver object or None.
    """
    if not registry:
        return None

    if name_hint and name_hint in registry:
        return registry[name_hint]

    if name_hint:
        hint_lower = name_hint.lower()
        for key, drv in registry.items():
            if hint_lower in key.lower():
                _logger.debug(f"find_driver: partial match '{name_hint}' -> '{key}'")
                return drv

    tags = _ROLE_HINTS.get(role.lower(), [])
    for key, drv in registry.items():
        key_upper = key.upper()
        for tag in tags:
            if tag.upper() in key_upper:
                _logger.debug(f"find_driver: role '{role}' matched tag '{tag}' -> '{key}'")
                return drv

    _logger.warning(f"find_driver: no match for role='{role}' hint='{name_hint}'")
    return None


def find_all_drivers(registry: dict, role: str) -> list:
    """Return ALL drivers matching a role (e.g. all PSUs)."""
    tags    = _ROLE_HINTS.get(role.lower(), [])
    results = []
    for key, drv in registry.items():
        key_upper = key.upper()
        for tag in tags:
            if tag.upper() in key_upper:
                results.append((key, drv))
                break
    return results
