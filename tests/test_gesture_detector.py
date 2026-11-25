import math
import unittest
from dataclasses import dataclass

from aircontrol.gesture_detector import Gesture, GestureDetector


@dataclass
class SyntheticHand:
    points: list[tuple[float, float, float]]

    def point(self, index):
        return self.points[index]


def make_hand(index_up=True, middle_up=False, pinch_ratio=0.8):
    points = [(0.5, 0.6, 0.0)] * 21
    points[0] = (0.5, 0.9, 0.0)
    for mcp, x, extended in ((5, 0.4, index_up), (9, 0.5, middle_up)):
        points[mcp] = (x, 0.6, 0.0)
        if extended:
            points[mcp + 1:mcp + 4] = [
                (x, 0.45, 0.0), (x, 0.32, 0.0), (x, 0.2, 0.0),
            ]
        else:
            points[mcp + 1:mcp + 4] = [
                (x, 0.46, 0.0), (x + 0.04, 0.54, 0.0), (x + 0.01, 0.6, 0.0),
            ]
    # Wrist-to-middle-MCP distance is 0.3 in this fixture.
    tip = points[8]
    points[4] = (tip[0] + pinch_ratio * 0.3, tip[1], tip[2])
    return SyntheticHand(points)


def middle_angle_hand(angle):
    hand = make_hand(middle_up=True)
    # Bend at the middle PIP while keeping the DIP straight and tip extended.
    turn = math.radians(180 - angle)
    for index, length in ((11, 0.13), (12, 0.25)):
        hand.points[index] = (0.5 + length * math.sin(turn), 0.45 - length * math.cos(turn), 0.0)
    return hand


