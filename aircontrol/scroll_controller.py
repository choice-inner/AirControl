from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum

from .cursor_mapper import CursorPosition
from .gesture_detector import Gesture


class ScrollMode(str, Enum):
    IDLE = "IDLE"
    SCROLLING = "SCROLLING"


@dataclass(frozen=True)
class ScrollEvent:
    kind: str
    timestamp: float
    amount: int = 0
    y: float | None = None
    reason: str = ""


class ScrollController:
    """Convert a stable two-finger scroll gesture into simulated wheel events."""

    def __init__(
        self,
        deadzone_px: float = 18.0,
        step_px: float = 24.0,
        gain: float = 1.0,
        max_steps_per_update: int = 5,
        min_interval: float = 0.1,
        max_sample_gap: float = 0.25,
    ):
        values = (deadzone_px, step_px, gain, min_interval, max_sample_gap)
        if any(not math.isfinite(value) or value <= 0 for value in values):
            raise ValueError("scroll thresholds and gain must be finite and positive")
        if not isinstance(max_steps_per_update, int) or isinstance(max_steps_per_update, bool) or max_steps_per_update < 1:
            raise ValueError("max_steps_per_update must be a positive integer")
        self.deadzone_px = deadzone_px
        self.step_px = step_px
        self.gain = gain
        self.max_steps_per_update = max_steps_per_update
        self.min_interval = min_interval
        self.max_sample_gap = max_sample_gap
        self.mode = ScrollMode.IDLE
        self._reference_y: float | None = None
        self._last_timestamp: float | None = None
        self._last_sample_at: float | None = None
        self._last_output_at: float | None = None

    @staticmethod
    def _y(position: CursorPosition | None) -> float | None:
        if position is None or not math.isfinite(position.y):
            return None
        return position.y

    def _validate_timestamp(self, timestamp: float) -> None:
        if not math.isfinite(timestamp):
            raise ValueError("timestamp must be finite")
        if self._last_timestamp is not None and timestamp < self._last_timestamp:
            raise ValueError("timestamp must not move backwards")
        self._last_timestamp = timestamp

    def _finish(self, timestamp: float, reason: str) -> tuple[ScrollEvent, ...]:
        if self.mode == ScrollMode.IDLE:
            return ()
        event = ScrollEvent("SCROLL_END", timestamp, y=self._reference_y, reason=reason)
        self.mode = ScrollMode.IDLE
        self._reference_y = None
        self._last_sample_at = None
        self._last_output_at = None
        return (event,)

    def reset(self, timestamp: float, reason: str = "RESET") -> tuple[ScrollEvent, ...]:
        self._validate_timestamp(timestamp)
        return self._finish(timestamp, reason)

    def update(
        self,
        gesture: Gesture,
        position: CursorPosition | None,
        timestamp: float,
    ) -> tuple[ScrollEvent, ...]:
        self._validate_timestamp(timestamp)
        y = self._y(position)
        if gesture != Gesture.SCROLL:
            return self._finish(timestamp, "GESTURE_" + gesture.value)
        if y is None:
            return self._finish(timestamp, "INVALID_POSITION")
        if self.mode == ScrollMode.IDLE:
            self.mode = ScrollMode.SCROLLING
            self._reference_y = y
            self._last_sample_at = timestamp
            self._last_output_at = timestamp
            return (ScrollEvent("SCROLL_START", timestamp, y=y),)

        assert self._reference_y is not None
        previous_sample = self._last_sample_at
        self._last_sample_at = timestamp
        if previous_sample is not None and timestamp - previous_sample > self.max_sample_gap:
            self._reference_y = y
            self._last_output_at = timestamp
            return ()
        delta = self._reference_y - y
        assert self._last_output_at is not None
        if abs(delta) < self.deadzone_px or timestamp - self._last_output_at < self.min_interval - 1e-9:
            return ()
        direction = 1 if delta > 0 else -1
        amount = min(self.max_steps_per_update, max(1, int(abs(delta) * self.gain / self.step_px)))
        # Consume this movement, including any excess beyond the output cap.
        # A jump must not leave queued scrolling after the hand stops moving.
        self._reference_y = y
        self._last_output_at = timestamp
        kind = "SCROLL_UP" if direction > 0 else "SCROLL_DOWN"
        return (ScrollEvent(kind, timestamp, amount=amount, y=y),)
