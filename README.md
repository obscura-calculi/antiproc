# AntiProcPet 🐾

A lightweight, offline desktop pet companion for Windows that keeps you focused by closing procrastination websites (like Reddit) before you get distracted.

- **How It Works**: AntiProcPet lives on your Windows desktop and quietly observes the foreground browser window (Chrome, Edge, Brave). Using Windows UI Automation, it reads the address bar of the active tab. When a blocked website is detected, the pet wakes up with a grace countdown, dashes across your screen, and closes the tab automatically using keyboard automation.
- **100% Offline & Private**: Zero network requests, zero telemetry, no accounts, and no cloud. The app never reads webpage contents or keystrokes—only the hostname in the active address bar. No personal data or full URLs are ever logged or sent anywhere.
- **No browser extensions needed**
- **No administrator rights required**
- **Non-activating window**: Never steals keyboard focus from what you're doing
- **Single-tab protection**: Leaves a fresh New Tab open instead of closing your entire browser
- **Always available in System Tray**: Can run discreetly in the background like WhatsApp or Discord

---

## Quick Start (Windows PowerShell)

### 1. Clone the repository and enter the directory

```powershell
git clone <your-repo-url>
cd AntiProcPet
```

### 2. Create and activate a virtual environment

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

> **Note**: If you see an execution policy error, run this once in PowerShell:
> ```powershell
> Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
> ```

### 3. Install pinned dependencies

```powershell
pip install -r requirements.txt
```

### 4. Launch AntiProcPet

```powershell
python -m antiproc.main
```

---

## Command-Line Modes

| Command | Mode | Description |
|---|---|---|
| `python -m antiproc.main` | **Normal Mode** | Runs the pet. When a blocked site is open, it alerts, runs across, and safely closes the tab. |
| `python -m antiproc.main --dry-run` | **Dry-Run Mode** | Full visual behavior (alert, run, paw swipe), but **suppresses all keystrokes** so no tabs are closed. |
| `python -m antiproc.main --debug-detect` | **Diagnostic Tool** | Console-only address bar inspector. Prints what your foreground browser is showing once per second. |

---

## Features & Controls

### The Animal Companion
- **Sits in the Corner**: By default, curls up in the bottom-right corner of your primary screen (above the taskbar).
- **Draggable**: Click and drag the pet to any spot on any connected screen. It remembers its position across restarts.
- **Click-to-Angry**: A quick click on the sleeping animal wakes it up angry (`ANGRY`) for 2 seconds with slanted eyebrows and an angry vein before it goes back to sleep.
- **Grace Period (Default 3s)**: When a blocked site appears, it enters `ALERT` with a pulsing red `!`. If you switch tabs or minimize the browser during these 3 seconds, the alert is cancelled.
- **Safe Closing**: If multiple tabs are open, it sends `Ctrl+W`. If Reddit is the *only* tab in the window, it safely sends `Ctrl+T` $\rightarrow$ `Ctrl+Shift+Tab` $\rightarrow$ `Ctrl+W` so your browser stays open with a blank new tab.
- **Typing Safeguard**: If your cursor is actively in the address bar typing a URL, detection pauses so tabs are never closed by mistake.

### System Tray Controls
Look for the cute animal tray icon in your Windows notification area (near the clock):
- **Double-Click Tray Icon**: Instantly unhides and restores the animal onto your screen.
- **Right-Click Menu**:
  - **Blocking enabled**: Toggle blocking on or off without quitting the app. When disabled, the animal stays sleeping and no tabs are closed.
  - **Hide animal / Show animal**: Hides the floating companion from your screen while keeping the app running in the background. Blocking continues working according to "Blocking enabled". Your hidden/shown choice is remembered across restarts.
  - **Choose animal**: Instantly switch between **Red Panda** and **Dodo** with live visual updates.
  - **Test animation**: Plays the full alert $\rightarrow$ run $\rightarrow$ swipe $\rightarrow$ return flow without touching any browser tabs (automatically unhides the animal if hidden).
  - **Start with Windows**: Silently launches AntiProcPet on login via `pythonw.exe` without showing a command prompt or console window (managed via `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`, no administrator rights required).
  - **Open blocklist file**: Opens `%APPDATA%\AntiProcPet\config.json` in Notepad. Changes are reloaded live without needing to restart.
  - **Open log file**: Opens `%APPDATA%\AntiProcPet\app.log` in Notepad.
  - **Quit**: Exits the app cleanly.

### Single-Instance Protection
The app uses a Windows system mutex (`AntiProcPet_SingleInstance_Mutex`). If AntiProcPet is already running, launching it a second time will notify you and exit immediately without creating duplicate pets or duplicate tray icons.

---

## Configuration (`config.json`)

Saved automatically in `%APPDATA%\AntiProcPet\config.json`:

```json
{
  "animal": "red_panda",
  "scale": 1.0,
  "grace_seconds": 3,
  "poll_interval_ms": 1000,
  "blocking_enabled": true,
  "animal_visible": true,
  "start_with_windows": false,
  "browsers": [
    "chrome.exe",
    "msedge.exe",
    "brave.exe"
  ],
  "blocklist": [
    {"domain": "reddit.com", "enabled": true},
    {"domain": "redd.it", "enabled": true}
  ],
  "home_position": null,
  "home_monitor": null
}
```

- Any modifications saved to this file are automatically picked up live by the app!
- If the file is ever deleted or corrupted, AntiProcPet auto-recovers with safe defaults.

---

## Adding Custom Sprite Art

The app uses built-in procedural drawings for placeholder art. To use your own pixel art or sprite frames:
1. Place PNG image files in `assets/<animal>/<state>/` (e.g. `assets/red_panda/sleeping/frame_01.png`, `frame_02.png`, etc.).
2. Supported states: `sleeping`, `angry`, `alert`, `running`, `swiping`, `returning`, `idle`.
3. The app will automatically load them on launch.

---

## Privacy & Security

- **Zero network requests**: No internet access, telemetry, or analytics.
- **Minimal UIA inspection**: Reads only the address bar in the active foreground browser window.
- **Strict logging**: Logs record only domain names (e.g. `reddit.com`), never full URLs, parameters, page titles, or page contents.
