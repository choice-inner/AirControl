from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum

from cursor_mapper import CursorPosition
from gesture_detector import distance, finger_is_up
from stage5_click_drag_preview import valid_landmarks


class SchemeBGesture(str, Enum):
    NONE = "NONE"
    PINCH_AIM = "PINCH_AIM"
    CLICK_OPEN = "CLICK_OPEN"
    DRAG_OPEN = "DRAG_OPEN"
    SCROLL = "SCROLL"


@dataclass(frozen=True)
class SchemeBState:
    gesture: SchemeBGesture = SchemeBGesture.NONE
    candidate: SchemeBGesture = SchemeBGesture.NONE
    candidate_frames: int = 0
    events: tuple[str, ...] = ()


class SchemeBDetector:
    """Experimental posture classifier for pinch aim, spread click, and open-hand drag."""

    def __init__(
        self,
        stable_frames: int = 3,
        finger_min_angle: float = 155.0,
        pinch_enter_ratio: float = 0.42,
        pinch_release_ratio: float = 0.56,
        click_open_ratio: float = 0.72,
    ):
        if stable_frames < 1:
            raise ValueError("stable_frames must be at least 1")
        if not 0 < finger_min_angle < 180:
            raise ValueError("finger_min_angle must be between 0 and 180")
        if not 0 < pinch_enter_ratio < pinch_release_ratio < click_open_ratio:
            raise ValueError("pinch and open ratios must be increasing")
        self.stable_frames = stable_frames
        self.finger_min_angle = finger_min_angle
        self.pinch_enter_ratio = pinch_enter_ratio
        self.pinch_release_ratio = pinch_release_ratio
        self.click_open_ratio = click_open_ratio
        self._gesture = SchemeBGesture.NONE
        self._candidate = SchemeBGesture.NONE
        self._frames = 0
        self._click_latched = False
        self._aim_latched = False

    @property
    def gesture(self):
        return self._gesture

    def reset(self) -> SchemeBState:
        previous = self._gesture
        self._gesture = self._candidate = SchemeBGesture.NONE
        self._frames = 0
        self._click_latched = False
        self._aim_latched = False
        events = () if previous == SchemeBGesture.NONE else (f"{previous.value}_END",)
        return SchemeBState(events=events)

    def _classify(self, hand, frame_size: tuple[int, int]) -> SchemeBGesture:
        width, height = frame_size
        aspect = width / height
        points = [
            (point.x * aspect, point.y, point.z * aspect)
            for point in hand.landmarks
        ]
        palm_scale = distance(points[0], points[9])
        if not math.isfinite(palm_scale) or palm_scale < 1e-6:
            return SchemeBGesture.NONE
        raised = [
            finger_is_up(points, tip, pip, self.finger_min_angle)
            for tip, pip in ((8, 6), (12, 10), (16, 14), (20, 18))
        ]
        drag_raised = [
            finger_is_up(points, tip, pip, max(135.0, self.finger_min_angle - 15.0))
            for tip, pip in ((8, 6), (12, 10), (16, 14), (20, 18))
        ]
        thumb_index_ratio = distance(points[4], points[8]) / palm_scale
        thumb_spread_ratio = distance(points[4], points[5]) / palm_scale
        index, middle, ring, pinky = raised
        # These postures are explicit controls and must win over pinch-distance
        # heuristics, which can fluctuate as the hand moves in front of camera.
        if (drag_raised[0] and drag_raised[1]
                and sum(drag_raised) >= 3
                and (drag_raised[2] or drag_raised[3])
                and thumb_spread_ratio > 0.65):
            return SchemeBGesture.DRAG_OPEN
        candidate_is_aim = self._candidate == SchemeBGesture.PINCH_AIM
        if (thumb_index_ratio <= self.pinch_enter_ratio
                or ((self._aim_latched or self._gesture == SchemeBGesture.PINCH_AIM or candidate_is_aim)
                    and thumb_index_ratio <= self.pinch_release_ratio)):
            # Pinch proximity alone arms relative aiming. Finger-angle estimates
            # are noisy exactly while the user closes and holds the pinch.
            if not self._click_latched:
                return SchemeBGesture.PINCH_AIM
        if index and middle and not ring and not pinky:
            return SchemeBGesture.SCROLL
        if self._aim_latched or self._gesture == SchemeBGesture.PINCH_AIM or candidate_is_aim:
            if (index and not middle and not ring and not pinky
                    and thumb_index_ratio >= self.click_open_ratio):
                return SchemeBGesture.CLICK_OPEN
            if self._click_latched and thumb_index_ratio < self.click_open_ratio:
                return SchemeBGesture.NONE
            if thumb_index_ratio <= self.pinch_release_ratio:
                return SchemeBGesture.PINCH_AIM
            return SchemeBGesture.NONE
        return SchemeBGesture.NONE

    def update(self, hand, frame_size: tuple[int, int]) -> SchemeBState:
        if hand is None or not valid_landmarks(hand):
            return self.reset()
        proposed = self._classify(hand, frame_size)
        if proposed == self._candidate:
            self._frames += 1
        else:
            self._candidate = proposed
            self._frames = 1

        previous = self._gesture
        protected_exit = (previous in (SchemeBGesture.DRAG_OPEN, SchemeBGesture.SCROLL)
                          and proposed != previous)
        required_frames = max(self.stable_frames, 5) if protected_exit else self.stable_frames
        self._frames = min(self._frames, required_frames)
        if self._frames >= required_frames:
            self._gesture = proposed
            if previous != SchemeBGesture.PINCH_AIM and self._gesture == SchemeBGesture.PINCH_AIM:
                self._click_latched = False
                self._aim_latched = True
            elif previous != SchemeBGesture.DRAG_OPEN and self._gesture == SchemeBGesture.DRAG_OPEN:
                self._click_latched = False
                self._aim_latched = False

        events: list[str] = []
        if previous != self._gesture:
            if previous != SchemeBGesture.NONE:
                events.append(f"{previous.value}_END")
            if self._gesture != SchemeBGesture.NONE:
                events.append(f"{self._gesture.value}_START")
        if (previous == SchemeBGesture.PINCH_AIM
                and self._gesture == SchemeBGesture.CLICK_OPEN
                and not self._click_latched):
            events.append("CLICK")
            self._click_latched = True
        if self._gesture == SchemeBGesture.NONE:
            self._click_latched = False
            if not (self._candidate == SchemeBGesture.PINCH_AIM
                    and self._frames < self.stable_frames):
                self._aim_latched = False
        return SchemeBState(self._gesture, self._candidate, self._frames, tuple(events))


