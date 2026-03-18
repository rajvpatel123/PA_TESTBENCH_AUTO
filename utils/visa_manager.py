# utils/visa_manager.py
"""
Singleton VISA ResourceManager.

All modules that need a pyvisa ResourceManager should import from here.
This file intentionally imports NOTHING from utils.visa_helper to avoid
circular imports (visa_helper imports drivers, drivers import this file).
"""
import pyvisa
from utils.logger import get_logger

_logger = get_logger(__name__)
_rm = None  # singleton


def get_visa_rm() -> pyvisa.ResourceManager:
    """Return a singleton pyvisa ResourceManager."""
    global _rm
    if _rm is None:
        _rm = pyvisa.ResourceManager()
        _logger.info("Initialized VISA ResourceManager")
    return _rm
