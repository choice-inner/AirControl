"""Offline packaging check; never opens a camera or creates an input backend."""
from pathlib import Path

import cv2
import mediapipe
import numpy as np

from .hand_tracker import HandTracker


def run_self_check(model_path: Path) -> None:
    model_path = Path(model_path)
    print(f"OpenCV: {cv2.__version__} | MediaPipe: {mediapipe.__version__}", flush=True)
    print(f"Model: {model_path}", flush=True)
    tracker = HandTracker(model_path, 0.7, 0.7, 0.7)
    try:
        result = tracker.process(np.zeros((480, 640, 3), dtype=np.uint8), 1)
        if result is not None:
            raise RuntimeError("Unexpected hand detection on the blank self-check image")
    finally:
        tracker.close()
    print("SELF-CHECK OK: model loaded and blank-frame inference completed. "
          "Camera and mouse input were not used.", flush=True)
