from __future__ import annotations

import argparse
import ctypes
import math
from pathlib import Path

import cv2

from config import Config
from cursor_mapper import CursorMapper, CursorPosition
from gesture_detector import Gesture, GestureDetector, GestureState
from stage2_hand_preview import DEFAULT_MODEL, run_preview


def primary_screen_size() -> tuple[int, int]:
    if not hasattr(ctypes, "windll"):
        raise RuntimeError("Stage 4 screen preview currently requires Windows")
    user32 = ctypes.windll.user32
    # Read physical primary-monitor pixels under Windows display scaling.
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except (AttributeError, OSError):
        user32.SetProcessDPIAware()
    width = user32.GetSystemMetrics(0)
    height = user32.GetSystemMetrics(1)
    if width < 2 or height < 2:
        raise RuntimeError("Could not read primary display dimensions")
    return width, height


def is_cursor_tracking_active(hand, state: GestureState) -> bool:
    return (
        hand is not None
        and state.gesture == Gesture.MOVE
        and state.candidate == Gesture.MOVE
    )


class CursorPreview:
    """Apply the stage 4 gesture gate and clear stale preview coordinates."""

    def __init__(self, mapper: CursorMapper):
        self.mapper = mapper

    def update(self, hand, state: GestureState, *, timestamp: float | None = None) -> CursorPosition | None:
        if not is_cursor_tracking_active(hand, state):
            self.mapper.reset()
            return None
        index_tip = hand.landmarks[8]
        return self.mapper.update(index_tip.x, index_tip.y, timestamp=timestamp)


def draw_operation_region(frame, config: Config) -> None:
    height, width = frame.shape[:2]
    left = round(config.cursor_margin_x * (width - 1))
    right = round((1.0 - config.cursor_margin_x) * (width - 1))
    top = round(config.cursor_margin_y * (height - 1))
    bottom = round((1.0 - config.cursor_margin_y) * (height - 1))
    cv2.rectangle(frame, (left, top), (right, bottom), (90, 190, 255), 1, cv2.LINE_AA)
    for point in ((left, top), (right, top), (left, bottom), (right, bottom)):
        cv2.circle(frame, point, 4, (90, 190, 255), -1, cv2.LINE_AA)


