from __future__ import annotations

import argparse
import time
from pathlib import Path

import cv2

from .config import Config
from .hand_tracker import HandTracker


PROJECT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_MODEL = PROJECT_DIR / "models" / "hand_landmarker.task"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="AirControl stage 2: hand landmark preview")
    parser.add_argument("--camera", type=int, default=0, help="camera index")
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL, help="Hand Landmarker .task model")
    return parser.parse_args()


def draw_hand(frame, hand) -> None:
    if hand is None:
        return
    height, width = frame.shape[:2]
    for start, end in (
        (0, 1), (1, 2), (2, 3), (3, 4),
        (0, 5), (5, 6), (6, 7), (7, 8),
        (5, 9), (9, 10), (10, 11), (11, 12),
        (9, 13), (13, 14), (14, 15), (15, 16),
        (13, 17), (17, 18), (18, 19), (19, 20),
        (0, 17),
    ):
        first = hand.landmarks[start]
        second = hand.landmarks[end]
        cv2.line(
            frame,
            (round(first.x * width), round(first.y * height)),
            (round(second.x * width), round(second.y * height)),
            (80, 220, 80),
            2,
            cv2.LINE_AA,
        )
    for index, point in enumerate(hand.landmarks):
        center = (round(point.x * width), round(point.y * height))
        color = (0, 220, 255) if index in (4, 8, 12) else (255, 180, 0)
        cv2.circle(frame, center, 5, color, -1, cv2.LINE_AA)


def draw_status(frame, hand, fps: float, model_path: Path) -> None:
    status = "HAND DETECTED" if hand else "NO HAND"
    color = (70, 220, 70) if hand else (0, 180, 255)
    cv2.rectangle(frame, (12, 12), (520, 138), (25, 25, 25), -1)
    lines = [
        f"Stage 2 | {status}",
        f"Hand: {hand.handedness if hand else '-'}  score: {hand.score:.2f}" if hand else "Hand: -",
        f"FPS: {fps:.1f}",
        f"Model: {model_path.name}",
        "Q / Esc: quit",
    ]
    for index, line in enumerate(lines):
        cv2.putText(
            frame,
            line,
            (24, 38 + index * 22),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.56,
            color,
            1,
            cv2.LINE_AA,
        )


def main() -> None:
    args = parse_args()
    config = Config(camera_index=args.camera)
    run_preview(config, args.model)


def run_preview(
    config: Config,
    model_path: Path,
    draw_overlay=draw_status,
    window_title: str = "AirControl - Stage 2 Hand Preview",
    on_exit=None,
    on_key=None,
    should_stop=None,
) -> None:
    if not model_path.is_file():
        raise FileNotFoundError(f"Hand Landmarker model not found: {model_path}")
    capture = cv2.VideoCapture(config.camera_index)
    capture.set(cv2.CAP_PROP_FRAME_WIDTH, config.frame_width)
    capture.set(cv2.CAP_PROP_FRAME_HEIGHT, config.frame_height)
    if not capture.isOpened():
        capture.release()
        raise RuntimeError(f"Cannot open camera {config.camera_index}")

    tracker = None
    started = time.monotonic()
    frame_count = 0
    fps = 0.0

    try:
        tracker = HandTracker(
            model_path=model_path,
            detection_confidence=config.detection_confidence,
            presence_confidence=config.presence_confidence,
            tracking_confidence=config.tracking_confidence,
            max_hands=config.max_hands,
        )
        while True:
            if should_stop is not None and should_stop():
                break
            ok, frame = capture.read()
            if not ok:
                raise RuntimeError("Camera frame could not be read")
            frame = cv2.flip(frame, 1)
            timestamp_ms = round((time.monotonic() - started) * 1000)
            hand = tracker.process(frame, timestamp_ms)
            draw_hand(frame, hand)

            frame_count += 1
            elapsed = max(time.monotonic() - started, 1e-6)
            fps = frame_count / elapsed
            draw_overlay(frame, hand, fps, model_path)
            cv2.imshow(window_title, frame)

            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27):
                break
            if on_key is not None and on_key(key):
                break
            if cv2.getWindowProperty(window_title, cv2.WND_PROP_VISIBLE) < 1:
                break
    finally:
        try:
            if on_exit is not None:
                on_exit()
        finally:
            try:
                capture.release()
            finally:
                try:
                    cv2.destroyAllWindows()
                finally:
                    if tracker is not None:
                        tracker.close()


if __name__ == "__main__":
    main()
