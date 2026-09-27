"""
tray.py — System tray icon and menu for AntiProcPet.

Milestone M2 features:
- Generated tray icon (cute animal face) that updates when animal changes.
- "Blocking enabled" checkbox (saved to config).
- "Choose animal" submenu (red_panda, dodo) with immediate switch & persistence.
- "Test animation" triggering full ALERT -> RUN -> SWIPE -> RETURN -> IDLE flow without closing anything.
- "Open blocklist file" and "Open log file".
- "Quit" action.
"""

import logging
import os
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QAction, QActionGroup, QColor, QFont, QGuiApplication, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from antiproc.config import config_path, get_appdata_dir, load_config, save_config
from antiproc.pet_window import PetWindow
from antiproc.states import PetStateMachine

logger = logging.getLogger("antiproc.tray")


def make_tray_icon(animal_name: str) -> QIcon:
    """Generate a clean 32x32 tray icon dynamically."""
    pix = QPixmap(32, 32)
    pix.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    is_red_panda = (animal_name == "red_panda")
    body_color = QColor(218, 90, 48) if is_red_panda else QColor(100, 130, 160)
    accent = QColor(255, 245, 235) if is_red_panda else QColor(220, 180, 70)

    # Circular base
    painter.setBrush(body_color)
    painter.setPen(QColor(30, 30, 30, 180))
    painter.drawEllipse(3, 4, 26, 25)

    # Ears or tuft
    if is_red_panda:
        painter.setBrush(accent)
        painter.setPen(Qt.PenStyle.NoPen)
        # Left ear accent
        painter.drawPolygon([QPoint(5, 7), QPoint(10, 3), QPoint(12, 9)])
        # Right ear accent
        painter.drawPolygon([QPoint(27, 7), QPoint(22, 3), QPoint(20, 9)])
    else:
        # Dodo yellow beak
        painter.setBrush(accent)
        painter.drawChord(10, 15, 12, 10, 0, 180 * 16)

    # Cute eyes
    painter.setBrush(QColor(25, 25, 25))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(9, 13, 3, 4)
    painter.drawEllipse(20, 13, 3, 4)

    painter.end()
    return QIcon(pix)


