from __future__ import annotations

import argparse
from collections import deque
from pathlib import Path

import cv2

from .config import Config
from .gesture_detector import Gesture, GestureDetector, GestureState
from .stage2_hand_preview import DEFAULT_MODEL, run_preview


COLORS = {
    Gesture.NONE: (170, 170, 170),
    Gesture.MOVE: (70, 220, 70),
    Gesture.PINCH: (0, 210, 255),
    Gesture.SCROLL: (255, 200, 90),
}


def draw_status(frame, hand, fps: float, state: GestureState, config: Config, events) -> None:
    height, width = frame.shape[:2]
    color = COLORS[state.gesture]
    lines = [
        f"Stage 3 | {state.gesture.value}",
        f"Hand: {hand.handedness if hand else 'NO HAND'} | FPS: {fps:.1f}",
        f"Candidate: {state.candidate.value} ({state.candidate_frames}/{config.gesture_stable_frames})",
        f"Pinch ratio: {state.pinch_ratio:.3f}" if hand else "Pinch ratio: -",
        f"Pinch thresholds: {config.pinch_on_distance:.2f} / {config.pinch_off_distance:.2f}",
        f"Index: {'UP' if state.index_up else 'DOWN'} | Middle: {'UP' if state.middle_up else 'DOWN'}",
    ]
    lines.extend(events)
    # Fit debug text inside the actual camera frame, including 640x480 cameras.
    panel_width = min(width - 16, 500)
    panel_height = min(height - 16, 24 + 22 * len(lines))
    cv2.rectangle(frame, (8, 8), (8 + panel_width, 8 + panel_height), (25, 25, 25), -1)
    for index, line in enumerate(lines):
        y = 30 + index * 22
        if y >= panel_height + 4:
            break
        (text_width, _), _ = cv2.getTextSize(line, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 1)
        scale = 0.55 * min(1.0, max(1, panel_width - 20) / max(1, text_width))
        cv2.putText(frame, line, (18, y), cv2.FONT_HERSHEY_SIMPLEX, scale, color, 1, cv2.LINE_AA)


def main() -> None:
    parser = argparse.ArgumentParser(description="AirControl stage 3: gesture state preview")
    parser.add_argument("--camera", type=int, default=0, help="camera index")
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL, help="Hand Landmarker model")
    args = parser.parse_args()
    config = Config(camera_index=args.camera)
    detector = GestureDetector(
        pinch_on=config.pinch_on_distance,
        pinch_off=config.pinch_off_distance,
        stable_frames=config.gesture_stable_frames,
        finger_min_angle=config.finger_min_angle,
        middle_finger_angle_hysteresis=config.middle_finger_angle_hysteresis,
        middle_stable_frames=config.middle_stable_frames,
    )
    recent_events: deque[str] = deque(maxlen=3)

    def draw_overlay(frame, hand, fps, model_path):
        height, width = frame.shape[:2]
        state = detector.update(hand, frame_size=(width, height))
        for event in state.events:
            recent_events.appendleft(event)
            print(event, flush=True)
        draw_status(frame, hand, fps, state, config, recent_events)

    run_preview(config, args.model, draw_overlay, "AirControl - Stage 3 Gesture Preview")


if __name__ == "__main__":
    main()
