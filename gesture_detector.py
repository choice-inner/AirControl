from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum


class Gesture(str, Enum):
    NONE = "NONE"
    MOVE = "MOVE"
    PINCH = "PINCH"
    SCROLL = "SCROLL"
    # Reserved for the later mouse-event stage.
    DRAG = "DRAG"


@dataclass(frozen=True)
class GestureState:
    gesture: Gesture = Gesture.NONE
    pinch_active: bool = False
    drag_active: bool = False
    scroll_delta: float = 0.0
    pinch_ratio: float = 0.0
    palm_scale: float = 0.0
    index_up: bool = False
    middle_up: bool = False
    candidate: Gesture = Gesture.NONE
    candidate_frames: int = 0
    changed: bool = False
    events: tuple[str, ...] = ()


def distance(a, b) -> float:
    return math.sqrt(
        (a[0] - b[0]) ** 2
        + (a[1] - b[1]) ** 2
        + (a[2] - b[2]) ** 2
    )


def joint_angle(a, b, c) -> float:
    first = tuple(a[i] - b[i] for i in range(3))
    second = tuple(c[i] - b[i] for i in range(3))
    length = math.dist(a, b) * math.dist(c, b)
    if length < 1e-12:
        return 0.0
    cosine = sum(x * y for x, y in zip(first, second)) / length
    return math.degrees(math.acos(max(-1.0, min(1.0, cosine))))


def finger_is_up(points, tip: int, pip: int, min_angle: float) -> bool:
    mcp, dip = pip - 1, pip + 1
    return (
        joint_angle(points[mcp], points[pip], points[dip]) >= min_angle
        and joint_angle(points[pip], points[dip], points[tip]) >= min_angle
        and distance(points[tip], points[0]) > distance(points[pip], points[0]) * 1.08
    )


