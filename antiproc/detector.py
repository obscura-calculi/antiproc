"""
detector.py — Browser address bar detection via Windows UI Automation.

Milestone M3:
- Inspects foreground window process (chrome.exe, msedge.exe, brave.exe).
- Finds the browser address bar with multi-level fallbacks:
    1. Name == "Address and search bar" (standard Chromium)
    2. ClassName in ("OmniboxViewViews", "Chrome_OmniboxView")
    3. First EditControl in the browser's ToolBar
    4. First EditControl in the browser window
- Checks keyboard focus (edit.HasKeyboardFocus): skips if user is currently typing.
- Parses and extracts hostname without storing/logging full URLs, queries, or paths.
- Accurate domain matching: equals domain or ends with "." + domain.
- Standalone debug tool: run with `python -m antiproc.main --debug-detect`.
"""

from dataclasses import dataclass
import logging
import os
import time
from typing import List, Optional, Tuple
from urllib.parse import urlparse

import psutil
import uiautomation as auto
import win32gui
import win32process

logger = logging.getLogger("antiproc.detector")

# Configure uiautomation search timeouts so it never freezes
auto.SetGlobalSearchTimeout(0.4)


@dataclass
class DetectionResult:
    hwnd: int
    process_name: str
    is_browser: bool
    address_bar_found: bool
    has_focus: bool
    domain: Optional[str]
    is_blocked: bool
    matched_entry: Optional[str]
    window_rect: Optional[Tuple[int, int, int, int]]  # (left, top, right, bottom)


def get_current_process_pids() -> set:
    """Return PID of current process and any child processes to ignore our own app."""
    try:
        curr = psutil.Process()
        pids = {curr.pid}
        for child in curr.children(recursive=True):
            pids.add(child.pid)
        return pids
    except Exception:
        return {os.getpid()}


def is_domain_blocked(hostname: Optional[str], blocklist: List[dict]) -> Tuple[bool, Optional[str]]:
    """
    Check if a hostname matches any enabled blocklist entry.
    Exact match: hostname == domain
    Subdomain match: hostname.endswith("." + domain)
    E.g. 'old.reddit.com' matches 'reddit.com', but 'notreddit.com' does NOT.
    """
    if not hostname:
        return False, None

    host = hostname.lower().strip()
    for item in blocklist:
        if not item.get("enabled", True):
            continue
        domain = item.get("domain", "").lower().strip()
        if not domain:
            continue

        if host == domain or host.endswith("." + domain):
            return True, domain

    return False, None


def clean_domain_from_url(raw_text: Optional[str]) -> Optional[str]:
    """
    Parse hostname from raw address bar text.
    Ensures no path, query params, or credentials are leaked.
    Rejects strings with spaces or UI element labels.
    """
    if not raw_text:
        return None

    text = raw_text.strip()
    if not text:
        return None

    # Common browser accessibility labels that are not URLs
    lower_text = text.lower()
    if lower_text in (
        "address and search bar",
        "search or enter web address",
        "search or enter address",
        "search",
        "new tab",
    ):
        return None

    # If the user typed a multi-word search query (e.g. "red panda facts"), it's not a domain
    if " " in text and not text.startswith(("http://", "https://")):
        return None

    # Address bar often omits scheme (e.g. 'reddit.com/r/all')
    if not (text.startswith("http://") or text.startswith("https://")):
        text = "https://" + text

    try:
        parsed = urlparse(text)
        host = parsed.hostname
        if not host:
            return None

        host = host.lower()
        # A valid hostname must not have spaces and typically contains a dot or is localhost
        if " " in host or ('.' not in host and host != "localhost"):
            return None

        # Check for valid characters in hostname
        if all(c.isalnum() or c in ".-" for c in host):
            return host
    except Exception:
        pass

    return None


