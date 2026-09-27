# AntiProcPet Specification

## Role and Working Style
- Personal desktop app for Windows 10/11 on a personal laptop.
- Plain language explanations and exact copy-paste PowerShell commands.
- Milestone-driven approach: stop after each milestone, provide run instructions and expected behavior, wait for confirmation before moving on.
- No network access, no telemetry, no update checks, no web requests.
- No administrator rights required.
- Do not package into an `.exe` yet; run from source with Python 3.11+.

## What the App Is
A small animated animal companion (default: red panda; second animal: dodo) that lives on top of the desktop and enforces focus:
1. Sits in the bottom-right corner of the screen, sleeping.
2. Clicking the sleeping animal wakes it up angry for ~2 seconds, then it goes back to sleep.
3. Automatically and continuously monitors the foreground browser window (Chrome, Edge, Brave). When Reddit (or other configured blocked domain) is opened, wakes up and displays a red "!" above its head (ALERT).
4. After a grace period (default 3 seconds), runs across the screen to the browser window, performs a paw swipe, and safely closes the tab.
5. Runs back to its home position, idles for a few seconds, then goes back to sleep.

## Hard Constraints
- Windows 10/11. Python 3.11+ with venv and pinned `requirements.txt`.
- NO browser extension. NO Electron. NO AI/LLM. NO YouTube logic yet.
- NO network access.
- NO administrator rights required. No keylogging, no screen capturing, no reading webpage DOM/content. The only information read from other programs is the address bar of the foreground browser window via UI Automation.
- Logs may contain only domain names (e.g., "reddit.com"), never full URLs, page titles, or paths.
- The animal window must NEVER steal keyboard focus from the browser or other applications (using `Qt.WindowDoesNotAcceptFocus`, `WA_ShowWithoutActivating`, `WS_EX_NOACTIVATE`).

## Tech Stack
- Python 3.11+ in a virtual environment (`.venv`).
- `PySide6` for GUI, animations, transparency, and system tray.
- `uiautomation` for reading the browser address bar.
- `pywin32` (`win32gui`, `win32process`, `win32con`, ctypes SendInput) for window geometry, foreground tracking, and keystroke dispatch.
- `psutil` for foreground process identification.
- Standard library: `json`, `logging`, `urllib.parse`, `winreg`.
- Background worker thread for UIA polling with Qt signals to the main GUI thread.

## Project Structure
```
antiproc/
  main.py            # App entry point
  config.py          # Configuration manager (%APPDATA%\AntiProcPet\config.json)
  detector.py        # Background browser UIA address bar polling
  closer.py          # Safe tab closing via SendInput (single-tab protected)
  pet_window.py      # Frameless, transparent, non-activating desktop pet window
  states.py          # State machine and transition logic
  tray.py            # System tray icon and menu
  startup.py         # Windows startup registry management (HKCU)
  logging_setup.py   # Rotating log file setup
assets/
  animals.json       # Settings per animal (FPS per state, scale)
  red_panda/<state>/ # Sprite frames (sleeping, angry, alert, running, swiping, returning, idle)
  dodo/<state>/      # Sprite frames
requirements.txt
README.md
SPEC.md
```

## Animal Window Requirements
- Frameless, transparent background, always on top, hidden from taskbar, never accepts focus.
- Tightly sized to the sprite/placeholder.
- Default position: bottom-right of primary screen's available geometry (above taskbar) with 16 px margin.
- Mouse interaction: press-and-release with < 5 px movement is a CLICK (wakes angry in M2); movement >= 5 px is a DRAG (saves position to `config.json` on release).
- Persists position and monitor in `config.json`. Resets to default corner if saved position is off-screen.
- Per-monitor DPI awareness. Sprites face right; mirror horizontally when moving left.
- Placeholder graphics: if sprite frames are missing, render clean procedural placeholder shapes with `QPainter` displaying the animal and state text (e.g., "SLEEP").

## States and Animations
States: `SLEEPING`, `ANGRY`, `ALERT`, `RUNNING`, `SWIPING`, `RETURNING`, `IDLE`.
- `SLEEPING`: curled up with "z" floating. Default state.
- `ANGRY`: lasts ~2 s after click on sleeping animal, then returns to SLEEPING.
- `ALERT`: red "!" above head, lasts `grace_seconds` (default 3 s). If blocked site navigates away or loses foreground during grace, cancel back to SLEEPING.
- `RUNNING`: moves smoothly (~600 px/s, ease-in/out, ~60 fps) to target point just below top edge of browser window.
- `SWIPING`: paw swipe (~0.6 s). Tab is closed at swipe hit frame.
- `RETURNING`: runs back to saved home position.
- `IDLE`: sits calmly for ~5 s, then returns to SLEEPING.
- 2-second cooldown after tab closing.
- Clicks ignored during busy states (`ALERT`, `RUNNING`, `SWIPING`, `RETURNING`).

## Detection Logic (M3)
- Polled every `poll_interval_ms` (default 1000 ms) on worker thread:
  1. Get foreground window. Ignore if own app.
  2. Inspect process name via psutil. Must match supported browser (`chrome.exe`, `msedge.exe`, `brave.exe`).
  3. Locate address bar via UI Automation (Edit control named "Address and search bar" or fallback first toolbar Edit).
  4. Skip poll if address bar has keyboard focus (user typing a URL).
  5. Parse hostname via `urllib.parse`.
  6. Match domain against blocklist (equals domain or ends with `.domain`).
  7. Require 2 consecutive polls on same window handle before triggering.
- Add `--debug-detect` CLI flag to print detection status once per second without triggering actions.

## Safe Tab Closing Logic (M5)
- Re-verify foreground window handle, blocked domain, and lack of focus before closing.
- Count tabs in window using UIA tab strip:
  - If >= 2 tabs: send `Ctrl+W`.
  - If == 1 tab: send `Ctrl+T`, `Ctrl+Shift+Tab`, `Ctrl+W` (leaves a blank new tab open instead of closing browser).
  - If tab count undetermined: use single-tab-safe sequence.
- Keystrokes via `SendInput` with ~100 ms interval; ensure modifier keys release.
- Add `--dry-run` flag to execute full sequence without sending keystrokes.

## System Tray and Settings (M6)
- Tray icon with options: Blocking enabled, Choose animal, Test animation, Open blocklist file, Open log file, Start with Windows, Quit.
- Single-instance lock.

## Milestones
- **M0**: Project setup, venv, requirements, clean launch/exit (COMPLETED).
- **M1**: Animal window with placeholder art, transparency, non-activating, dragging, position persistence, multi-monitor safe.
- **M2**: State machine, animation timer, click-to-angry, tray icon.
- **M3**: Detection worker and `--debug-detect` tool.
- **M4**: Full loop in `--dry-run` mode.
- **M5**: Real safe tab closing and test checklist.
- **M6**: Tray settings, live reload, startup registry, single-instance lock.
- **M7**: (Optional) Background tab title inspection.