class SchemeBSession:
    """Preview-only relative pinch aiming and simulated click/drag/scroll events."""

    def __init__(self, detector: SchemeBDetector, screen_size: tuple[int, int],
                 sensitivity: float = 1.6, smoothing: float = 0.4):
        if min(screen_size) < 2:
            raise ValueError("screen_size must be at least 2x2")
        if not math.isfinite(sensitivity) or sensitivity <= 0:
            raise ValueError("sensitivity must be finite and positive")
        if not 0 < smoothing <= 1:
            raise ValueError("smoothing must be in (0, 1]")
        self.detector = detector
        self.width, self.height = screen_size
        self.sensitivity = sensitivity
        self.smoothing = smoothing
        self.position: CursorPosition | None = None
        self._pinch_origin: tuple[float, float] | None = None
        self._cursor_origin: tuple[float, float] | None = None
        self._last_hand_point: tuple[float, float] | None = None
        self._dragging = False
        self._drag_origin: tuple[float, float] | None = None
        self._drag_cursor_origin: tuple[float, float] | None = None

    @staticmethod
    def _thumb_point(hand, frame_size):
        width, height = frame_size
        thumb = hand.landmarks[4]
        return (thumb.x * width, thumb.y * height)

    def update(self, hand, frame_size: tuple[int, int]):
        previous = self.detector.gesture
        state = self.detector.update(hand, frame_size)
        events = list(state.events)
        if hand is None or not valid_landmarks(hand):
            if self._dragging:
                events.append("DRAG_END HAND_LOST")
            self._clear()
            return state, None, tuple(events)

        point = self._thumb_point(hand, frame_size)
        if self._dragging and state.gesture != SchemeBGesture.DRAG_OPEN:
            self._dragging = False
            events.append("DRAG_END")
            self._drag_origin = None
            self._drag_cursor_origin = None
        if state.gesture == SchemeBGesture.PINCH_AIM:
            if previous != SchemeBGesture.PINCH_AIM:
                self._pinch_origin = point
                if self.position is None:
                    self._cursor_origin = ((self.width - 1) * 0.5, (self.height - 1) * 0.5)
                else:
                    self._cursor_origin = (self.position.x, self.position.y)
                self._last_hand_point = point
                if self.position is None:
                    self._set_position(*self._cursor_origin)
                events.append("AIM_START")
            assert self._pinch_origin is not None and self._cursor_origin is not None
            if state.candidate != SchemeBGesture.CLICK_OPEN:
                desired_x = self._cursor_origin[0] + (point[0] - self._pinch_origin[0]) * self.width / frame_size[0] * self.sensitivity
                desired_y = self._cursor_origin[1] + (point[1] - self._pinch_origin[1]) * self.height / frame_size[1] * self.sensitivity
                self._move_toward(desired_x, desired_y)
                self._last_hand_point = point
        elif state.gesture == SchemeBGesture.CLICK_OPEN:
            self._pinch_origin = None
            self._cursor_origin = None
            self._last_hand_point = None
        elif state.gesture == SchemeBGesture.DRAG_OPEN:
            if not self._dragging:
                self._dragging = True
                self._drag_origin = point
                if self.position is None:
                    self._set_position((self.width - 1) * 0.5, (self.height - 1) * 0.5)
                self._drag_cursor_origin = (self.position.x, self.position.y)
                events.append("DRAG_START")
            if self._drag_origin is not None and self._drag_cursor_origin is not None:
                desired_x = self._drag_cursor_origin[0] + (point[0] - self._drag_origin[0]) * self.width / frame_size[0] * self.sensitivity
                desired_y = self._drag_cursor_origin[1] + (point[1] - self._drag_origin[1]) * self.height / frame_size[1] * self.sensitivity
                self._move_toward(desired_x, desired_y)
        if state.gesture not in (SchemeBGesture.PINCH_AIM, SchemeBGesture.CLICK_OPEN):
            self._pinch_origin = None
            self._cursor_origin = None
            self._last_hand_point = None
        return state, self.position, tuple(events)

    def _move_toward(self, x, y):
        x = min(self.width - 1, max(0.0, x))
        y = min(self.height - 1, max(0.0, y))
        if self.position is None:
            self._set_position(x, y)
            return
        error = math.dist((x, y), (self.position.x, self.position.y))
        response = min(error / 80.0, 1.0)
        alpha = self.smoothing + (max(0.9, self.smoothing) - self.smoothing) * response
        self._set_position(self.position.x + alpha * (x - self.position.x),
                           self.position.y + alpha * (y - self.position.y))

    def _set_position(self, x, y):
        nx, ny = x / (self.width - 1), y / (self.height - 1)
        self.position = CursorPosition(x, y, nx, ny, x, y)

    def _clear(self):
        self.position = None
        self._pinch_origin = None
        self._cursor_origin = None
        self._last_hand_point = None
        self._dragging = False
        self._drag_origin = None
        self._drag_cursor_origin = None
