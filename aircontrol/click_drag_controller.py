from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum

from .cursor_mapper import CursorPosition
from .gesture_detector import Gesture


class ClickDragMode(str, Enum):
    IDLE = "IDLE"
    PINCHING = "PINCHING"
    DRAGGING = "DRAGGING"


@dataclass(frozen=True)
class ActionEvent:
    kind: str
    timestamp: float
    x: float | None = None
    y: float | None = None
    reason: str = ""


class ClickDragController:
    """Turn stable PINCH states into recorded click/drag events only."""

    def __init__(
        self,
        click_cooldown: float = 0.35,
        click_max_duration: float = 0.8,
        drag_start_distance_px: float = 48.0,
        drag_move_epsilon_px: float = 1.0,
    ):
        values = (click_cooldown, click_max_duration, drag_start_distance_px, drag_move_epsilon_px)
        if any(not math.isfinite(value) or value < 0 for value in values):
            raise ValueError("click and drag timing/distance values must be finite and non-negative")
        if drag_start_distance_px <= 0:
            raise ValueError("drag_start_distance_px must be positive")
        self.click_cooldown = click_cooldown
        self.click_max_duration = click_max_duration
        self.drag_start_distance_px = drag_start_distance_px
        self.drag_move_epsilon_px = drag_move_epsilon_px
        self.mode = ClickDragMode.IDLE
        self.button_down = False
        self._pinch_started_at: float | None = None
        self._anchor: tuple[float, float] | None = None
        self._last_position: tuple[float, float] | None = None
        self._last_emitted_position: tuple[float, float] | None = None
        self._last_click_at: float | None = None
        self._last_timestamp: float | None = None

    @staticmethod
    def _point(position: CursorPosition | None) -> tuple[float, float] | None:
        if position is None:
            return None
        point = (position.x, position.y)
        return point if all(math.isfinite(value) for value in point) else None

    @staticmethod
    def _event(kind: str, timestamp: float, point: tuple[float, float] | None = None, reason: str = ""):
        return ActionEvent(kind, timestamp, *(point or (None, None)), reason)

    def _validate_timestamp(self, timestamp: float) -> None:
        if not math.isfinite(timestamp):
            raise ValueError("timestamp must be finite")
        if self._last_timestamp is not None and timestamp < self._last_timestamp:
            raise ValueError("timestamp must not move backwards")
        self._last_timestamp = timestamp

    def _begin_pinch(self, timestamp: float, point: tuple[float, float]) -> tuple[ActionEvent, ...]:
        self.mode = ClickDragMode.PINCHING
        self.button_down = True
        self._pinch_started_at = timestamp
        self._anchor = point
        self._last_position = point
        return (self._event("PINCH_START", timestamp, point),)

    def _finish(self, timestamp: float, reason: str, point: tuple[float, float] | None) -> list[ActionEvent]:
        events: list[ActionEvent] = []
        if self.mode == ClickDragMode.DRAGGING:
            end_point = point or self._last_position
            events.append(self._event("DRAG_END", timestamp, end_point, reason))
        elif self.mode == ClickDragMode.PINCHING:
            started = self._pinch_started_at
            duration = timestamp - started if started is not None else math.inf
            anchor = self._anchor
            release_point = point or self._last_position or anchor
            click_point = anchor
            moved = 0.0
            if anchor is not None and release_point is not None:
                moved = math.dist(anchor, release_point)
            click_allowed = (
                reason == "RELEASE"
                and duration <= self.click_max_duration
                and moved <= self.drag_start_distance_px
                and click_point is not None
                and (self._last_click_at is None or timestamp - self._last_click_at >= self.click_cooldown)
            )
            if click_allowed:
                events.append(self._event("CLICK", timestamp, click_point))
                self._last_click_at = timestamp
            elif (
                reason == "RELEASE"
                and duration <= self.click_max_duration
                and moved <= self.drag_start_distance_px
                and click_point is not None
            ):
                events.append(self._event("CLICK_SUPPRESSED", timestamp, click_point, "COOLDOWN"))
            elif reason == "RELEASE":
                events.append(self._event("PINCH_CANCEL", timestamp, click_point, "TOO_LONG_OR_MOVED"))
            else:
                events.append(self._event("PINCH_CANCEL", timestamp, click_point, reason))

        if self.mode != ClickDragMode.IDLE:
            events.append(self._event("RELEASE_ALL", timestamp, point or self._last_position, reason))
        self.mode = ClickDragMode.IDLE
        self.button_down = False
        self._pinch_started_at = None
        self._anchor = None
        self._last_position = None
        self._last_emitted_position = None
        return events

    def reset(self, timestamp: float, reason: str = "RESET") -> tuple[ActionEvent, ...]:
        return self.release_all(timestamp, reason)

    def release_all(self, timestamp: float, reason: str = "RESET") -> tuple[ActionEvent, ...]:
        """Clear any simulated press/drag state through one cleanup path."""
        self._validate_timestamp(timestamp)
        return tuple(self._finish(timestamp, reason, None))

    def update(
        self,
        gesture: Gesture,
        position: CursorPosition | None,
        timestamp: float,
    ) -> tuple[ActionEvent, ...]:
        self._validate_timestamp(timestamp)
        point = self._point(position)
        if position is not None and point is None:
            return tuple(self._finish(timestamp, "INVALID_POSITION", None))
        events: list[ActionEvent] = []

        if gesture == Gesture.PINCH:
            if point is None:
                return tuple(self._finish(timestamp, "INVALID_POSITION", None))
            if self.mode == ClickDragMode.IDLE:
                events.extend(self._begin_pinch(timestamp, point))
            elif self.mode == ClickDragMode.PINCHING:
                self._last_position = point
                anchor = self._anchor
                if anchor is not None and math.dist(anchor, point) >= self.drag_start_distance_px:
                    self.mode = ClickDragMode.DRAGGING
                    self._last_emitted_position = point
                    events.append(self._event("DRAG_START", timestamp, point))
                    events.append(self._event("DRAG_MOVE", timestamp, point))
            elif self.mode == ClickDragMode.DRAGGING and point is not None:
                self._last_position = point
                previous = self._last_emitted_position
                if previous is None or math.dist(previous, point) >= self.drag_move_epsilon_px:
                    events.append(self._event("DRAG_MOVE", timestamp, point))
                    self._last_emitted_position = point
            return tuple(events)

        if self.mode != ClickDragMode.IDLE:
            reason = "RELEASE" if gesture == Gesture.MOVE else f"GESTURE_{gesture.value}"
            events.extend(self._finish(timestamp, reason, point))
        return tuple(events)