class GestureDetectorTests(unittest.TestCase):
    def setUp(self):
        self.detector = GestureDetector(0.34, 0.42, stable_frames=3)

    def settle(self, hand, frame_size=(1, 1)):
        for _ in range(3):
            state = self.detector.update(hand, frame_size)
        return state

    def test_move_requires_three_consecutive_frames(self):
        hand = make_hand()
        for frames in (1, 2):
            state = self.detector.update(hand)
            self.assertEqual(state.gesture, Gesture.NONE)
            self.assertEqual(state.candidate, Gesture.MOVE)
            self.assertEqual(state.candidate_frames, frames)
            self.assertEqual(state.events, ())
        state = self.detector.update(hand)
        self.assertEqual(state.gesture, Gesture.MOVE)
        self.assertTrue(state.changed)
        self.assertEqual(state.events, ("MOVE_START",))
        self.assertEqual(self.detector.update(hand).events, ())

    def test_one_frame_noise_does_not_switch_or_accumulate(self):
        self.settle(make_hand())
        scroll = make_hand(middle_up=True)
        self.assertEqual(self.detector.update(scroll).gesture, Gesture.MOVE)
        self.detector.update(make_hand())
        state = self.detector.update(scroll)
        self.assertEqual(state.gesture, Gesture.MOVE)
        self.assertEqual(state.candidate, Gesture.MOVE)
        self.assertFalse(state.middle_up)
        state = self.detector.update(scroll)
        self.assertEqual(state.candidate_frames, 1)
        self.assertEqual(state.candidate, Gesture.SCROLL)
        self.detector.update(scroll)
        state = self.detector.update(scroll)
        self.assertEqual(state.gesture, Gesture.SCROLL)
        self.assertEqual(state.events, ("MOVE_END", "SCROLL_START"))

    def test_middle_state_requires_consecutive_frames_before_scroll(self):
        self.settle(make_hand())
        scroll = make_hand(middle_up=True)
        first = self.detector.update(scroll)
        self.assertFalse(first.middle_up)
        self.assertEqual(first.gesture, Gesture.MOVE)
        second = self.detector.update(scroll)
        self.assertTrue(second.middle_up)
        self.assertEqual(second.gesture, Gesture.MOVE)
        state = self.settle(scroll)
        self.assertEqual(state.gesture, Gesture.SCROLL)

    def test_middle_state_hysteresis_holds_through_angle_band(self):
        self.settle(make_hand())
        for angle in (154, 156, 159, 151) * 3:
            state = self.detector.update(middle_angle_hand(angle))
            self.assertFalse(state.middle_up)
            self.assertEqual(state.candidate, Gesture.MOVE)
            self.assertEqual(state.gesture, Gesture.MOVE)
        self.settle(make_hand(middle_up=True))
        for angle in (159, 154, 151, 156) * 3:
            state = self.detector.update(middle_angle_hand(angle))
            self.assertTrue(state.middle_up)
            self.assertEqual(state.gesture, Gesture.SCROLL)

    def test_middle_fold_requires_consecutive_frames_and_returns_to_move(self):
        scroll = make_hand(middle_up=True)
        for _ in range(4):
            self.detector.update(scroll)
        # An isolated folded estimate must not accumulate across interruptions.
        for hand in (make_hand(), scroll, make_hand()):
            state = self.detector.update(hand)
            self.assertTrue(state.middle_up)
            self.assertEqual(state.candidate, Gesture.SCROLL)
        state = self.detector.update(make_hand())
        self.assertFalse(state.middle_up)
        self.assertEqual(state.candidate, Gesture.MOVE)
        self.assertEqual(self.settle(make_hand()).gesture, Gesture.MOVE)

    def test_middle_history_is_cleared_on_hand_loss_and_invalid_points(self):
        for invalid_hand in (None, SyntheticHand([(math.nan, 0, 0)] * 21)):
            self.detector.reset()
            for _ in range(4):
                self.detector.update(make_hand(middle_up=True))
            state = self.detector.update(invalid_hand)
            self.assertEqual(state.gesture, Gesture.NONE)
            self.assertFalse(state.middle_up)
            state = self.detector.update(middle_angle_hand(155))
            self.assertFalse(state.middle_up)
            self.assertEqual(state.candidate, Gesture.MOVE)

    def test_pinch_has_priority_over_move_and_scroll(self):
        for middle_up in (False, True):
            with self.subTest(middle_up=middle_up):
                self.detector.reset()
                self.settle(make_hand(middle_up=middle_up))
                state = self.settle(make_hand(middle_up=middle_up, pinch_ratio=0.3))
                self.assertEqual(state.gesture, Gesture.PINCH)
                self.assertTrue(state.pinch_active)
                self.assertEqual(state.events[-1], "PINCH_START")

    def test_pinch_hysteresis_and_stable_release(self):
        self.settle(make_hand(pinch_ratio=0.3))
        state = self.settle(make_hand(pinch_ratio=0.38))
        self.assertEqual(state.gesture, Gesture.PINCH)
        self.assertEqual(state.events, ())
        released = make_hand(pinch_ratio=0.5)
        self.assertEqual(self.detector.update(released).gesture, Gesture.PINCH)
        self.assertEqual(self.detector.update(released).gesture, Gesture.PINCH)
        state = self.detector.update(released)
        self.assertFalse(state.pinch_active)
        self.assertEqual(state.events, ("PINCH_END", "MOVE_START"))
        state = self.settle(make_hand(pinch_ratio=0.38))
        self.assertEqual(state.gesture, Gesture.MOVE)

    def test_hand_loss_resets_immediately_and_only_emits_one_end(self):
        self.settle(make_hand(pinch_ratio=0.3))
        state = self.detector.update(None)
        self.assertEqual(state.gesture, Gesture.NONE)
        self.assertEqual(state.candidate_frames, 0)
        self.assertFalse(state.pinch_active)
        self.assertEqual(state.events, ("PINCH_END",))
        self.assertEqual(self.detector.update(None).events, ())
        state = self.detector.update(make_hand(pinch_ratio=0.38))
        self.assertEqual(state.gesture, Gesture.NONE)
        self.assertEqual(state.candidate, Gesture.MOVE)
        self.assertEqual(state.candidate_frames, 1)

    def test_folded_fingers_return_to_idle(self):
        self.settle(make_hand())
        state = self.settle(make_hand(index_up=False))
        self.assertEqual(state.gesture, Gesture.NONE)
        self.assertEqual(state.events, ("MOVE_END",))

    def test_middle_finger_alone_is_idle(self):
        state = self.settle(make_hand(index_up=False, middle_up=True))
        self.assertEqual(state.gesture, Gesture.NONE)

    def test_scale_translation_and_mirroring_preserve_classification(self):
        for scale in (0.4, 1.5, -0.7):
            with self.subTest(scale=scale):
                hand = make_hand(middle_up=True, pinch_ratio=0.3)
                hand.points = [tuple(scale * v + 0.2 for v in p) for p in hand.points]
                self.detector.reset()
                state = self.settle(hand)
                self.assertEqual(state.gesture, Gesture.PINCH)
                self.assertAlmostEqual(state.pinch_ratio, 0.3)
                self.assertTrue(state.index_up)
                self.assertTrue(state.middle_up)

    def test_image_aspect_ratio_is_corrected(self):
        for width, height in ((1280, 720), (640, 480), (480, 640)):
            with self.subTest(size=(width, height)):
                hand = make_hand(pinch_ratio=0.3)
                aspect = width / height
                hand.points = [(x / aspect, y, z / aspect) for x, y, z in hand.points]
                self.detector.reset()
                state = self.settle(hand, (width, height))
                self.assertEqual(state.gesture, Gesture.PINCH)
                self.assertAlmostEqual(state.pinch_ratio, 0.3)

    def test_invalid_landmarks_reset_active_state(self):
        for invalid in (math.nan, math.inf):
            with self.subTest(invalid=invalid):
                self.settle(make_hand())
                hand = make_hand()
                hand.points[8] = (invalid, 0.2, 0.0)
                state = self.detector.update(hand)
                self.assertEqual(state.gesture, Gesture.NONE)
                self.assertEqual(state.events, ("MOVE_END",))
        self.settle(make_hand())
        hand = make_hand()
        hand.points[9] = hand.points[0]
        self.assertEqual(self.detector.update(hand).gesture, Gesture.NONE)

    def test_invalid_configuration_is_rejected(self):
        for args in ((0.42, 0.34), (0, 0.42), (0.34, math.inf)):
            with self.subTest(args=args), self.assertRaises(ValueError):
                GestureDetector(*args)
        with self.assertRaises(ValueError):
            GestureDetector(0.34, 0.42, stable_frames=0)
        with self.assertRaises(ValueError):
            GestureDetector(0.34, 0.42, finger_min_angle=180)
        for kwargs in (
            {"middle_finger_angle_hysteresis": 0},
            {"middle_finger_angle_hysteresis": 25},
            {"middle_finger_angle_hysteresis": math.nan},
            {"middle_stable_frames": 0},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                GestureDetector(0.34, 0.42, **kwargs)
        with self.assertRaises(ValueError):
            self.detector.update(make_hand(), (0, 720))


if __name__ == "__main__":
    unittest.main()
