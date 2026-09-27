"""
pet_window.py — Transparent, frameless, non-activating desktop pet window.

Milestone M2 features:
- Procedural placeholder animation for all 7 states (SLEEPING, ANGRY, ALERT, RUNNING, SWIPING, RETURNING, IDLE).
- Smooth 60fps movement (~600 px/s) to target points and back to home position.
- Automatic horizontal mirroring when moving left.
- Drag vs. Click threshold (<5px = click -> triggers angry state in M2).
- Non-activating window behavior (never steals focus).
- Red panda and dodo placeholder styles.
"""

import logging
import math
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import (
    QEasingCurve,
    QPoint,
    QRect,
    QSize,
    Qt,
    QTimer,
    QVariantAnimation,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QGuiApplication,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPen,
    QPolygon,
)
from PySide6.QtWidgets import QWidget

from antiproc.config import load_config, save_config
from antiproc.states import PetState

logger = logging.getLogger("antiproc.pet_window")

# Windows constants for non-activating window
GWL_EXSTYLE = -20
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TOPMOST = 0x00000008
WS_EX_TOOLWINDOW = 0x00000080


class PetWindow(QWidget):
    """The floating desktop companion window."""

    clicked = Signal()
    reached_target = Signal()
    returned_home = Signal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)

        self._config = load_config()
        self._animal = self._config.get("animal", "red_panda")
        self._state = PetState.SLEEPING
        self._facing_left = False

        # Drag state
        self._mouse_press_global: Optional[QPoint] = None
        self._window_start_pos: Optional[QPoint] = None
        self._is_dragging = False

        # Dimensions: 120 x 120 logical px base * scale (gives room for '!' badge and floating Zs)
        scale = float(self._config.get("scale", 1.0))
        self._base_size = int(120 * scale)
        self.setFixedSize(self._base_size, self._base_size)

        # Home position (used for RETURNING)
        self._home_pos: QPoint = QPoint(0, 0)

        # Movement animation
        self._move_anim: Optional[QVariantAnimation] = None

        # Frame animation ticker (30 fps for smooth procedural bobbing/pulsing)
        self._tick = 0
        self._anim_timer = QTimer(self)
        self._anim_timer.setInterval(33)  # ~30 fps
        self._anim_timer.timeout.connect(self._on_anim_tick)
        self._anim_timer.start()

        self._setup_window_flags()
        self._setup_position()

    def _setup_window_flags(self) -> None:
        """Configure flags so the window is transparent, on-top, and NEVER steals focus."""
        flags = (
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.SubWindow
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._apply_windows_noactivate()

    def _apply_windows_noactivate(self) -> None:
        """Apply Windows extended style WS_EX_NOACTIVATE to prevent stealing foreground focus."""
        try:
            import win32gui

            hwnd = int(self.winId())
            current_style = win32gui.GetWindowLong(hwnd, GWL_EXSTYLE)
            new_style = current_style | WS_EX_NOACTIVATE | WS_EX_TOPMOST | WS_EX_TOOLWINDOW
            win32gui.SetWindowLong(hwnd, GWL_EXSTYLE, new_style)
            logger.debug("Applied WS_EX_NOACTIVATE to pet window (HWND: %s)", hwnd)
        except Exception as e:
            logger.warning("Could not apply WS_EX_NOACTIVATE: %s", e)

    def _setup_position(self) -> None:
        """Position window at saved coordinates or default bottom-right of primary screen."""
        saved_pos = self._config.get("home_position")
        if saved_pos and isinstance(saved_pos, (list, tuple)) and len(saved_pos) == 2:
            target_pt = QPoint(int(saved_pos[0]), int(saved_pos[1]))
            if self._is_on_any_screen(target_pt):
                self.move(target_pt)
                self._home_pos = target_pt
                logger.info("Restored saved pet position: (%d, %d)", target_pt.x(), target_pt.y())
                return

        self._move_to_default_position()

    def _move_to_default_position(self) -> None:
        primary = QGuiApplication.primaryScreen()
        if not primary:
            self.move(100, 100)
            self._home_pos = self.pos()
            return

        avail = primary.availableGeometry()
        margin = 16
        x = avail.right() - self.width() - margin + 1
        y = avail.bottom() - self.height() - margin + 1
        pos = QPoint(x, y)
        self.move(pos)
        self._home_pos = pos
        logger.info("Set default bottom-right position: (%d, %d) on screen '%s'", x, y, primary.name())

    def _is_on_any_screen(self, pos: QPoint) -> bool:
        """Check if the window rect at `pos` intersects any active display's available area."""
        window_rect = QRect(pos, self.size())
        for screen in QGuiApplication.screens():
            if screen.availableGeometry().intersects(window_rect):
                return True
        return False

    def _save_current_position(self) -> None:
        """Save current window coordinates and monitor name to config.json."""
        current_pos = self.pos()
        self._home_pos = current_pos
        screen_name = ""
        for screen in QGuiApplication.screens():
            if screen.availableGeometry().contains(current_pos):
                screen_name = screen.name()
                break

        self._config["home_position"] = [current_pos.x(), current_pos.y()]
        self._config["home_monitor"] = screen_name
        save_config(self._config)
        logger.info(
            "Saved pet position: (%d, %d) on monitor '%s'",
            current_pos.x(),
            current_pos.y(),
            screen_name,
        )

    # ---------------- State & Animation API ----------------

    def set_animal(self, animal_name: str) -> None:
        if self._animal != animal_name:
            self._animal = animal_name
            self._config["animal"] = animal_name
            save_config(self._config)
            logger.info("Switched animal to: %s", animal_name)
            self.update()

    def set_state(self, state: PetState) -> None:
        self._state = state
        self.update()

    def get_state(self) -> PetState:
        return self._state

    def _on_anim_tick(self) -> None:
        self._tick = (self._tick + 1) % 1000
        self.update()

    # ---------------- Smooth Movement ----------------

    def run_to(self, target: QPoint, callback: Optional[Callable[[], None]] = None) -> None:
        """Smoothly move pet to target position at ~600 px/sec."""
        start = self.pos()
        delta_x = target.x() - start.x()
        self._facing_left = (delta_x < 0)

        dist = math.hypot(target.x() - start.x(), target.y() - start.y())
        duration_ms = max(250, int((dist / 600.0) * 1000))

        if self._move_anim and self._move_anim.state() == QVariantAnimation.State.Running:
            self._move_anim.stop()

        anim = QVariantAnimation(self)
        anim.setStartValue(start)
        anim.setEndValue(target)
        anim.setDuration(duration_ms)
        anim.setEasingCurve(QEasingCurve.Type.InOutQuad)
        anim.valueChanged.connect(self.move)

        def _on_finished():
            self._move_anim = None
            if callback:
                callback()
            self.reached_target.emit()

        anim.finished.connect(_on_finished)
        self._move_anim = anim
        anim.start()
        logger.debug("Moving from %s to %s (duration %dms)", start, target, duration_ms)

    def return_home(self, callback: Optional[Callable[[], None]] = None) -> None:
        """Smoothly move pet back to its saved home position."""
        start = self.pos()
        target = self._home_pos
        delta_x = target.x() - start.x()
        self._facing_left = (delta_x < 0)

        dist = math.hypot(target.x() - start.x(), target.y() - start.y())
        duration_ms = max(250, int((dist / 600.0) * 1000))

        if self._move_anim and self._move_anim.state() == QVariantAnimation.State.Running:
            self._move_anim.stop()

        anim = QVariantAnimation(self)
        anim.setStartValue(start)
        anim.setEndValue(target)
        anim.setDuration(duration_ms)
        anim.setEasingCurve(QEasingCurve.Type.InOutQuad)
        anim.valueChanged.connect(self.move)

        def _on_finished():
            self._move_anim = None
            # Face right again once home
            self._facing_left = False
            if callback:
                callback()
            self.returned_home.emit()

        anim.finished.connect(_on_finished)
        self._move_anim = anim
        anim.start()
        logger.debug("Returning home to %s (duration %dms)", target, duration_ms)

    # ---------------- Mouse Events (Click vs. Drag) ----------------

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._mouse_press_global = event.globalPosition().toPoint()
            self._window_start_pos = self.pos()
            self._is_dragging = False
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._mouse_press_global is None or self._window_start_pos is None:
            return

        current_global = event.globalPosition().toPoint()
        delta = current_global - self._mouse_press_global

        if not self._is_dragging and delta.manhattanLength() >= 5:
            self._is_dragging = True

        if self._is_dragging:
            self.move(self._window_start_pos + delta)
            event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            if self._is_dragging:
                self._save_current_position()
                logger.info("Finished dragging pet to (%d, %d)", self.x(), self.y())
            else:
                # Less than 5px movement: treat as CLICK
                logger.info("Pet clicked!")
                self.clicked.emit()

            self._mouse_press_global = None
            self._window_start_pos = None
            self._is_dragging = False
            event.accept()

    # ---------------- Placeholder Art Rendering ----------------

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

        w = self.width()
        h = self.height()

        # Check if real sprite frames exist in assets/
        assets_dir = Path(__file__).resolve().parent.parent / "assets"
        state_dir = assets_dir / self._animal / self._state.name.lower()
        png_files = list(state_dir.glob("*.png")) if state_dir.exists() else []

        if png_files:
            # Sprite rendering hook for future sprite assets
            pass

        # If facing left, horizontally mirror the rendering
        if self._facing_left:
            painter.translate(w, 0)
            painter.scale(-1, 1)

        self._draw_placeholder(painter, w, h)

    def _draw_placeholder(self, painter: QPainter, w: int, h: int) -> None:
        is_red_panda = (self._animal == "red_panda")
        state = self._state
        tick = self._tick

        # Bobbing calculation for subtle alive feel
        bob_y = int(math.sin(tick * 0.15) * 2) if state in (PetState.SLEEPING, PetState.IDLE) else 0
        if state in (PetState.RUNNING, PetState.RETURNING):
            bob_y = int(abs(math.sin(tick * 0.4)) * 6)

        # Base Palette
        if is_red_panda:
            body_color = QColor(218, 90, 48) if state != PetState.ANGRY else QColor(235, 60, 40)
            ear_inner = QColor(245, 230, 215)
            accent_color = QColor(255, 245, 235)
            tag_color = QColor(190, 70, 35, 220)
        else:
            body_color = QColor(100, 130, 160) if state != PetState.ANGRY else QColor(165, 80, 100)
            ear_inner = QColor(210, 170, 60)
            accent_color = QColor(230, 235, 240)
            tag_color = QColor(70, 95, 125, 220)

        # State-specific tag colors
        if state == PetState.ANGRY:
            tag_color = QColor(220, 40, 40, 230)
        elif state == PetState.ALERT:
            tag_color = QColor(230, 130, 20, 230)
        elif state in (PetState.RUNNING, PetState.RETURNING):
            tag_color = QColor(40, 140, 200, 230)
        elif state == PetState.SWIPING:
            tag_color = QColor(160, 40, 200, 230)

        # 1. Ears / Tuft
        painter.setPen(Qt.PenStyle.NoPen)
        if is_red_panda:
            # Left ear
            painter.setBrush(body_color)
            painter.drawPolygon([QPoint(int(w * 0.22), int(h * 0.38) + bob_y),
                                 QPoint(int(w * 0.30), int(h * 0.16) + bob_y),
                                 QPoint(int(w * 0.45), int(h * 0.30) + bob_y)])
            painter.setBrush(ear_inner)
            painter.drawPolygon([QPoint(int(w * 0.25), int(h * 0.36) + bob_y),
                                 QPoint(int(w * 0.31), int(h * 0.22) + bob_y),
                                 QPoint(int(w * 0.41), int(h * 0.31) + bob_y)])
            # Right ear
            painter.setBrush(body_color)
            painter.drawPolygon([QPoint(int(w * 0.55), int(h * 0.30) + bob_y),
                                 QPoint(int(w * 0.70), int(h * 0.16) + bob_y),
                                 QPoint(int(w * 0.78), int(h * 0.38) + bob_y)])
            painter.setBrush(ear_inner)
            painter.drawPolygon([QPoint(int(w * 0.59), int(h * 0.31) + bob_y),
                                 QPoint(int(w * 0.69), int(h * 0.22) + bob_y),
                                 QPoint(int(w * 0.75), int(h * 0.36) + bob_y)])
        else:
            # Dodo head tuft
            painter.setBrush(ear_inner)
            painter.drawEllipse(QPoint(int(w * 0.36), int(h * 0.25) + bob_y), int(w * 0.08), int(h * 0.08))

        # 2. Body
        body_rect = QRect(int(w * 0.14), int(h * 0.28) + bob_y, int(w * 0.72), int(h * 0.54))
        painter.setBrush(body_color)
        painter.setPen(QPen(QColor(40, 40, 40, 160), 2))
        painter.drawRoundedRect(body_rect, int(w * 0.25), int(h * 0.25))

        # 3. Running feet or swipe claws
        if state in (PetState.RUNNING, PetState.RETURNING):
            foot_phase = (tick % 6) < 3
            painter.setBrush(QColor(50, 40, 40))
            painter.setPen(Qt.PenStyle.NoPen)
            if foot_phase:
                painter.drawEllipse(int(w * 0.25), int(h * 0.80) + bob_y, int(w * 0.14), int(h * 0.08))
                painter.drawEllipse(int(w * 0.60), int(h * 0.76) + bob_y, int(w * 0.14), int(h * 0.08))
            else:
                painter.drawEllipse(int(w * 0.30), int(h * 0.76) + bob_y, int(w * 0.14), int(h * 0.08))
                painter.drawEllipse(int(w * 0.55), int(h * 0.80) + bob_y, int(w * 0.14), int(h * 0.08))

        elif state == PetState.SWIPING:
            # Draw paw slash swipe trail
            painter.setPen(QPen(QColor(255, 230, 80, 220), 4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            swipe_prog = (tick % 10) / 10.0
            arc_y = int(h * 0.35 + swipe_prog * (h * 0.40))
            painter.drawArc(int(w * 0.60), arc_y, int(w * 0.32), int(h * 0.25), 45 * 16, 120 * 16)
            painter.setPen(QPen(QColor(255, 255, 255, 240), 2))
            painter.drawArc(int(w * 0.62), arc_y + 4, int(w * 0.28), int(h * 0.20), 45 * 16, 120 * 16)

        # 4. Eyes & Expressions
        painter.setPen(QPen(QColor(40, 20, 20), 2.5))
        painter.setBrush(Qt.BrushStyle.NoBrush)

        if state == PetState.SLEEPING:
            # Sleeping curved eyes "^ ^"
            painter.drawArc(int(w * 0.30), int(h * 0.44) + bob_y, int(w * 0.12), int(h * 0.10), 30 * 16, 120 * 16)
            painter.drawArc(int(w * 0.58), int(h * 0.44) + bob_y, int(w * 0.12), int(h * 0.10), 30 * 16, 120 * 16)
        elif state == PetState.ANGRY:
            # Angry slanted eyebrows "\ /" and dot eyes
            painter.drawLine(int(w * 0.28), int(h * 0.44) + bob_y, int(w * 0.42), int(h * 0.48) + bob_y)
            painter.drawLine(int(w * 0.72), int(h * 0.44) + bob_y, int(w * 0.58), int(h * 0.48) + bob_y)
            painter.setBrush(QColor(20, 10, 10))
            painter.drawEllipse(int(w * 0.33), int(h * 0.49) + bob_y, int(w * 0.07), int(h * 0.07))
            painter.drawEllipse(int(w * 0.60), int(h * 0.49) + bob_y, int(w * 0.07), int(h * 0.07))
        elif state == PetState.ALERT:
            # Wide alert eyes "O O"
            painter.setBrush(QColor(255, 255, 255))
            painter.setPen(QPen(QColor(30, 20, 20), 2))
            painter.drawEllipse(int(w * 0.28), int(h * 0.43) + bob_y, int(w * 0.15), int(h * 0.15))
            painter.drawEllipse(int(w * 0.57), int(h * 0.43) + bob_y, int(w * 0.15), int(h * 0.15))
            painter.setBrush(QColor(20, 10, 10))
            painter.drawEllipse(int(w * 0.33), int(h * 0.47) + bob_y, int(w * 0.07), int(h * 0.07))
            painter.drawEllipse(int(w * 0.62), int(h * 0.47) + bob_y, int(w * 0.07), int(h * 0.07))
        else:
            # Open friendly/focused eyes
            painter.setBrush(QColor(30, 20, 20))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(int(w * 0.32), int(h * 0.46) + bob_y, int(w * 0.08), int(h * 0.08))
            painter.drawEllipse(int(w * 0.60), int(h * 0.46) + bob_y, int(w * 0.08), int(h * 0.08))

        # 5. Muzzle / Beak
        if is_red_panda:
            painter.setBrush(accent_color)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(QPoint(int(w * 0.50), int(h * 0.57) + bob_y), int(w * 0.10), int(h * 0.06))
            painter.setBrush(QColor(40, 20, 20))
            painter.drawEllipse(QPoint(int(w * 0.50), int(h * 0.54) + bob_y), int(w * 0.035), int(h * 0.025))
        else:
            painter.setBrush(ear_inner)
            painter.setPen(QPen(QColor(140, 100, 20), 1.5))
            painter.drawChord(QRect(int(w * 0.44), int(h * 0.50) + bob_y, int(w * 0.22), int(h * 0.18)), 0, 180 * 16)

        # 6. Overhead Overlays (Floating "z Z", Red "!", Angry vein)
        if state == PetState.SLEEPING:
            z_offset = int((tick % 40) / 4)
            painter.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
            painter.setPen(QColor(255, 255, 255, 200))
            painter.drawText(int(w * 0.74), int(h * 0.28) - z_offset, "z")
            painter.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
            painter.drawText(int(w * 0.82), int(h * 0.20) - z_offset, "Z")

        elif state == PetState.ALERT:
            # Bright Red "!" with pulsing bounce
            alert_bounce = int(math.sin(tick * 0.3) * 3)
            alert_rect = QRect(int(w * 0.42), int(h * 0.02) + alert_bounce, int(w * 0.16), int(h * 0.24))
            # Yellow glow behind it
            painter.setBrush(QColor(255, 240, 100, 200))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(alert_rect.adjusted(-2, -2, 2, 2))
            # Red exclamation
            painter.setFont(QFont("Segoe UI Black", 16, QFont.Weight.ExtraBold))
            painter.setPen(QColor(220, 20, 20))
            painter.drawText(alert_rect, Qt.AlignmentFlag.AlignCenter, "!")

        elif state == PetState.ANGRY:
            # Angry mark 💢
            painter.setFont(QFont("Segoe UI Emoji", 12))
            painter.setPen(QColor(240, 30, 30))
            painter.drawText(int(w * 0.72), int(h * 0.22) + bob_y, "💢")

        # 7. State pill badge at bottom
        tag_text = state.name
        tag_rect = QRect(int(w * 0.16), int(h * 0.82), int(w * 0.68), int(h * 0.16))
        painter.setBrush(tag_color)
        painter.setPen(QPen(QColor(255, 255, 255, 220), 1))
        painter.drawRoundedRect(tag_rect, int(tag_rect.height() / 2), int(tag_rect.height() / 2))

        painter.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        painter.setPen(QColor(255, 255, 255))
        painter.drawText(tag_rect, Qt.AlignmentFlag.AlignCenter, tag_text)
