# utils/visa_manager.py
"""
Shim so that drivers importing from utils.visa_manager still work.
All logic lives in utils.visa_helper.
"""
from utils.visa_helper import get_visa_rm  # noqa: F401
