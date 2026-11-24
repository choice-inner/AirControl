import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

from click_drag_controller import ClickDragController, ClickDragMode
from config import Config
from cursor_mapper import CursorMapper
from gesture_detector import GestureDetector
from stage5_click_drag_preview import Stage5Session
from stage2_hand_preview import DEFAULT_MODEL, run_preview
from test_gesture_detector import make_hand


def preview_hand(pinch_ratio=0.8):
    hand = make_hand(pinch_ratio=pinch_ratio)
    # Detector corrects x/z by width/height; undo that for a 640x480 fixture.
    hand.landmarks = tuple(SimpleNamespace(x=x * 0.75, y=y, z=z * 0.75) for x, y, z in hand.points)
    hand.point = lambda index: (
        hand.landmarks[index].x,
        hand.landmarks[index].y,
        hand.landmarks[index].z,
    )
    return hand


def translated_hand(hand, dx, dy):
    translated = make_hand()
    translated.points = [(x + dx, y + dy, z) for x, y, z in hand.points]
    return preview_hand_from(translated)


def preview_hand_from(hand):
    hand.landmarks = tuple(SimpleNamespace(x=x * 0.75, y=y, z=z * 0.75) for x, y, z in hand.points)
    hand.point = lambda index: (
        hand.landmarks[index].x,
        hand.landmarks[index].y,
        hand.landmarks[index].z,
    )
    return hand


class Stage5SessionTests(unittest.TestCase):
    def setUp(self):
        config = Config()
        self.session = Stage5Session(
            GestureDetector(config.pinch_on_distance, config.pinch_off_distance, config.gesture_stable_frames),
            CursorMapper((1000, 1000), max_speed=100, margin_x=0, margin_y=0),
            ClickDragController(
                config.click_cooldown,
                config.click_max_duration,
                config.drag_start_distance_px,
                config.drag_move_epsilon_px,
            ),
        )

    def update(self, hand, timestamp):
        return self.session.update(hand, (640, 480), timestamp)

    def test_stable_move_then_short_pinch_release_emits_one_click(self):
        hand = preview_hand()
        for index in range(3):
            self.update(hand, index / 30)
        events = []
        for index in range(3, 6):
            _, _, current = self.update(preview_hand(0.3), index / 30)
            events.extend(current)
        self.assertIn("PINCH_START", [event.kind for event in events])
        for index in range(6, 9):
            _, _, current = self.update(hand, index / 30)
            events.extend(current)
        self.assertEqual([event.kind for event in events].count("CLICK"), 1)
        self.assertEqual(self.session.controller.mode, ClickDragMode.IDLE)

    def test_lost_hand_while_pinching_never_emits_click(self):
        for index in range(3):
            self.update(preview_hand(), index / 30)
        for index in range(3, 6):
            self.update(preview_hand(0.3), index / 30)
        _, position, events = self.update(None, 0.2)
        self.assertIsNone(position)
        self.assertNotIn("CLICK", [event.kind for event in events])
        self.assertEqual([event.kind for event in events], ["PINCH_CANCEL", "RELEASE_ALL"])
        self.assertEqual(self.session.controller.mode, ClickDragMode.IDLE)

    def test_pinch_motion_starts_drag_and_release_does_not_click(self):
        for index in range(3):
            self.update(preview_hand(), index / 30)
        for index in range(3, 6):
            self.update(preview_hand(0.3), index / 30)
        events = []
        for index in range(6, 10):
            _, _, current = self.update(translated_hand(preview_hand(0.3), 0.12, 0), index / 30)
            events.extend(current)
        self.assertIn("DRAG_START", [event.kind for event in events])
        self.assertEqual(self.session.controller.mode, ClickDragMode.DRAGGING)
        first_release_position = None
        # Drag release now freezes through a 120ms candidate grace interval.
        for index in range(10, 15):
            _, position, current = self.update(translated_hand(preview_hand(), 0.2, 0), index / 30)
            if index == 10:
                first_release_position = position
            if index in (10, 11):
                self.assertEqual(position, first_release_position)
            events.extend(current)
        self.assertEqual([event.kind for event in events].count("DRAG_END"), 1)
        self.assertNotIn("CLICK", [event.kind for event in events])
        self.assertEqual(self.session.controller.mode, ClickDragMode.IDLE)

    def test_startup_pinch_is_ignored_until_stable_move(self):
        for index in range(6):
            _, _, events = self.update(preview_hand(0.3), index / 30)
            self.assertEqual(events, ())
            self.assertFalse(self.session.controller.button_down)
        for index in range(6, 9):
            self.update(preview_hand(), index / 30)
        events = []
        for index in range(9, 12):
            _, _, current = self.update(preview_hand(0.3), index / 30)
            events.extend(current)
        self.assertIn("PINCH_START", [event.kind for event in events])

    def test_invalid_landmarks_and_exit_release_active_action(self):
        for index in range(3):
            self.update(preview_hand(), index / 30)
        for index in range(3, 6):
            self.update(preview_hand(0.3), index / 30)
        active = self.session.controller.button_down
        self.assertTrue(active)
        invalid = preview_hand(0.3)
        invalid.landmarks = invalid.landmarks[:8] + (SimpleNamespace(x=float("nan"), y=0, z=0),) + invalid.landmarks[9:]
        _, position, events = self.update(invalid, 0.2)
        self.assertIsNone(position)
        self.assertEqual([event.kind for event in events], ["PINCH_CANCEL", "RELEASE_ALL"])
        self.assertFalse(self.session.controller.button_down)

        for index in range(6, 9):
            self.update(preview_hand(), index / 30)
        for index in range(9, 12):
            self.update(preview_hand(0.3), index / 30)
        events = self.session.cleanup(0.5, "EXIT")
        self.assertEqual([event.kind for event in events], ["PINCH_CANCEL", "RELEASE_ALL"])
        self.assertEqual(events[0].reason, "EXIT")
        self.assertFalse(self.session.controller.button_down)


