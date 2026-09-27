"""
closer.py — Safe tab-closing logic via Windows SendInput.

Milestone M5:
- Re-verifies foreground window, address bar, focus state, and blocked domain right before acting.
- Counts browser tabs using UI Automation.
- If >= 2 tabs: sends Ctrl+W.
- If == 1 tab (or undetermined): sends Ctrl+T -> Ctrl+Shift+Tab -> Ctrl+W (safe sequence to prevent closing whole browser).
- Uses SendInput with ~100ms intervals.
- Always ensures modifier keys (Ctrl, Shift) are released in a finally block.
- Supports --dry-run mode (performs all verification checks without sending keystrokes).
"""

import ctypes
from ctypes import wintypes
import logging
import time
from typing import List, Optional

import uiautomation as auto
import win32gui

from antiproc.config import load_config
from antiproc.detector import clean_domain_from_url, find_browser_address_bar, is_domain_blocked

logger = logging.getLogger("antiproc.closer")

# ---------------- Windows SendInput Ctypes Setup ----------------

PUL = ctypes.POINTER(ctypes.c_ulong)


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", PUL),
    ]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", PUL),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class INPUT_I(ctypes.Union):
    _fields_ = [
        ("ki", KEYBDINPUT),
        ("mi", MOUSEINPUT),
        ("hi", HARDWAREINPUT),
    ]


class INPUT(ctypes.Structure):
    _fields_ = [
        ("type", wintypes.DWORD),
        ("ii", INPUT_I),
    ]


INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002

# Virtual Key Codes
VK_TAB = 0x09
VK_SHIFT = 0x10
VK_CONTROL = 0x11
VK_T = 0x54
VK_W = 0x57


def _send_key(vk_code: int, key_up: bool = False) -> None:
    """Dispatch a single keyboard event via Windows SendInput."""
    extra = ctypes.c_ulong(0)
    inp = INPUT()
    inp.type = INPUT_KEYBOARD
    inp.ii.ki = KEYBDINPUT(
        wVk=vk_code,
        wScan=0,
        dwFlags=KEYEVENTF_KEYUP if key_up else 0,
        time=0,
        dwExtraInfo=ctypes.pointer(extra),
    )
    ctypes.windll.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))


def send_key_combination(keys: List[int], hold_delay: float = 0.08) -> None:
    """
    Press keys in sequential order, hold for hold_delay, and release in reverse order.
    Ensures all keys and modifiers are guaranteed to be released.
    """
    pressed = []
    try:
        for k in keys:
            _send_key(k, key_up=False)
            pressed.append(k)
            time.sleep(0.03)
        time.sleep(hold_delay)
    finally:
        for k in reversed(pressed):
            _send_key(k, key_up=True)
            time.sleep(0.02)
        # Guarantee modifiers never remain stuck down
        _send_key(VK_CONTROL, key_up=True)
        _send_key(VK_SHIFT, key_up=True)


# ---------------- Tab Counting via UI Automation ----------------


def count_browser_tabs(hwnd: int) -> Optional[int]:
    """
    Attempt to count open tabs in the browser window via UI Automation.
    Returns: integer tab count (>= 1), or None if cannot be determined.
    """
    try:
        ctrl = auto.ControlFromHandle(hwnd)
        if not ctrl or not ctrl.Exists(0, 0):
            return None

        # Strategy 1: TabControl search
        tab_ctrl = ctrl.TabControl(searchDepth=8)
        if tab_ctrl.Exists(0, 0):
            children = tab_ctrl.GetChildren()
            tab_items = [
                c for c in children
                if c.ControlTypeName == "TabItemControl" or ("tab" in c.Name.lower() and "new tab" not in c.Name.lower())
            ]
            if tab_items:
                return len(tab_items)

        # Strategy 2: Direct TabItemControls under top panels
        tab_items = []
        for child in ctrl.GetChildren():
            for sub in child.GetChildren():
                if sub.ControlTypeName == "TabItemControl" and "new tab" not in sub.Name.lower():
                    tab_items.append(sub)
        if tab_items:
            return len(tab_items)

    except Exception as e:
        logger.debug("Exception counting browser tabs: %s", e)

    return None


# ---------------- Tab Closing Action ----------------


def perform_safe_tab_close(hwnd: int, is_dry_run: bool = False) -> bool:
    """
    Execute the tab-closing sequence.
    If 2+ tabs: sends Ctrl+W.
    If 1 tab or undetermined: sends Ctrl+T -> Ctrl+Shift+Tab -> Ctrl+W.
    """
    tab_count = count_browser_tabs(hwnd)
    logger.info("Browser tab count for HWND %s: %s", hwnd, tab_count)

    if is_dry_run:
        if tab_count is not None and tab_count >= 2:
            logger.info("[DRY-RUN] Multiple tabs detected (%d). Would send Ctrl+W.", tab_count)
        else:
            logger.info("[DRY-RUN] Single tab or unknown (%s). Would use safe sequence: Ctrl+T -> Ctrl+Shift+Tab -> Ctrl+W.", tab_count)
        return True

    if tab_count is not None and tab_count >= 2:
        logger.info("Multiple tabs detected (%d). Sending Ctrl+W...", tab_count)
        send_key_combination([VK_CONTROL, VK_W])
    else:
        logger.info("Single tab or unknown count (%s). Executing safe sequence...", tab_count)
        # 1. Open new tab (Ctrl+T)
        send_key_combination([VK_CONTROL, VK_T])
        time.sleep(0.12)
        # 2. Switch back to Reddit tab (Ctrl+Shift+Tab)
        send_key_combination([VK_CONTROL, VK_SHIFT, VK_TAB])
        time.sleep(0.12)
        # 3. Close the Reddit tab (Ctrl+W)
        send_key_combination([VK_CONTROL, VK_W])

    return True


def verify_and_close(hwnd: int, expected_domain: str, is_dry_run: bool = False) -> bool:
    """
    Safety gate executed right at the swipe hit frame:
    1. Re-verifies foreground window == hwnd.
    2. Re-verifies address bar still contains a blocked domain.
    3. Re-verifies address bar does NOT have keyboard focus.
    If all checks pass, executes the tab close action.
    """
    current_fg = win32gui.GetForegroundWindow()
    if current_fg != hwnd:
        logger.warning(
            "Close ABORTED: Foreground window changed (expected HWND %s, got HWND %s).",
            hwnd,
            current_fg,
        )
        return False

    found, has_focus, raw_url = find_browser_address_bar(hwnd)
    if not found:
        logger.warning("Close ABORTED: Address bar could not be found on re-verification.")
        return False

    if has_focus:
        logger.warning("Close ABORTED: Address bar currently has keyboard focus (user typing).")
        return False

    current_domain = clean_domain_from_url(raw_url)
    cfg = load_config()
    is_blocked, matched = is_domain_blocked(current_domain, cfg.get("blocklist", []))

    if not is_blocked:
        logger.warning(
            "Close ABORTED: Domain '%s' is no longer a blocked domain (expected '%s').",
            current_domain,
            expected_domain,
        )
        return False

    logger.info("Pre-action safety checks PASSED for HWND %s (domain: %s).", hwnd, current_domain)
    return perform_safe_tab_close(hwnd, is_dry_run=is_dry_run)
