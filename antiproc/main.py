"""
main.py — Main application entry point for AntiProcPet.

Milestone M6 (Complete Polish):
  - Single-instance lock via Windows named mutex.
  - Live configuration reloading via QFileSystemWatcher.
  - Background browser address bar detection via UI Automation.
  - Safe tab-closing logic via Windows SendInput with single-tab protection.
  - Interactive System Tray icon with blocking toggle, animal picker, Windows startup, and test actions.
  - Transparent, non-activating floating pet companion with procedural animations.
  - Full CLI support:
      python -m antiproc.main              # Normal run
      python -m antiproc.main --dry-run    # Full loop, no keystrokes sent
      python -m antiproc.main --debug-detect # Address bar detection diagnostic
"""

import ctypes
import signal
import sys
from typing import Optional

from PySide6.QtCore import QFileSystemWatcher, QPoint, QRect, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication

from antiproc.config import config_path, load_config
from antiproc.detector import DetectorWorker, run_debug_detect_loop
from antiproc.logging_setup import setup_logging
from antiproc.pet_window import PetWindow
from antiproc.states import PetState, PetStateMachine
from antiproc.tray import PetTrayIcon


def acquire_single_instance_mutex():
    """
    Ensure only one instance of AntiProcPet is running at a time.
    Returns: Windows mutex handle if acquired, or None if already running.
    """
    ERROR_ALREADY_EXISTS = 183
    kernel32 = ctypes.windll.kernel32
    mutex_name = "Local\\AntiProcPet_SingleInstance_Mutex"
    mutex = kernel32.CreateMutexW(None, False, mutex_name)
    if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
        return None
    return mutex


def main():
    # Diagnostic detection tool flag
    if "--debug-detect" in sys.argv:
        run_debug_detect_loop()
        sys.exit(0)

    # 1. Single-instance lock
    mutex = acquire_single_instance_mutex()
    if not mutex:
        print("\n[!] AntiProcPet is already running! (Single-instance lock active)")
        print("    Look for the cute animal icon in your Windows notification area near the clock.\n")
        sys.exit(0)

    is_dry_run = ("--dry-run" in sys.argv)

    logger = setup_logging()
    mode_str = "DRY-RUN (keystrokes suppressed)" if is_dry_run else "NORMAL"
    logger.info("Starting AntiProcPet [Mode: %s]...", mode_str)

    # Load initial configuration
    cfg = load_config()

    # Create Qt Application
    app = QApplication(sys.argv)
    app.setApplicationName("AntiProcPet")
    app.setQuitOnLastWindowClosed(False)

    # 2. State Machine
    grace = cfg.get("grace_seconds", 3)
    sm = PetStateMachine(grace_seconds=grace)

    # 3. Pet Window
    pet = PetWindow()
    if cfg.get("animal_visible", True):
        pet.show()
    else:
        pet.hide()
        logger.info("Pet started in hidden mode per config.")

    # Active target context for close actions
    active_target = {
        "hwnd": 0,
        "domain": "",
    }

    # Connect Pet Window <--> State Machine
    pet.clicked.connect(sm.handle_click)
    sm.state_changed.connect(pet.set_state)
    sm.start_run_to.connect(lambda target: pet.run_to(target, sm.on_reached_target))
    sm.start_return.connect(lambda: pet.return_home(sm.on_returned_home))

    # Swipe hit handler (M5/M6 safe closing)
    def on_swipe_hit():
        hwnd = active_target["hwnd"]
        domain = active_target["domain"]
        from antiproc.closer import verify_and_close

        success = verify_and_close(hwnd=hwnd, expected_domain=domain, is_dry_run=is_dry_run)
        if success:
            if is_dry_run:
                msg = (
                    f"\n{'='*70}\n"
                    f"[DRY-RUN] SWIPE HIT! Pre-checks passed. Would close {domain} tab in HWND {hwnd}.\n"
                    f"(Dry-run mode active: NO KEYSTROKES SENT.)\n"
                    f"{'='*70}\n"
                )
                print(msg, flush=True)
            else:
                msg = (
                    f"\n{'='*70}\n"
                    f"[BLOCKED SITE CLOSED] Successfully closed {domain} tab in HWND {hwnd}!\n"
                    f"{'='*70}\n"
                )
                print(msg, flush=True)
                logger.info("Closed blocked tab (%s) on HWND %s", domain, hwnd)
        else:
            logger.info("Tab close aborted by safety checks.")

    sm.swipe_hit.connect(on_swipe_hit)

    # 4. Detector Worker (Background Thread)
    detector = DetectorWorker()

    def on_blocked_detected(hwnd: int, domain: str, qt_rect: Optional[QRect]):
        if sm.is_busy or sm.in_cooldown:
            return

        active_target["hwnd"] = hwnd
        active_target["domain"] = domain

        # Calculate run target point near top edge of browser window
        if qt_rect and qt_rect.isValid() and not qt_rect.isEmpty():
            target_x = max(
                qt_rect.left() + 20,
                min(
                    qt_rect.right() - pet.width() - 20,
                    qt_rect.left() + int(qt_rect.width() / 2) - int(pet.width() / 2),
                ),
            )
            target_y = max(20, qt_rect.top() + 40)
            target_pos = QPoint(target_x, target_y)
        else:
            primary = QGuiApplication.primaryScreen()
            avail = primary.availableGeometry() if primary else QRect(0, 0, 1920, 1080)
            target_pos = QPoint(avail.center().x() - int(pet.width() / 2), avail.top() + 60)

        logger.info("Triggering alert for blocked domain '%s' at target %s", domain, target_pos)
        sm.trigger_alert(target_pos, is_test=False)

    def on_site_cleared():
        if sm.current_state == PetState.ALERT:
            logger.info("User switched away or navigated to safe page during grace period. Cancelling alert.")
            sm.cancel_alert()

    detector.blocked_detected.connect(on_blocked_detected)
    detector.site_cleared.connect(on_site_cleared)
    detector.start()

    # 5. Clean Exit Handler
    def quit_app():
        logger.info("Shutting down AntiProcPet...")
        detector.stop()
        if mutex:
            ctypes.windll.kernel32.CloseHandle(mutex)
        app.quit()

    # Allow graceful exit on Ctrl+C from terminal
    signal.signal(signal.SIGINT, lambda *args: quit_app())
    sigint_timer = QTimer()
    sigint_timer.start(250)
    sigint_timer.timeout.connect(lambda: None)

    # 6. Tray Icon
    tray = PetTrayIcon(pet_window=pet, state_machine=sm, on_quit=quit_app)

    # 7. Live Config Reload Watcher (picks up changes to config.json without restarting)
    cfg_file = str(config_path())
    cfg_watcher = QFileSystemWatcher([cfg_file])

    def reload_config_from_disk():
        new_cfg = load_config()
        sm.set_grace_seconds(new_cfg.get("grace_seconds", 3))
        tray.sync_config(new_cfg)
        # Re-add path in case editor performed atomic rewrite
        if cfg_file not in cfg_watcher.files():
            cfg_watcher.addPath(cfg_file)
        logger.info("Live configuration reloaded from %s", cfg_file)

    def on_config_file_modified(_path: str):
        # Short debounce timer to allow file write to finish
        QTimer.singleShot(150, reload_config_from_disk)

    cfg_watcher.fileChanged.connect(on_config_file_modified)

    print(f"\nAntiProcPet running in {mode_str} mode.")
    print("Pet sits in the bottom-right corner. Right-click the tray icon for options.")
    print("Press Ctrl+C or use Quit in the tray menu to exit.\n", flush=True)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
