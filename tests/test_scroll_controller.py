import math
import unittest

from aircontrol.cursor_mapper import CursorPosition
from aircontrol.gesture_detector import Gesture
from aircontrol.scroll_controller import ScrollController, ScrollMode


def position(y):
    return CursorPosition(500, y, 0.5, y / 1000, 500, y)


class ScrollControllerTests(unittest.TestCase):
    def make_controller(self, **kwargs):
        defaults = {"deadzone_px": 18, "step_px": 24, "gain": 2, "max_steps_per_update": 3}
        defaults.update(kwargs)
        return ScrollController(**defaults)

    def test_start_has_no_scroll_until_deadzone_is_crossed(self):
        controller = self.make_controller()
        self.assertEqual(controller.update(Gesture.SCROLL, position(500), 1.0)[0].kind, "SCROLL_START")
        self.assertEqual(controller.update(Gesture.SCROLL, position(490), 1.1), ())
        self.assertEqual(controller.update(Gesture.SCROLL, position(483), 1.2), ())
        event = controller.update(Gesture.SCROLL, position(470), 1.3)[0]
        self.assertEqual(event.kind, "SCROLL_UP")
        self.assertEqual(event.amount, 2)

    def test_down_direction_and_small_motion_accumulation(self):
        controller = self.make_controller(gain=1)
        controller.update(Gesture.SCROLL, position(500), 1.0)
        self.assertEqual(controller.update(Gesture.SCROLL, position(530), 1.1)[0].kind, "SCROLL_DOWN")
        self.assertEqual(controller.update(Gesture.SCROLL, position(540), 1.2), ())
        self.assertEqual(controller.update(Gesture.SCROLL, position(560), 1.3)[0].kind, "SCROLL_DOWN")

    def test_static_input_does_not_repeat_scroll(self):
        controller = self.make_controller()
        controller.update(Gesture.SCROLL, position(500), 1.0)
        for timestamp in (1.1, 1.2, 1.3):
            self.assertEqual(controller.update(Gesture.SCROLL, position(500), timestamp), ())
        self.assertEqual(controller.mode, ScrollMode.SCROLLING)

    def test_gesture_change_ends_scroll_and_next_scroll_reinitializes(self):
        controller = self.make_controller()
        controller.update(Gesture.SCROLL, position(500), 1.0)
        ended = controller.update(Gesture.MOVE, position(400), 1.1)
        self.assertEqual([event.kind for event in ended], ["SCROLL_END"])
        self.assertEqual(ended[0].reason, "GESTURE_MOVE")
        started = controller.update(Gesture.SCROLL, position(400), 1.2)
        self.assertEqual(started[0].kind, "SCROLL_START")

    def test_invalid_position_and_hand_loss_finish_cleanly(self):
        controller = self.make_controller()
        controller.update(Gesture.SCROLL, position(500), 1.0)
        invalid = CursorPosition(0, math.nan, 0, 0, 0, 0)
        ended = controller.update(Gesture.SCROLL, invalid, 1.1)
        self.assertEqual([event.kind for event in ended], ["SCROLL_END"])
        self.assertEqual(ended[0].reason, "INVALID_POSITION")
        self.assertEqual(controller.update(Gesture.NONE, None, 1.2), ())

    def test_large_jump_is_capped(self):
        controller = self.make_controller(gain=1, max_steps_per_update=2)
        controller.update(Gesture.SCROLL, position(500), 1.0)
        event = controller.update(Gesture.SCROLL, position(100), 1.1)[0]
        self.assertEqual(event.amount, 2)
        for timestamp in (1.2, 1.3, 1.4):
            self.assertEqual(controller.update(Gesture.SCROLL, position(100), timestamp), ())

    def test_output_frequency_is_limited_and_reverse_motion_changes_direction(self):
        controller = self.make_controller()
        controller.update(Gesture.SCROLL, position(500), 1.0)
        self.assertEqual(controller.update(Gesture.SCROLL, position(450), 1.03), ())
        self.assertEqual(controller.update(Gesture.SCROLL, position(450), 1.06), ())
        self.assertEqual(controller.update(Gesture.SCROLL, position(450), 1.1)[0].kind, "SCROLL_UP")
        self.assertEqual(controller.update(Gesture.SCROLL, position(480), 1.2)[0].kind, "SCROLL_DOWN")

    def test_frame_stall_reinitializes_without_scrolling(self):
        controller = self.make_controller()
        controller.update(Gesture.SCROLL, position(500), 1.0)
        self.assertEqual(controller.update(Gesture.SCROLL, position(100), 2.0), ())
        self.assertEqual(controller.update(Gesture.SCROLL, position(100), 2.1), ())
        self.assertEqual(controller.update(Gesture.SCROLL, position(130), 2.2)[0].kind, "SCROLL_DOWN")

    def test_invalid_configuration_and_timestamp_are_rejected(self):
        for kwargs in (
            {"deadzone_px": 0}, {"step_px": math.inf}, {"gain": -1}, {"max_steps_per_update": 0},
            {"min_interval": 0}, {"max_sample_gap": math.nan},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.make_controller(**kwargs)
        controller = self.make_controller()
        with self.assertRaises(ValueError):
            controller.update(Gesture.SCROLL, position(500), math.nan)
        controller.update(Gesture.SCROLL, position(500), 1.0)
        with self.assertRaises(ValueError):
            controller.update(Gesture.SCROLL, position(500), 0.9)


if __name__ == "__main__":
    unittest.main()