class PetTrayIcon(QSystemTrayIcon):
    """System tray controller."""

    def __init__(
        self,
        pet_window: PetWindow,
        state_machine: PetStateMachine,
        on_quit: Callable[[], None],
        parent: Optional[object] = None,
    ):
        super().__init__(parent)

        self._pet = pet_window
        self._sm = state_machine
        self._on_quit = on_quit
        self._config = load_config()

        animal = self._config.get("animal", "red_panda")
        self.setIcon(make_tray_icon(animal))
        self.setToolTip("AntiProcPet — Desktop Focus Companion")

        self._setup_menu()
        self.activated.connect(self._on_tray_activated)
        self.show()

    def _setup_menu(self) -> None:
        menu = QMenu()

        # Header title
        title_action = menu.addAction("AntiProcPet 🐾")
        title_action.setEnabled(False)
        menu.addSeparator()

        # 1. Blocking enabled checkbox
        blocking_enabled = self._config.get("blocking_enabled", True)
        self._blocking_action = QAction("Blocking enabled", menu)
        self._blocking_action.setCheckable(True)
        self._blocking_action.setChecked(blocking_enabled)
        self._blocking_action.toggled.connect(self._on_toggle_blocking)
        menu.addAction(self._blocking_action)

        # 2. Hide / Show animal toggle
        is_visible = self._config.get("animal_visible", True)
        self._visibility_action = QAction("Hide animal" if is_visible else "Show animal", menu)
        self._visibility_action.triggered.connect(self._toggle_animal_visibility)
        menu.addAction(self._visibility_action)

        menu.addSeparator()

        # 3. Choose animal submenu
        animal_menu = menu.addMenu("Choose animal")
        animal_group = QActionGroup(animal_menu)
        animal_group.setExclusive(True)

        current_animal = self._config.get("animal", "red_panda")
        animals = [
            ("red_panda", "Red Panda"),
            ("dodo", "Dodo"),
        ]

        # Also inspect assets/ for any custom folders
        assets_dir = Path(__file__).resolve().parent.parent / "assets"
        if assets_dir.exists():
            for folder in assets_dir.iterdir():
                if folder.is_dir() and folder.name not in ("red_panda", "dodo"):
                    animals.append((folder.name, folder.name.replace("_", " ").title()))

        for animal_id, label in animals:
            action = QAction(label, animal_menu)
            action.setCheckable(True)
            if animal_id == current_animal:
                action.setChecked(True)
            action.triggered.connect(lambda checked, aid=animal_id: self._on_choose_animal(aid))
            animal_group.addAction(action)
            animal_menu.addAction(action)

        # 3. Test animation
        test_action = menu.addAction("Test animation")
        test_action.triggered.connect(self._run_test_animation)

        menu.addSeparator()

        # 4. Start with Windows checkbox
        from antiproc.startup import is_startup_enabled

        self._startup_action = QAction("Start with Windows", menu)
        self._startup_action.setCheckable(True)
        self._startup_action.setChecked(is_startup_enabled())
        self._startup_action.toggled.connect(self._on_toggle_startup)
        menu.addAction(self._startup_action)

        menu.addSeparator()

        # 5. Open blocklist / config file
        open_config_action = menu.addAction("Open blocklist file")
        open_config_action.triggered.connect(self._open_config_file)

        # 6. Open log file
        open_log_action = menu.addAction("Open log file")
        open_log_action.triggered.connect(self._open_log_file)

        menu.addSeparator()

        # 7. Quit
        quit_action = menu.addAction("Quit")
        quit_action.triggered.connect(self._on_quit)

        self.setContextMenu(menu)

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        """Double-clicking the tray icon restores/shows the pet window."""
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            logger.info("Tray icon double-clicked: showing animal.")
            self.show_animal()

    def _toggle_animal_visibility(self) -> None:
        if self._pet.isVisible():
            self.hide_animal()
        else:
            self.show_animal()

    def hide_animal(self) -> None:
        self._pet.hide()
        self._config["animal_visible"] = False
        save_config(self._config)
        self._visibility_action.setText("Show animal")
        logger.info("Animal companion hidden.")

    def show_animal(self) -> None:
        self._pet.show()
        self._pet._apply_windows_noactivate()
        self._config["animal_visible"] = True
        save_config(self._config)
        self._visibility_action.setText("Hide animal")
        logger.info("Animal companion shown.")

    def _on_toggle_startup(self, enabled: bool) -> None:
        from antiproc.startup import set_startup_enabled
        success = set_startup_enabled(enabled)
        if success:
            self._config["start_with_windows"] = enabled
            save_config(self._config)
            logger.info("Toggled start_with_windows: %s", enabled)
        else:
            # Revert UI state if failed
            self._startup_action.setChecked(not enabled)

    def sync_config(self, cfg: dict) -> None:
        """Update tray menu items when config changes externally."""
        self._config = cfg
        # Sync blocking checkbox
        blocking = cfg.get("blocking_enabled", True)
        if self._blocking_action.isChecked() != blocking:
            self._blocking_action.blockSignals(True)
            self._blocking_action.setChecked(blocking)
            self._blocking_action.blockSignals(False)

        # Sync animal visibility
        visible = cfg.get("animal_visible", True)
        if visible and not self._pet.isVisible():
            self._pet.show()
            self._pet._apply_windows_noactivate()
            self._visibility_action.setText("Hide animal")
        elif not visible and self._pet.isVisible():
            self._pet.hide()
            self._visibility_action.setText("Show animal")

        # Sync animal
        animal = cfg.get("animal", "red_panda")
        self.setIcon(make_tray_icon(animal))
        self._pet.set_animal(animal)

        # Sync startup checkbox
        from antiproc.startup import is_startup_enabled
        current_startup = is_startup_enabled()
        if self._startup_action.isChecked() != current_startup:
            self._startup_action.blockSignals(True)
            self._startup_action.setChecked(current_startup)
            self._startup_action.blockSignals(False)

    def _on_toggle_blocking(self, enabled: bool) -> None:
        self._config["blocking_enabled"] = enabled
        save_config(self._config)
        logger.info("Toggled blocking_enabled: %s", enabled)

    def _on_choose_animal(self, animal_id: str) -> None:
        self._config["animal"] = animal_id
        save_config(self._config)
        self._pet.set_animal(animal_id)
        self.setIcon(make_tray_icon(animal_id))
        logger.info("Selected animal: %s", animal_id)

    def _run_test_animation(self) -> None:
        """Trigger test sequence: ALERT -> RUNNING -> SWIPING -> RETURNING -> IDLE."""
        if self._sm.is_busy:
            logger.info("Test animation ignored: pet is already busy in %s", self._sm.current_state.name)
            return

        # If animal was hidden, show it so the user can see the animation
        if not self._pet.isVisible():
            self.show_animal()

        # Pick a target point on the active screen (~upper center area, simulates browser location)
        screen = QGuiApplication.primaryScreen()
        avail = screen.availableGeometry() if screen else self._pet.geometry()
        target_x = avail.center().x() - int(self._pet.width() / 2)
        target_y = avail.top() + 80
        target = QPoint(target_x, target_y)

        logger.info("Starting test animation to target: (%d, %d)", target.x(), target.y())
        self._sm.trigger_alert(target, is_test=True, grace_override=1.8)

    def _open_config_file(self) -> None:
        path = config_path()
        if not path.exists():
            save_config(self._config)
        try:
            os.startfile(str(path))
        except Exception as e:
            logger.error("Failed to open config file: %s", e)

    def _open_log_file(self) -> None:
        path = get_appdata_dir() / "app.log"
        if not path.exists():
            path.touch()
        try:
            os.startfile(str(path))
        except Exception as e:
            logger.error("Failed to open log file: %s", e)
