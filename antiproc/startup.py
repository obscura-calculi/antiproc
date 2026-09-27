"""
startup.py — Windows auto-start configuration via HKCU registry.

Milestone M6:
- Requires no administrator rights (uses HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run).
- Launches AntiProcPet silently via pythonw.exe on user login.
- Safe read/write/delete operations with full error handling.
"""

import logging
import os
from pathlib import Path
import sys
import winreg

logger = logging.getLogger("antiproc.startup")

RUN_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
APP_NAME = "AntiProcPet"


def get_pythonw_command() -> str:
    """Find pythonw.exe in current venv or Python installation and construct run command."""
    venv_dir = Path(sys.prefix)
    pythonw = venv_dir / "Scripts" / "pythonw.exe"
    if not pythonw.exists():
        pythonw = venv_dir / "pythonw.exe"
    if not pythonw.exists():
        pythonw = Path(sys.executable).parent / "pythonw.exe"
    if not pythonw.exists():
        pythonw = Path(sys.executable)

    project_root = Path(__file__).resolve().parent.parent

    cmd = (
        f'"{pythonw}" -c '
        f'"import sys; sys.path.insert(0, r\'{project_root}\'); from antiproc.main import main; main()"'
    )
    return cmd


def is_startup_enabled() -> bool:
    """Check if AntiProcPet is currently registered in HKCU Run key."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, winreg.KEY_READ) as key:
            val, _ = winreg.QueryValueEx(key, APP_NAME)
            return bool(val)
    except FileNotFoundError:
        return False
    except Exception as e:
        logger.warning("Could not query startup registry key: %s", e)
        return False


def set_startup_enabled(enable: bool) -> bool:
    """Add or remove AntiProcPet from HKCU Run key."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, winreg.KEY_SET_VALUE) as key:
            if enable:
                cmd = get_pythonw_command()
                winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, cmd)
                logger.info("Added AntiProcPet to Windows startup: %s", cmd)
            else:
                try:
                    winreg.DeleteValue(key, APP_NAME)
                    logger.info("Removed AntiProcPet from Windows startup.")
                except FileNotFoundError:
                    pass
        return True
    except Exception as e:
        logger.error("Failed to update Windows startup registry key: %s", e)
        return False
