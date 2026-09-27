"""
states.py — State machine and state definitions for AntiProcPet.

Milestone M2:
- States: SLEEPING, ANGRY, ALERT, RUNNING, SWIPING, RETURNING, IDLE.
- Enforces busy states (ALERT, RUNNING, SWIPING, RETURNING ignore clicks).
- Transitions and timers for click-to-angry, alert grace, swipe, return, and idle.
- Cooldown timer after actions so detection doesn't loop immediately.
"""

from enum import Enum, auto
import logging
from typing import Optional

from PySide6.QtCore import QObject, QPoint, QRect, QTimer, Signal

logger = logging.getLogger("antiproc.states")


class PetState(Enum):
    SLEEPING = auto()
    ANGRY = auto()
    ALERT = auto()
    RUNNING = auto()
    SWIPING = auto()
    RETURNING = auto()
    IDLE = auto()


BUSY_STATES = {
    PetState.ALERT,
    PetState.RUNNING,
    PetState.SWIPING,
    PetState.RETURNING,
}


class PetStateMachine(QObject):
    """Manages pet state transitions and timing."""

    state_changed = Signal(PetState)
    start_run_to = Signal(QPoint)   # emitted when transitioning to RUNNING
    start_return = Signal()         # emitted when transitioning to RETURNING
    swipe_hit = Signal()            # emitted at the impact moment of the swipe
    action_finished = Signal()      # emitted when full sequence finishes

    def __init__(self, grace_seconds: float = 3.0, parent: Optional[QObject] = None):
        super().__init__(parent)

        self._state = PetState.SLEEPING
        self._grace_seconds = grace_seconds
        self._target_pos: Optional[QPoint] = None
        self._is_test_run = False
        self._in_cooldown = False

        # Timers
        self._state_timer = QTimer(self)
        self._state_timer.setSingleShot(True)
        self._timer_callback = None
        self._state_timer.timeout.connect(self._on_state_timer_fired)

        self._cooldown_timer = QTimer(self)
        self._cooldown_timer.setSingleShot(True)
        self._cooldown_timer.timeout.connect(self._end_cooldown)

    @property
    def current_state(self) -> PetState:
        return self._state

    @property
    def is_busy(self) -> bool:
        return self._state in BUSY_STATES

    @property
    def in_cooldown(self) -> bool:
        return self._in_cooldown

    def set_grace_seconds(self, seconds: float) -> None:
        self._grace_seconds = max(0.5, float(seconds))

    def _set_state(self, new_state: PetState) -> None:
        if self._state == new_state:
            return
        old_state = self._state
        self._state = new_state
        logger.info("State changed: %s -> %s", old_state.name, new_state.name)
        self.state_changed.emit(new_state)

    def _end_cooldown(self) -> None:
        self._in_cooldown = False
        logger.debug("Action cooldown ended.")

    def _on_state_timer_fired(self) -> None:
        if self._timer_callback:
            cb = self._timer_callback
            self._timer_callback = None
            cb()

    def _start_state_timer(self, duration_ms: int, callback) -> None:
        """Safely start the single-shot state timer with a callback."""
        self._state_timer.stop()
        self._timer_callback = callback
        self._state_timer.start(duration_ms)

    # ---------------- State Actions ----------------

    def handle_click(self) -> bool:
        """Handle a direct mouse click on the pet. Returns True if handled."""
        if self.is_busy:
            logger.debug("Click ignored: pet is in busy state %s", self._state.name)
            return False

        if self._state in (PetState.SLEEPING, PetState.IDLE):
            self._set_state(PetState.ANGRY)
            # Stay angry for 2 seconds then go back to sleep
            self._start_state_timer(2000, lambda: self._set_state(PetState.SLEEPING))
            return True

        return False

    def trigger_alert(self, target_pos: QPoint, is_test: bool = False, grace_override: Optional[float] = None) -> bool:
        """Trigger ALERT (e.g. from browser detector or test animation)."""
        if self.is_busy or self._in_cooldown:
            return False

        self._target_pos = target_pos
        self._is_test_run = is_test
        self._set_state(PetState.ALERT)

        grace = grace_override if grace_override is not None else self._grace_seconds
        logger.info("Alert triggered with %.1fs grace period (is_test=%s)", grace, is_test)

        self._start_state_timer(int(grace * 1000), self._on_grace_expired)
        return True

    def cancel_alert(self) -> None:
        """Cancel an ongoing alert if the user switched away or closed the blocked tab."""
        if self._state == PetState.ALERT:
            logger.info("Alert cancelled during grace period. Returning to SLEEPING.")
            self._state_timer.stop()
            self._set_state(PetState.SLEEPING)

    def _on_grace_expired(self) -> None:
        """Grace period expired: run to the target!"""
        if self._state != PetState.ALERT:
            return

        if self._target_pos:
            self._set_state(PetState.RUNNING)
            self.start_run_to.emit(self._target_pos)
        else:
            # Fallback if no target
            self._set_state(PetState.SLEEPING)

    def on_reached_target(self) -> None:
        """Called when the pet finishes running to the target location."""
        if self._state != PetState.RUNNING:
            return

        self._set_state(PetState.SWIPING)
        # Swipe animation duration: ~600ms total
        # Hit frame at ~300ms
        QTimer.singleShot(300, self._on_swipe_hit)
        QTimer.singleShot(600, self._on_swipe_finished)

    def _on_swipe_hit(self) -> None:
        if self._state == PetState.SWIPING:
            logger.info("Swipe hit frame reached!")
            self.swipe_hit.emit()

    def _on_swipe_finished(self) -> None:
        if self._state != PetState.SWIPING:
            return
        logger.info("Swipe finished. Returning home.")
        self._set_state(PetState.RETURNING)
        self.start_return.emit()

    def on_returned_home(self) -> None:
        """Called when pet finishes running back to home position."""
        if self._state != PetState.RETURNING:
            return

        logger.info("Pet returned home. Entering IDLE.")
        self._set_state(PetState.IDLE)

        # 2-second action cooldown starts now
        self._in_cooldown = True
        self._cooldown_timer.start(2000)

        # Idle for 4 seconds then transition back to SLEEPING
        self._start_state_timer(4000, lambda: self._set_state(PetState.SLEEPING))

        self.action_finished.emit()
