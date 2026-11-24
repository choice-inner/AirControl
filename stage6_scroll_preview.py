from __future__ import annotations

import argparse
import time
from pathlib import Path

import cv2

from config import Config
from click_drag_controller import ActionEvent, ClickDragController
from cursor_mapper import CursorMapper, CursorPosition
from gesture_detector import Gesture, GestureDetector, GestureState
from scroll_controller import ScrollController, ScrollEvent
from stage2_hand_preview import DEFAULT_MODEL, run_preview
from stage4_cursor_preview import draw_operation_region, draw_screen_preview, primary_screen_size
from stage5_click_drag_preview import Stage5Session, valid_landmarks


class Stage6Session(Stage5Session):
    """Join stable gestures, a cursor preview, and simulated scroll events."""

    def __init__(self, detector: GestureDetector, mapper: CursorMapper,
                 controller: ClickDragController, scroll: ScrollController,
                 drag_release_grace_seconds: float = 0.12):
        super().__init__(detector, mapper, controller, drag_release_grace_seconds)
        self.scroll = scroll
        self._frozen_cursor: CursorPosition | None = None

    def update(self, hand, frame_size: tuple[int, int], timestamp: float):
        state, position, actions = super().update(hand, frame_size, timestamp)
        if hand is not None and valid_landmarks(hand):
            if (state.gesture == Gesture.SCROLL and state.candidate == Gesture.SCROLL
                    and not self.controller.button_down):
                y = (hand.landmarks[8].y + hand.landmarks[12].y) * 0.5 * frame_size[1]
                sample = CursorPosition(0, y, 0, y / frame_size[1], 0, y)
                events = self.scroll.update(Gesture.SCROLL, sample, timestamp)
                return state, self._frozen_cursor, actions + events
            events = self.scroll.reset(timestamp, f"GESTURE_{state.candidate.value}")
            if position is not None:
                self._frozen_cursor = position
            elif state.candidate != Gesture.SCROLL:
                self._frozen_cursor = None
            return state, position, actions + events
        self._frozen_cursor = None
        reason = "HAND_LOST" if hand is None else "INVALID_HAND"
        return state, None, actions + self.scroll.reset(timestamp, reason)

    def cleanup(self, timestamp: float, reason: str = "EXIT"):
        actions = super().cleanup(timestamp, reason)
        self._frozen_cursor = None
        return actions + self.scroll.reset(timestamp, reason)


def draw_status(frame, hand, fps: float, state: GestureState, config: Config,
                screen_size: tuple[int, int], position: CursorPosition | None,
                controller: ScrollController, events: list[ActionEvent | ScrollEvent],
                action_controller: ClickDragController | None = None,
                status_note: str = "SIMULATION ONLY - no real mouse input | Q / Esc: quit",
                stage_number: int = 6, real_button_down: bool | None = None,
                mode_label: str | None = None, output_status: str | None = None) -> None:
    height, width = frame.shape[:2]
    draw_operation_region(frame, config)
    if valid_landmarks(hand):
        index = hand.landmarks[8]
        cv2.circle(frame, (round(index.x * width), round(index.y * height)), 10, (0, 255, 255), 2, cv2.LINE_AA)
    draw_screen_preview(frame, screen_size, position, position is not None and state.gesture != Gesture.SCROLL)
    lines = [
        f"Stage {stage_number} | {state.gesture.value} | FPS: {fps:.1f}",
        f"Scroll: {controller.mode.value}",
        f"Candidate: {state.candidate.value} ({state.candidate_frames}/{config.gesture_stable_frames})",
        f"Index: ({hand.landmarks[8].x:.3f}, {hand.landmarks[8].y:.3f})" if valid_landmarks(hand) else "Index: NO HAND",
        (f"Mapped: ({round(position.x)}, {round(position.y)})" +
         (" [FROZEN]" if state.gesture == Gesture.SCROLL else "")) if position else "Mapped: -",
        f"Deadzone: {config.scroll_deadzone_px:.0f} camera px | Gain: {config.scroll_gain:g}",
        status_note,
    ]
    if action_controller is not None:
        held = action_controller.button_down if real_button_down is None else real_button_down
        lines.insert(2, f"Action: {action_controller.mode.value} | Button: {'DOWN' if held else 'UP'}")
    if mode_label is not None:
        lines.insert(1, f"Mode: {mode_label}")
    if output_status is not None:
        lines.insert(2, f"Output: {output_status}")
    lines.extend(f"{event.kind}{f' x{event.amount}' if getattr(event, 'amount', 0) else ''}{f' ({event.reason})' if event.reason else ''}" for event in events)
    panel_width = min(width - 24, 560)
    panel_height = min(height - 24, 24 + 22 * len(lines))
    cv2.rectangle(frame, (8, 8), (8 + panel_width, 8 + panel_height), (25, 25, 25), -1)
    for index, line in enumerate(lines):
        y = 30 + index * 22
        if y >= panel_height + 4:
            break
        (text_width, _), _ = cv2.getTextSize(line, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
        scale = 0.5 * min(1.0, max(1, panel_width - 20) / max(1, text_width))
        cv2.putText(frame, line, (18, y), cv2.FONT_HERSHEY_SIMPLEX, scale, (220, 220, 220), 1, cv2.LINE_AA)


def main() -> None:
    parser = argparse.ArgumentParser(description="AirControl stage 6: scroll preview only")
    parser.add_argument("--camera", type=int, default=0)
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    args = parser.parse_args()
    config = Config(camera_index=args.camera)
    screen_size = primary_screen_size()
    mapper = CursorMapper(screen_size, smoothing=config.smoothing, margin_x=config.cursor_margin_x,
                          margin_y=config.cursor_margin_y, max_speed=config.cursor_max_speed,
                          jitter_deadzone_px=config.cursor_jitter_deadzone_px)
    detector = GestureDetector(
        pinch_on=config.pinch_on_distance, pinch_off=config.pinch_off_distance,
        stable_frames=config.gesture_stable_frames, finger_min_angle=config.finger_min_angle,
        middle_finger_angle_hysteresis=config.middle_finger_angle_hysteresis,
        middle_stable_frames=config.middle_stable_frames,
    )
    scroll = ScrollController(config.scroll_deadzone_px, config.scroll_step_px, config.scroll_gain,
                              config.scroll_max_steps_per_update, config.scroll_min_interval,
                              config.scroll_max_sample_gap)
    controller = ClickDragController(config.click_cooldown, config.click_max_duration,
                                     config.drag_start_distance_px, config.drag_move_epsilon_px)
    session = Stage6Session(detector, mapper, controller, scroll, config.drag_release_grace_seconds)
    recent_events: list[ActionEvent | ScrollEvent] = []

    def draw_overlay(frame, hand, fps, model_path):
        timestamp = time.monotonic()
        state, position, current = session.update(hand, frame.shape[1::-1], timestamp)
        if current:
            recent_events[0:0] = current
            for event in current:
                print(event.kind, getattr(event, "amount", ""), event.reason, flush=True)
        del recent_events[5:]
        draw_status(frame, hand, fps, state, config, screen_size, position, scroll, recent_events, controller)

    def cleanup():
        for event in session.cleanup(time.monotonic(), "EXIT"):
            print(event.kind, getattr(event, "amount", ""), event.reason, flush=True)

    run_preview(config, args.model, draw_overlay, "AirControl - Stage 6 Scroll Preview", cleanup)


if __name__ == "__main__":
    main()