class GestureDetector:
    """Convert one detected hand into stable, mutually exclusive states."""

    THUMB_TIP, INDEX_TIP, MIDDLE_TIP = 4, 8, 12
    INDEX_PIP, MIDDLE_PIP = 6, 10
    WRIST, MIDDLE_MCP = 0, 9

    def __init__(
        self,
        pinch_on: float,
        pinch_off: float,
        stable_frames: int = 3,
        finger_min_angle: float = 155.0,
        middle_finger_angle_hysteresis: float = 5.0,
        middle_stable_frames: int = 2,
    ):
        if not (0 < pinch_on < pinch_off) or not math.isfinite(pinch_off):
            raise ValueError("pinch thresholds must satisfy 0 < pinch_on < pinch_off")
        if stable_frames < 1:
            raise ValueError("stable_frames must be at least 1")
        if not 0 < finger_min_angle < 180:
            raise ValueError("finger_min_angle must be between 0 and 180")
        if (
            not math.isfinite(middle_finger_angle_hysteresis)
            or not 0 < middle_finger_angle_hysteresis < min(finger_min_angle, 180 - finger_min_angle)
        ):
            raise ValueError("middle_finger_angle_hysteresis must fit on both sides of finger_min_angle")
        if middle_stable_frames < 1:
            raise ValueError("middle_stable_frames must be at least 1")
        self.pinch_on = pinch_on
        self.pinch_off = pinch_off
        self.stable_frames = stable_frames
        self.finger_min_angle = finger_min_angle
        self.middle_finger_angle_hysteresis = middle_finger_angle_hysteresis
        self.middle_stable_frames = middle_stable_frames
        self._pinch_active = False
        self._middle_up = False
        self._middle_candidate = False
        self._middle_candidate_frames = 0
        self._gesture = Gesture.NONE
        self._candidate = Gesture.NONE
        self._candidate_frames = 0

    @property
    def gesture(self) -> Gesture:
        return self._gesture

    def reset(self) -> GestureState:
        previous = self._gesture
        self._pinch_active = False
        self._middle_up = False
        self._middle_candidate = False
        self._middle_candidate_frames = 0
        self._gesture = Gesture.NONE
        self._candidate = Gesture.NONE
        self._candidate_frames = 0
        return GestureState(
            changed=previous != Gesture.NONE,
            events=self._transition_events(previous, Gesture.NONE),
        )

    @staticmethod
    def _transition_events(previous: Gesture, current: Gesture) -> tuple[str, ...]:
        if previous == current:
            return ()
        events = []
        if previous != Gesture.NONE:
            events.append(f"{previous.value}_END")
        if current != Gesture.NONE:
            events.append(f"{current.value}_START")
        return tuple(events)

    def _stable_gesture(self, proposed: Gesture) -> tuple[Gesture, bool]:
        if proposed == self._candidate:
            self._candidate_frames = min(self._candidate_frames + 1, self.stable_frames)
        else:
            self._candidate = proposed
            self._candidate_frames = 1

        changed = False
        if self._candidate_frames >= self.stable_frames and self._gesture != proposed:
            self._gesture = proposed
            changed = True
        return self._gesture, changed

    def _stable_middle_state(self, points) -> bool:
        # Keep the current classification inside the angle band. This prevents
        # landmark jitter near the straight/bent boundary from toggling scroll.
        if self._middle_up:
            proposed = finger_is_up(
                points, self.MIDDLE_TIP, self.MIDDLE_PIP,
                self.finger_min_angle - self.middle_finger_angle_hysteresis,
            )
        else:
            proposed = finger_is_up(
                points, self.MIDDLE_TIP, self.MIDDLE_PIP,
                self.finger_min_angle + self.middle_finger_angle_hysteresis,
            )

        if proposed == self._middle_up:
            self._middle_candidate = proposed
            self._middle_candidate_frames = 0
        elif proposed == self._middle_candidate:
            self._middle_candidate_frames += 1
        else:
            self._middle_candidate = proposed
            self._middle_candidate_frames = 1

        if self._middle_candidate_frames >= self.middle_stable_frames:
            self._middle_up = proposed
            self._middle_candidate_frames = 0
        return self._middle_up

    def update(self, hand, frame_size: tuple[int, int] = (1, 1)) -> GestureState:
        if hand is None:
            return self.reset()

        width, height = frame_size
        if width <= 0 or height <= 0:
            raise ValueError("frame_size must contain positive width and height")
        # MediaPipe x and z use image width, while y uses image height.
        aspect = width / height
        points = [(x * aspect, y, z * aspect) for x, y, z in (hand.point(i) for i in range(21))]
        if not all(math.isfinite(value) for point in points for value in point):
            return self.reset()
        palm_scale = distance(points[self.WRIST], points[self.MIDDLE_MCP])
        if palm_scale < 1e-6:
            return self.reset()
        pinch_ratio = distance(points[self.THUMB_TIP], points[self.INDEX_TIP]) / palm_scale
        index_up = finger_is_up(points, self.INDEX_TIP, self.INDEX_PIP, self.finger_min_angle)
        middle_up = self._stable_middle_state(points)

        if self._pinch_active:
            if pinch_ratio > self.pinch_off:
                self._pinch_active = False
        elif pinch_ratio < self.pinch_on:
            self._pinch_active = True

        # Pinch has priority so a pinch never becomes scrolling or movement.
        if self._pinch_active:
            proposed = Gesture.PINCH
        elif index_up and middle_up:
            proposed = Gesture.SCROLL
        elif index_up and not middle_up:
            proposed = Gesture.MOVE
        else:
            proposed = Gesture.NONE

        previous = self._gesture
        gesture, changed = self._stable_gesture(proposed)

        return GestureState(
            gesture=gesture,
            pinch_active=gesture == Gesture.PINCH,
            pinch_ratio=pinch_ratio,
            palm_scale=palm_scale,
            index_up=index_up,
            middle_up=middle_up,
            candidate=self._candidate,
            candidate_frames=self._candidate_frames,
            changed=changed,
            events=self._transition_events(previous, gesture),
        )