class PreviewCleanupTests(unittest.TestCase):
    def test_exit_callback_runs_before_tracker_close_even_on_overlay_error(self):
        for overlay_raises in (False, True):
            with self.subTest(overlay_raises=overlay_raises):
                order = []
                frame = np.zeros((16, 16, 3), dtype=np.uint8)
                capture = Mock()
                capture.isOpened.return_value = True
                capture.read.return_value = (True, frame)
                capture.release.side_effect = lambda: order.append("camera_release")
                tracker = Mock()
                tracker.process.return_value = None
                tracker.close.side_effect = lambda: order.append("tracker_close")
                overlay = Mock(side_effect=RuntimeError("overlay failed") if overlay_raises else None)

                with (
                    patch("stage2_hand_preview.cv2.VideoCapture", return_value=capture),
                    patch("stage2_hand_preview.cv2.flip", side_effect=lambda image, _: image),
                    patch("stage2_hand_preview.cv2.imshow"),
                    patch("stage2_hand_preview.cv2.waitKey", return_value=ord("q")),
                    patch("stage2_hand_preview.cv2.destroyAllWindows"),
                    patch("stage2_hand_preview.HandTracker", return_value=tracker),
                ):
                    if overlay_raises:
                        with self.assertRaisesRegex(RuntimeError, "overlay failed"):
                            run_preview(Config(), DEFAULT_MODEL, overlay, on_exit=lambda: order.append("cleanup"))
                    else:
                        run_preview(Config(), DEFAULT_MODEL, overlay, on_exit=lambda: order.append("cleanup"))

                self.assertLess(order.index("cleanup"), order.index("camera_release"))
                self.assertLess(order.index("camera_release"), order.index("tracker_close"))


if __name__ == "__main__":
    unittest.main()
