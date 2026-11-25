from __future__ import annotations

import argparse
import math
import time
from pathlib import Path

import cv2

from .click_drag_controller import ActionEvent, ClickDragController, ClickDragMode
from .config import Config
from .cursor_mapper import CursorMapper, CursorPosition
from .gesture_detector import Gesture, GestureDetector, GestureState
from .stage2_hand_preview import DEFAULT_MODEL, run_preview
from .stage4_cursor_preview import (
    draw_operation_region,
    draw_screen_preview,
    primary_screen_size,
)


def valid_landmarks(hand) -> bool:
    landmarks = getattr(hand, "landmarks", None)
    if landmarks is None or len(landmarks) != 21:
        return False
    return all(
        all(hasattr(point, name) and math.isfinite(float(getattr(point, name))) for name in ("x", "y", "z"))
        for point in landmarks
    )


class Stage5Session:
    """Join stable gesture, simulated cursor position, and action states."""

    def __init__(self, detector: GestureDetector, mapper: CursorMapper, controller: ClickDragController,
                 drag_release_grace_seconds: float = 0.12):
        if not math.isfinite(drag_release_grace_seconds) or drag_release_grace_seconds < 0:
            raise ValueError("drag_release_grace_seconds must be finite and non-negative")
        self.detector = detector
        self.mapper = mapper
        self.controller = controller
        self.drag_release_grace_seconds = drag_release_grace_seconds
        self._drag_release_started_at: float | None = None
        self._armed = False
        self._last_move_position: CursorPosition | None = None
        self._pinch_origin: CursorPosition | None = None
        self._pinch_anchor: CursorPosition | None = None
        self._pinch_display: CursorPosition | None = None

    def update(self, hand, frame_size: tuple[int, int], timestamp: float):
        if hand is not None and not valid_landmarks(hand):
            state = self.detector.reset()
            self._armed = False
            self._last_move_position = None
            self._reset_position_state()
            events = self.controller.release_all(timestamp, reason="INVALID_HAND")
            return state, None, events

        state = self.detector.update(hand, frame_size=frame_size)
        position = None
        # A degenerate hand returns a reset state with no palm scale.
        if hand is not None and state.palm_scale > 0 and self.controller.mode == ClickDragMode.DRAGGING:
            if state.candidate == Gesture.PINCH:
                self._drag_release_started_at = None
                position, events = self._update_pinch(hand, timestamp)
                return state, position, events
            if self._drag_release_started_at is None:
                self._drag_release_started_at = timestamp
            if timestamp - self._drag_release_started_at < self.drag_release_grace_seconds:
                # Keep the owned button down but freeze coordinates while uncertain.
                return state, self._pinch_display, ()
            reason = "RELEASE" if state.candidate == Gesture.MOVE else f"GESTURE_{state.candidate.value}"
            events = self.controller.release_all(timestamp, reason)
            self._armed = False
            self._last_move_position = None
            self._reset_position_state()
            return state, None, events
        if hand is None:
            self._armed = False
            self._last_move_position = None
            self._reset_position_state()
            events = self.controller.release_all(timestamp, reason="HAND_LOST")
        elif state.gesture == Gesture.MOVE and state.candidate == Gesture.MOVE:
            if self.controller.mode != ClickDragMode.IDLE:
                events = self.controller.update(Gesture.MOVE, None, timestamp)
                self._reset_position_state()
            else:
                events = ()
            self._armed = True
            index_tip = hand.landmarks[8]
            position = self.mapper.update(index_tip.x, index_tip.y, timestamp=timestamp)
            self._last_move_position = position
        elif state.candidate == Gesture.PINCH and state.gesture in (Gesture.MOVE, Gesture.PINCH):
            if state.gesture == Gesture.PINCH and self._armed:
                position, events = self._update_pinch(hand, timestamp)
            else:
                self.mapper.reset()
                position = self._last_move_position
                events = ()
        elif state.gesture == Gesture.PINCH and state.candidate == Gesture.MOVE and self._armed:
            # Opening the fingers must not become a new drag during release debounce.
            position, events = self._pinch_display, ()
        else:
            reason = f"GESTURE_{state.candidate.value}"
            if self.controller.mode != ClickDragMode.IDLE:
                events = self.controller.release_all(timestamp, reason=reason)
            else:
                events = ()
            self._armed = False
            self._last_move_position = None
            self._reset_position_state()
        return state, position, events

    def _update_pinch(self, hand, timestamp: float):
        # Both tips describe the same pinch; average their individual tracking noise.
        index_tip, thumb_tip = hand.landmarks[8], hand.landmarks[4]
        mapped = self.mapper.update((index_tip.x + thumb_tip.x) * 0.5,
                                    (index_tip.y + thumb_tip.y) * 0.5, timestamp=timestamp)
        if mapped is None:
            events = self.controller.release_all(timestamp, reason="INVALID_POSITION")
            self._armed = False
            self._reset_position_state()
            return None, events
        if self._pinch_origin is None:
            self._pinch_origin = mapped
            self._pinch_anchor = self._last_move_position or mapped
        anchor = self._pinch_anchor or mapped
        origin = self._pinch_origin
        x = min(self.mapper.width - 1, max(0.0, anchor.x + mapped.x - origin.x))
        y = min(self.mapper.height - 1, max(0.0, anchor.y + mapped.y - origin.y))
        position = CursorPosition(
            x,
            y,
            x / (self.mapper.width - 1),
            y / (self.mapper.height - 1),
            x,
            y,
        )
        events = self.controller.update(Gesture.PINCH, position, timestamp)
        self._pinch_display = anchor if self.controller.mode == ClickDragMode.PINCHING else position
        return self._pinch_display, events

    def _reset_position_state(self) -> None:
        self._drag_release_started_at = None
        self.mapper.reset()
        self._pinch_origin = None
        self._pinch_anchor = None
        self._pinch_display = None

    def cleanup(self, timestamp: float, reason: str = "EXIT"):
        self.detector.reset()
        self._armed = False
        self._last_move_position = None
        self._reset_position_state()
        return self.controller.release_all(timestamp, reason)


