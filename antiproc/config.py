"""
config.py — Manages settings stored in %APPDATA%\\AntiProcPet\\config.json.

On first run it creates the file with sensible defaults.
If the file is corrupted it recreates it (no crash).
"""

import json
import os
import sys
from pathlib import Path


def get_appdata_dir() -> Path:
    """Return %APPDATA%\\AntiProcPet, creating it if needed."""
    base = os.environ.get("APPDATA")
    if not base:
        # Fallback (should never happen on Windows)
        base = Path.home() / "AppData" / "Roaming"
    folder = Path(base) / "AntiProcPet"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


DEFAULTS = {
    "animal": "red_panda",
    "scale": 1.0,
    "grace_seconds": 3,
    "poll_interval_ms": 1000,
    "blocking_enabled": True,
    "animal_visible": True,
    "start_with_windows": False,
    "browsers": ["chrome.exe", "msedge.exe", "brave.exe"],
    "blocklist": [
        {"domain": "reddit.com", "enabled": True},
        {"domain": "redd.it", "enabled": True},
    ],
    "home_position": None,  # null = use default bottom-right
    "home_monitor": None,   # name of the monitor the pet was on
}


def config_path() -> Path:
    return get_appdata_dir() / "config.json"


def load_config() -> dict:
    """Load config.json.  Return defaults on any error."""
    path = config_path()
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            # Merge with defaults so new keys are always present
            merged = {**DEFAULTS, **data}
            return merged
        except Exception:
            pass  # Corrupted — fall through to defaults
    # First run or corrupted: write defaults
    save_config(DEFAULTS)
    return dict(DEFAULTS)


def save_config(cfg: dict) -> None:
    """Write config to disk (pretty-printed for easy hand-editing)."""
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
