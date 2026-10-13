"""Compatibility imports for settings and persistence."""
from .contracts import MODEL_ID
from .storage.store import DEFAULT_SETTINGS, Store
from .storage.json import read_json, write_json

__all__ = ["MODEL_ID", "DEFAULT_SETTINGS", "Store", "read_json", "write_json"]