def draw_status(
    frame,
    hand,
    fps: float,
    state: GestureState,
    config: Config,
    screen_size: tuple[int, int],
    position: CursorPosition | None,
    controller: ClickDragController,
    events: list[ActionEvent],
) -> None:
    height, width = frame.shape[:2]
    draw_operation_region(frame, config)
    valid_hand = valid_landmarks(hand)
    if valid_hand:
        index = hand.landmarks[8]
        tip = (round(index.x * width), round(index.y * height))
        cv2.circle(frame, tip, 10, (0, 255, 255), 2, cv2.LINE_AA)
    draw_screen_preview(frame, screen_size, position, position is not None)

    lines = [
        f"Stage 5 | {state.gesture.value} | FPS: {fps:.1f}",
        f"Action: {controller.mode.value} | Button: {'DOWN' if controller.button_down else 'UP'}",
        f"Index: ({hand.landmarks[8].x:.3f}, {hand.landmarks[8].y:.3f})" if valid_hand else "Index: NO HAND",
        f"Mapped: ({round(position.x)}, {round(position.y)})" if position else "Mapped: -",
        f"Drag threshold: {config.drag_start_distance_px:.0f}px | Click max: {config.click_max_duration:.1f}s",
        "SIMULATION ONLY - no real mouse input",
    ]
    lines.extend(f"{event.kind}{f' ({event.reason})' if event.reason else ''}" for event in events)
    panel_width = min(width - 24, 540)
    panel_height = min(height - 24, 24 + 22 * len(lines))
    cv2.rectangle(frame, (8, 8), (8 + panel_width, 8 + panel_height), (25, 25, 25), -1)
    for index, line in enumerate(lines):
        y = 30 + index * 22
        if y >= panel_height + 4:
            break
        (text_width, _), _ = cv2.getTextSize(line, cv2.FONT_HERSHEY_SIMPLEX, 0.52, 1)
        scale = 0.52 * min(1.0, max(1, panel_width - 20) / max(1, text_width))
        color = (0, 210, 255) if line.startswith(("CLICK", "DRAG", "RELEASE", "PINCH_CANCEL")) else (220, 220, 220)
        cv2.putText(frame, line, (18, y), cv2.FONT_HERSHEY_SIMPLEX, scale, color, 1, cv2.LINE_AA)


def main() -> None:
    parser = argparse.ArgumentParser(description="AirControl stage 5: click and drag preview only")
    parser.add_argument("--camera", type=int, default=0, help="camera index")
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL, help="Hand Landmarker model")
    args = parser.parse_args()

    config = Config(camera_index=args.camera)
    screen_size = primary_screen_size()
    mapper = CursorMapper(
        screen_size,
        smoothing=config.smoothing,
        margin_x=config.cursor_margin_x,
        margin_y=config.cursor_margin_y,
        max_speed=config.cursor_max_speed,
        jitter_deadzone_px=config.cursor_jitter_deadzone_px,
    )
    detector = GestureDetector(
        pinch_on=config.pinch_on_distance,
        pinch_off=config.pinch_off_distance,
        stable_frames=config.gesture_stable_frames,
        finger_min_angle=config.finger_min_angle,
        middle_finger_angle_hysteresis=config.middle_finger_angle_hysteresis,
        middle_stable_frames=config.middle_stable_frames,
    )
    controller = ClickDragController(
        click_cooldown=config.click_cooldown,
        click_max_duration=config.click_max_duration,
        drag_start_distance_px=config.drag_start_distance_px,
        drag_move_epsilon_px=config.drag_move_epsilon_px,
    )
    session = Stage5Session(detector, mapper, controller, config.drag_release_grace_seconds)
    recent_events: list[ActionEvent] = []

    def draw_overlay(frame, hand, fps, model_path):
        timestamp = time.monotonic()
        height, width = frame.shape[:2]
        state, position, events = session.update(hand, (width, height), timestamp)
        if events:
            recent_events[0:0] = events
            for event in events:
                print(event.kind, event.reason, flush=True)
        del recent_events[5:]
        draw_status(frame, hand, fps, state, config, screen_size, position, controller, recent_events)

    def cleanup():
        events = session.cleanup(time.monotonic(), reason="EXIT")
        for event in events:
            print(event.kind, event.reason, flush=True)

    run_preview(config, args.model, draw_overlay, "AirControl - Stage 5 Click Drag Preview", cleanup)


if __name__ == "__main__":
    main()