def find_browser_address_bar(hwnd: int) -> Tuple[bool, bool, Optional[str]]:
    """
    Locate address bar inside the browser window handle using UI Automation.
    Returns: (found, has_focus, raw_url_text)
    """
    try:
        ctrl = auto.ControlFromHandle(hwnd)
        if not ctrl or not ctrl.Exists(0, 0):
            return False, False, None

        edit_ctrl = None

        # Strategy 1: Standard Chromium address bar name
        edit_ctrl = ctrl.EditControl(searchDepth=12, Name="Address and search bar")
        if not edit_ctrl.Exists(0, 0):
            # Strategy 2: Common Chromium omnibox class names
            for cls_name in ("OmniboxViewViews", "Chrome_OmniboxView"):
                candidate = ctrl.EditControl(searchDepth=12, ClassName=cls_name)
                if candidate.Exists(0, 0):
                    edit_ctrl = candidate
                    break

        if not edit_ctrl or not edit_ctrl.Exists(0, 0):
            # Strategy 3: First EditControl within a ToolBar control
            toolbar = ctrl.ToolBarControl(searchDepth=8)
            if toolbar.Exists(0, 0):
                candidate = toolbar.EditControl(searchDepth=6)
                if candidate.Exists(0, 0):
                    edit_ctrl = candidate

        if not edit_ctrl or not edit_ctrl.Exists(0, 0):
            # Strategy 4: Fallback to first EditControl in the window
            candidate = ctrl.EditControl(searchDepth=12)
            if candidate.Exists(0, 0):
                edit_ctrl = candidate

        if not edit_ctrl or not edit_ctrl.Exists(0, 0):
            return False, False, None

        # Check if address bar currently has keyboard focus (user typing a URL)
        has_focus = False
        try:
            has_focus = bool(edit_ctrl.HasKeyboardFocus)
        except Exception:
            pass

        # Read address bar text via ValuePattern
        raw_val = None
        try:
            pattern = edit_ctrl.GetValuePattern()
            if pattern:
                raw_val = pattern.Value
        except Exception:
            pass

        # Only fall back to edit_ctrl.Name if it's not the generic control name
        if not raw_val:
            try:
                name_val = edit_ctrl.Name
                if name_val and name_val.lower() not in (
                    "address and search bar",
                    "search or enter web address",
                    "search or enter address",
                ):
                    raw_val = name_val
            except Exception:
                pass

        return True, has_focus, raw_val

    except Exception as e:
        logger.debug("UIA read exception (expected on lazy browser tree): %s", e)
        return False, False, None


def inspect_foreground_window(cfg: dict, own_pids: Optional[set] = None) -> DetectionResult:
    """Perform a single inspection pass of the current foreground window."""
    if own_pids is None:
        own_pids = get_current_process_pids()

    hwnd = win32gui.GetForegroundWindow()
    if not hwnd or hwnd == 0:
        return DetectionResult(
            hwnd=0,
            process_name="none",
            is_browser=False,
            address_bar_found=False,
            has_focus=False,
            domain=None,
            is_blocked=False,
            matched_entry=None,
            window_rect=None,
        )

    # Ignore our own app windows
    try:
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        if pid in own_pids:
            return DetectionResult(
                hwnd=hwnd,
                process_name="antiproc",
                is_browser=False,
                address_bar_found=False,
                has_focus=False,
                domain=None,
                is_blocked=False,
                matched_entry=None,
                window_rect=None,
            )

        proc = psutil.Process(pid)
        proc_name = proc.name().lower()
    except (psutil.NoSuchProcess, psutil.AccessDenied, Exception):
        proc_name = "unknown"

    supported_browsers = [b.lower() for b in cfg.get("browsers", ["chrome.exe", "msedge.exe", "brave.exe"])]
    is_browser = proc_name in supported_browsers

    if not is_browser:
        return DetectionResult(
            hwnd=hwnd,
            process_name=proc_name,
            is_browser=False,
            address_bar_found=False,
            has_focus=False,
            domain=None,
            is_blocked=False,
            matched_entry=None,
            window_rect=None,
        )

    # Get window geometry (physical / logical rect)
    window_rect = None
    try:
        rect = win32gui.GetWindowRect(hwnd)
        window_rect = (rect[0], rect[1], rect[2], rect[3])
    except Exception:
        pass

    # Find address bar
    found, has_focus, raw_url = find_browser_address_bar(hwnd)
    domain = clean_domain_from_url(raw_url) if found else None

    # Check against blocklist
    blocklist = cfg.get("blocklist", [])
    is_blocked, matched = is_domain_blocked(domain, blocklist)

    return DetectionResult(
        hwnd=hwnd,
        process_name=proc_name,
        is_browser=True,
        address_bar_found=found,
        has_focus=has_focus,
        domain=domain,
        is_blocked=is_blocked,
        matched_entry=matched,
        window_rect=window_rect,
    )


