import unittest
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from aircontrol.config import Config
from aircontrol.cursor_mapper import CursorMapper
from aircontrol.gesture_detector import Gesture, GestureDetector, GestureState
from aircontrol.stage4_cursor_preview import CursorPreview, draw_status
from tests.test_gesture_detector import make_hand


def preview_hand(**kwargs):
    hand = make_hand(**kwargs)
    hand.landmarks = tuple(SimpleNamespace(x=x, y=y, z=z) for x, y, z in hand.points)
    return hand


class CursorPreviewTests(unittest.TestCase):
    def setUp(self):
        self.mapper = CursorMapper((1920, 1080))
        self.preview = CursorPreview(self.mapper)
        self.detector = GestureDetector(0.34, 0.42, stable_frames=3)

    def update(self, hand):
        state = self.detector.update(hand)
        position = self.preview.update(hand, state)
        return state, position

    def test_first_move_initializes_exactly_on_confirmation_frame(self):
        hand = preview_hand()
        for _ in range(2):
            state, position = self.update(hand)
            self.assertEqual(state.candidate, Gesture.MOVE)
            self.assertEqual(state.gesture, Gesture.NONE)
            self.assertIsNone(position)
        state, position = self.update(hand)
        self.assertEqual(state.events, ("MOVE_START",))
        self.assertIsNotNone(position)
        self.assertAlmostEqual(position.x, (0.4 - 0.15) / 0.7 * 1919)
        self.assertAlmostEqual(position.y, (0.2 - 0.15) / 0.7 * 1079)

    def test_nonmove_candidate_immediately_clears_display_and_mapper(self):
        for kwargs in ({"middle_up": True}, {"pinch_ratio": 0.3}, {"index_up": False}):
            with self.subTest(kwargs=kwargs):
                self.detector.reset()
                hand = preview_hand()
                for _ in range(3):
                    self.update(hand)
                state, position = self.update(preview_hand(**kwargs))
                if kwargs.get("middle_up"):
                    # A single middle-finger outlier must keep cursor tracking.
                    self.assertEqual(state.candidate, Gesture.MOVE)
                    self.assertIsNotNone(position)
                    state, position = self.update(preview_hand(**kwargs))
                self.assertEqual(state.gesture, Gesture.MOVE)
                self.assertNotEqual(state.candidate, Gesture.MOVE)
                self.assertIsNone(position)
                self.assertIsNone(self.mapper.last_position)

    def test_hand_loss_and_reentry_do_not_reuse_old_coordinates(self):
        hand = preview_hand()
        for _ in range(3):
            self.update(hand)
        self.assertIsNotNone(self.mapper.last_position)
        _, position = self.update(None)
        self.assertIsNone(position)
        self.assertIsNone(self.mapper.last_position)
        # Translate all landmarks together to preserve the MOVE geometry.
        moved = preview_hand()
        moved.points = [(x + 0.2, y + 0.2, z) for x, y, z in moved.points]
        moved.landmarks = tuple(SimpleNamespace(x=x, y=y, z=z) for x, y, z in moved.points)
        for _ in range(2):
            _, position = self.update(moved)
            self.assertIsNone(position)
        _, position = self.update(moved)
        self.assertAlmostEqual(position.x, (0.6 - 0.15) / 0.7 * 1919)
        self.assertAlmostEqual(position.y, (0.4 - 0.15) / 0.7 * 1079)

    def test_confirmed_nonmove_never_exposes_previous_position(self):
        for gesture in (Gesture.NONE, Gesture.PINCH, Gesture.SCROLL):
            with self.subTest(gesture=gesture):
                self.mapper.update(0.5, 0.5)
                state = GestureState(gesture=gesture, candidate=gesture)
                self.assertIsNone(self.preview.update(preview_hand(), state))
                self.assertIsNone(self.mapper.last_position)

    def test_paused_render_has_no_coordinate_or_screen_dot(self):
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        hand = preview_hand()
        state = GestureState(gesture=Gesture.MOVE, candidate=Gesture.SCROLL)
        with patch("aircontrol.stage4_cursor_preview.cv2.putText") as text, patch(
            "aircontrol.stage4_cursor_preview.cv2.circle"
        ) as circles:
            draw_status(frame, hand, 20, state, Config(), (1920, 1080), None, [])
        labels = [call.args[1] for call in text.call_args_list]
        self.assertIn("Cursor: PAUSED", labels)
        self.assertIn("Mapped: -", labels)
        self.assertIn("Target: -", labels)
        # Four operation-region corners and one index-tip ring, with no screen dot.
        self.assertEqual(circles.call_count, 5)


if __name__ == "__main__":
    unittest.main()