def draw_screen_preview(
    frame,
    screen_size: tuple[int, int],
    position: CursorPosition | None,
    active: bool,
) -> None:
    height, width = frame.shape[:2]
    panel_width = min(320, max(170, width // 3), width - 24)
    available_height = min(height // 3, 210) - 58
    map_width = min(panel_width - 24, max(1, available_height) * screen_size[0] / screen_size[1])
    map_height = map_width * screen_size[1] / screen_size[0]
    panel_height = round(map_height) + 58
    x0 = width - panel_width - 12
    y0 = height - panel_height - 12
    cv2.rectangle(frame, (x0, y0), (x0 + panel_width, y0 + panel_height), (25, 25, 25), -1)
    cv2.putText(frame, "SCREEN PREVIEW ONLY", (x0 + 9, y0 + 20), cv2.FONT_HERSHEY_SIMPLEX,
                0.45, (230, 230, 230), 1, cv2.LINE_AA)
    left, top = round(x0 + (panel_width - map_width) / 2), y0 + 33
    right, bottom = left + round(map_width), top + round(map_height)
    cv2.rectangle(frame, (left, top), (right, bottom), (150, 150, 150), 1, cv2.LINE_AA)
    if position is not None:
        if active:
            target = (
                round(left + position.target_x / (screen_size[0] - 1) * (right - left)),
                round(top + position.target_y / (screen_size[1] - 1) * (bottom - top)),
            )
            cv2.drawMarker(frame, target, (0, 210, 255), cv2.MARKER_CROSS, 12, 1, cv2.LINE_AA)
        dot_x = round(left + position.normalized_x * (right - left))
        dot_y = round(top + position.normalized_y * (bottom - top))
        cv2.circle(frame, (dot_x, dot_y), 6, (80, 220, 80) if active else (140, 140, 140), -1,
                   cv2.LINE_AA)
    width_px, height_px = screen_size
    label = f"{round(position.x)}, {round(position.y)} / {width_px}x{height_px}" if position else f"- / {width_px}x{height_px}"
    cv2.putText(frame, label, (x0 + 9, y0 + panel_height - 8), cv2.FONT_HERSHEY_SIMPLEX,
                0.4, (210, 210, 210), 1, cv2.LINE_AA)


def draw_status(
    frame,
    hand,
    fps: float,
    state: GestureState,
    config: Config,
    screen_size: tuple[int, int],
    position: CursorPosition | None,
    recent_events: list[str],
) -> None:
    height, width = frame.shape[:2]
    active = is_cursor_tracking_active(hand, state) and position is not None
    draw_operation_region(frame, config)
    if hand is not None:
        index = hand.landmarks[8]
        if all(math.isfinite(value) and abs(value) < 100 for value in (index.x, index.y)):
            tip = (round(index.x * width), round(index.y * height))
            cv2.circle(frame, tip, 10, (0, 255, 255), 2, cv2.LINE_AA)
    draw_screen_preview(frame, screen_size, position, active)

    lines = [
        f"Stage 4 | {state.gesture.value} | FPS: {fps:.1f}",
        f"Cursor: {'PREVIEW' if active else 'PAUSED'}",
        f"Index: ({hand.landmarks[8].x:.3f}, {hand.landmarks[8].y:.3f})" if hand else "Index: NO HAND",
        f"Mapped: ({round(position.x)}, {round(position.y)})" if position else "Mapped: -",
        f"Target: ({round(position.target_x)}, {round(position.target_y)})" if active and position else "Target: -",
        f"Screen: {screen_size[0]} x {screen_size[1]}",
        f"Smooth: {config.smoothing:.2f} | jitter deadzone: {config.cursor_jitter_deadzone_px:.0f}px",
        f"Margins: {config.cursor_margin_x:.2f}, {config.cursor_margin_y:.2f}",
    ]
    lines.extend(recent_events)
    panel_width = min(width - 24, 480)
    panel_height = min(height - 24, 24 + 22 * len(lines))
    cv2.rectangle(frame, (8, 8), (8 + panel_width, 8 + panel_height), (25, 25, 25), -1)
    for index, line in enumerate(lines):
        y = 30 + index * 22
        if y >= panel_height + 4:
            break
        (text_width, _), _ = cv2.getTextSize(line, cv2.FONT_HERSHEY_SIMPLEX, 0.53, 1)
        scale = 0.53 * min(1.0, max(1, panel_width - 20) / max(1, text_width))
        color = (80, 220, 80) if index == 1 and active else (220, 220, 220)
        cv2.putText(frame, line, (18, y), cv2.FONT_HERSHEY_SIMPLEX, scale, color, 1, cv2.LINE_AA)


def main() -> None:
    parser = argparse.ArgumentParser(description="AirControl stage 4: cursor mapping preview only")
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
    cursor_preview = CursorPreview(mapper)
    detector = GestureDetector(
        pinch_on=config.pinch_on_distance,
        pinch_off=config.pinch_off_distance,
        stable_frames=config.gesture_stable_frames,
        finger_min_angle=config.finger_min_angle,
        middle_finger_angle_hysteresis=config.middle_finger_angle_hysteresis,
        middle_stable_frames=config.middle_stable_frames,
    )
    recent_events: list[str] = []

    def draw_overlay(frame, hand, fps, model_path):
        height, width = frame.shape[:2]
        state = detector.update(hand, frame_size=(width, height))
        for event in state.events:
            recent_events.insert(0, event)
            print(event, flush=True)
        del recent_events[3:]

        position = cursor_preview.update(hand, state)
        draw_status(frame, hand, fps, state, config, screen_size, position, recent_events)

    run_preview(config, args.model, draw_overlay, "AirControl - Stage 4 Cursor Preview")


if __name__ == "__main__":
    main()