def run_debug_detect_loop(poll_interval_s: float = 1.0) -> None:
    """
    Console debug loop triggered by `python -m antiproc.main --debug-detect`.
    Prints clean status once per second. Never alters windows or closes tabs.
    """
    from antiproc.config import load_config

    cfg = load_config()
    own_pids = get_current_process_pids()

    print("=" * 70)
    print("AntiProcPet -- Address Bar Detection Debug Tool")
    print(f"Supported browsers: {cfg.get('browsers', [])}")
    print(f"Active blocklist:   {[b['domain'] for b in cfg.get('blocklist', []) if b.get('enabled')]}")
    print("Watching foreground window once per second. Press Ctrl+C to exit.")
    print("=" * 70)

    try:
        while True:
            # Re-read config dynamically so changes in config.json show immediately
            cfg = load_config()
            res = inspect_foreground_window(cfg, own_pids)

            timestamp = time.strftime("%H:%M:%S")

            if not res.is_browser:
                status = f"[{timestamp}] Process: {res.process_name:<12} | Not a supported browser"
            elif not res.address_bar_found:
                status = f"[{timestamp}] Process: {res.process_name:<12} | Address bar: NOT FOUND (lazy tree / fullscreen / loading)"
            else:
                focus_str = "TYPING (focus active)" if res.has_focus else "unfocused"
                blocked_str = f"BLOCKED ({res.matched_entry})" if res.is_blocked else "allowed"
                domain_str = res.domain if res.domain else "(new tab / blank)"
                status = (
                    f"[{timestamp}] Process: {res.process_name:<12} | "
                    f"Bar: FOUND | "
                    f"Domain: {domain_str:<18} | "
                    f"Focus: {focus_str:<21} | "
                    f"Status: {blocked_str}"
                )

            print(status, flush=True)
            time.sleep(poll_interval_s)

    except KeyboardInterrupt:
        print("\nDetection debug stopped.")


def win32_rect_to_qt_rect(rect: Optional[Tuple[int, int, int, int]]) -> Optional[object]:
    """Convert physical win32 (left, top, right, bottom) rect to Qt logical QRect."""
    if not rect:
        return None
    try:
        from PySide6.QtCore import QRect
        from PySide6.QtGui import QGuiApplication

        phys_x, phys_y, phys_r, phys_b = rect
        phys_w = phys_r - phys_x
        phys_h = phys_b - phys_y

        primary = QGuiApplication.primaryScreen()
        dpr = primary.devicePixelRatio() if primary else 1.0
        for s in QGuiApplication.screens():
            sg = s.geometry()
            sdpr = s.devicePixelRatio()
            if (
                sg.x() * sdpr <= phys_x < (sg.x() + sg.width()) * sdpr
                and sg.y() * sdpr <= phys_y < (sg.y() + sg.height()) * sdpr
            ):
                dpr = sdpr
                break

        return QRect(int(phys_x / dpr), int(phys_y / dpr), int(phys_w / dpr), int(phys_h / dpr))
    except Exception:
        return None


class DetectorWorker:
    pass  # Type placeholder for non-Qt environments


from PySide6.QtCore import QObject, QThread, Signal


class DetectorWorker(QThread):
    """
    Background worker thread for continuous browser address bar polling.
    Safely initializes COM and emits Qt signals to main GUI thread.
    """

    blocked_detected = Signal(int, str, object)  # hwnd, domain, QRect
    site_cleared = Signal()                     # emitted when navigation leaves blocked site

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._running = True
        self._last_blocked_hwnd: Optional[int] = None
        self._consecutive = 0

    def stop(self) -> None:
        self._running = False
        self.wait(2000)

    def run(self) -> None:
        try:
            import pythoncom
            pythoncom.CoInitialize()
        except Exception:
            pass

        own_pids = get_current_process_pids()
        logger.info("DetectorWorker background thread started.")

        try:
            while self._running:
                from antiproc.config import load_config

                cfg = load_config()

                interval_ms = max(250, int(cfg.get("poll_interval_ms", 1000)))
                sleep_s = interval_ms / 1000.0

                if not cfg.get("blocking_enabled", True):
                    self._consecutive = 0
                    self._last_blocked_hwnd = None
                    time.sleep(sleep_s)
                    continue

                res = inspect_foreground_window(cfg, own_pids)

                if res.is_blocked and not res.has_focus:
                    if res.hwnd == self._last_blocked_hwnd:
                        self._consecutive += 1
                    else:
                        self._last_blocked_hwnd = res.hwnd
                        self._consecutive = 1

                    # Trigger after 2 consecutive polls on the same window
                    if self._consecutive == 2:
                        qt_rect = win32_rect_to_qt_rect(res.window_rect)
                        logger.info(
                            "Blocked site confirmed: domain=%s in HWND=%s",
                            res.domain,
                            res.hwnd,
                        )
                        self.blocked_detected.emit(res.hwnd, res.domain, qt_rect)
                else:
                    if self._consecutive > 0:
                        logger.debug("Blocked site cleared or focus active; resetting consecutive counter.")
                        self._consecutive = 0
                        self._last_blocked_hwnd = None
                        self.site_cleared.emit()

                time.sleep(sleep_s)
        except Exception as e:
            logger.error("DetectorWorker exception in polling loop: %s", e, exc_info=True)
        finally:
            try:
                import pythoncom
                pythoncom.CoUninitialize()
            except Exception:
                pass
            logger.info("DetectorWorker thread stopped.")

