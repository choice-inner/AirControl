from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision


@dataclass(frozen=True)
class Hand:
    """One detected hand with normalized MediaPipe landmark coordinates."""

    landmarks: tuple
    handedness: str
    score: float

    def point(self, index: int) -> tuple[float, float, float]:
        point = self.landmarks[index]
        return point.x, point.y, point.z


class HandTracker:
    def __init__(
        self,
        model_path: str | Path,
        detection_confidence: float,
        presence_confidence: float,
        tracking_confidence: float,
        max_hands: int = 1,
    ):
        model_path = Path(model_path)
        if not model_path.is_file():
            raise FileNotFoundError(f"Hand Landmarker model not found: {model_path}")

        options = vision.HandLandmarkerOptions(
            base_options=python.BaseOptions(model_asset_path=str(model_path)),
            running_mode=vision.RunningMode.VIDEO,
            num_hands=max_hands,
            min_hand_detection_confidence=detection_confidence,
            min_hand_presence_confidence=presence_confidence,
            min_tracking_confidence=tracking_confidence,
        )
        self._detector = vision.HandLandmarker.create_from_options(options)
        self._last_timestamp_ms = -1

    def process(self, frame_bgr, timestamp_ms: int) -> Hand | None:
        if timestamp_ms <= self._last_timestamp_ms:
            timestamp_ms = self._last_timestamp_ms + 1
        self._last_timestamp_ms = timestamp_ms

        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        result = self._detector.detect_for_video(image, timestamp_ms)
        if not result.hand_landmarks:
            return None

        handedness = "Unknown"
        score = 0.0
        if result.handedness and result.handedness[0]:
            classification = result.handedness[0][0]
            handedness = classification.category_name or str(classification.display_name or "Unknown")
            score = float(classification.score)
        return Hand(tuple(result.hand_landmarks[0]), handedness, score)

    def close(self) -> None:
        self._detector.close()
