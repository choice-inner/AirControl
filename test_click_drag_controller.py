import math
import unittest

from click_drag_controller import ClickDragController, ClickDragMode
from cursor_mapper import CursorPosition
from gesture_detector import Gesture


def position(x, y):
    return CursorPosition(x, y, x / 1000, y / 1000, x, y)


class ClickDragControllerTests(unittest.TestCase):
    def make_controller(self, **kwargs):
        defaults = {
            "click_cooldown": 0.35,
            "click_max_duration": 0.8,
            "drag_start_distance_px": 24,
            "drag_move_epsilon_px": 2,
        }
        defaults.update(kwargs)
        return ClickDragController(**defaults)

    def test_short_pinch_release_clicks_once_and_releases_all(self):
        controller = self.make_controller()
        started = controller.update(Gesture.PINCH, position(200, 300), 1.0)
        self.assertEqual([event.kind for event in started], ["PINCH_START"])
        self.assertEqual(controller.mode, ClickDragMode.PINCHING)
        controller.update(Gesture.PINCH, position(204, 303), 1.1)
        released = controller.update(Gesture.MOVE, position(205, 304), 1.2)
        self.assertEqual([event.kind for event in released], ["CLICK", "RELEASE_ALL"])
        self.assertEqual((released[0].x, released[0].y), (200, 300))
        self.assertEqual(controller.mode, ClickDragMode.IDLE)
        self.assertFalse(controller.button_down)
        self.assertEqual(controller.update(Gesture.MOVE, position(210, 305), 1.3), ())

    def test_click_cooldown_suppresses_repeated_click(self):
        controller = self.make_controller()
        controller.update(Gesture.PINCH, position(100, 100), 1.0)
        first = controller.update(Gesture.MOVE, position(100, 100), 1.1)
        self.assertEqual([event.kind for event in first], ["CLICK", "RELEASE_ALL"])
        controller.update(Gesture.PINCH, position(100, 100), 1.2)
        second = controller.update(Gesture.MOVE, position(100, 100), 1.3)
        self.assertEqual([event.kind for event in second], ["CLICK_SUPPRESSED", "RELEASE_ALL"])
        self.assertEqual(second[0].reason, "COOLDOWN")

    def test_movement_threshold_starts_drag_once_and_filters_tiny_moves(self):
        controller = self.make_controller()
        controller.update(Gesture.PINCH, position(100, 100), 1.0)
        self.assertEqual(controller.update(Gesture.PINCH, position(123, 100), 1.1), ())
        started = controller.update(Gesture.PINCH, position(124, 100), 1.2)
        self.assertEqual([event.kind for event in started], ["DRAG_START", "DRAG_MOVE"])
        self.assertEqual(controller.mode, ClickDragMode.DRAGGING)
        self.assertEqual(controller.update(Gesture.PINCH, position(125, 100), 1.3), ())
        moved = controller.update(Gesture.PINCH, position(127, 100), 1.4)
        self.assertEqual([event.kind for event in moved], ["DRAG_MOVE"])

    def test_subpixel_motion_accumulates_against_last_emitted_drag_position(self):
        controller = self.make_controller(drag_move_epsilon_px=2)
        controller.update(Gesture.PINCH, position(100, 100), 1.0)
        controller.update(Gesture.PINCH, position(124, 100), 1.1)
        self.assertEqual(controller.update(Gesture.PINCH, position(125, 100), 1.2), ())
        self.assertEqual(controller.update(Gesture.PINCH, position(126, 100), 1.3)[0].kind, "DRAG_MOVE")

    def test_drag_release_never_clicks(self):
        controller = self.make_controller()
        controller.update(Gesture.PINCH, position(100, 100), 1.0)
        controller.update(Gesture.PINCH, position(130, 100), 1.1)
        ended = controller.update(Gesture.MOVE, position(140, 110), 1.2)
        self.assertEqual([event.kind for event in ended], ["DRAG_END", "RELEASE_ALL"])
        self.assertNotIn("CLICK", [event.kind for event in ended])
        self.assertEqual((ended[0].x, ended[0].y), (140, 110))
        self.assertEqual(controller.mode, ClickDragMode.IDLE)
        self.assertFalse(controller.button_down)

    def test_slow_or_moved_pinch_is_cancelled_instead_of_clicked(self):
        controller = self.make_controller(click_max_duration=0.4)
        controller.update(Gesture.PINCH, position(100, 100), 1.0)
        too_long = controller.update(Gesture.MOVE, position(100, 100), 1.5)
        self.assertEqual([event.kind for event in too_long], ["PINCH_CANCEL", "RELEASE_ALL"])

        controller.update(Gesture.PINCH, position(100, 100), 2.0)
        moved = controller.update(Gesture.MOVE, position(130, 100), 2.1)
        self.assertEqual([event.kind for event in moved], ["PINCH_CANCEL", "RELEASE_ALL"])
        self.assertEqual(moved[0].reason, "TOO_LONG_OR_MOVED")

    def test_scroll_or_idle_transition_cancels_pinch_without_click(self):
        for gesture in (Gesture.SCROLL, Gesture.NONE):
            with self.subTest(gesture=gesture):
                controller = self.make_controller()
                controller.update(Gesture.PINCH, position(100, 100), 1.0)
                ended = controller.update(gesture, position(100, 100), 1.1)
                self.assertEqual([event.kind for event in ended], ["PINCH_CANCEL", "RELEASE_ALL"])
                self.assertEqual(ended[0].reason, f"GESTURE_{gesture.value}")

    def test_lost_hand_cancels_pinch_and_closes_drag(self):
        controller = self.make_controller()
        controller.update(Gesture.PINCH, position(100, 100), 1.0)
        cancelled = controller.reset(1.1, reason="HAND_LOST")
        self.assertEqual([event.kind for event in cancelled], ["PINCH_CANCEL", "RELEASE_ALL"])
        self.assertEqual(cancelled[-1].reason, "HAND_LOST")
        self.assertEqual(controller.mode, ClickDragMode.IDLE)
        self.assertFalse(controller.button_down)

    def test_invalid_position_cancels_active_pinch(self):
        controller = self.make_controller()
        controller.update(Gesture.PINCH, position(100, 100), 1.0)
        invalid = CursorPosition(math.nan, 100, 0, 0, 0, 0)
        events = controller.update(Gesture.PINCH, invalid, 1.1)
        self.assertEqual([event.kind for event in events], ["PINCH_CANCEL", "RELEASE_ALL"])
        self.assertEqual(events[0].reason, "INVALID_POSITION")
        self.assertFalse(controller.button_down)

    def test_lost_hand_closes_drag(self):
        controller = self.make_controller()
        controller.update(Gesture.PINCH, position(100, 100), 2.0)
        controller.update(Gesture.PINCH, position(130, 100), 2.1)
        cancelled = controller.reset(2.2, reason="HAND_LOST")
        self.assertEqual([event.kind for event in cancelled], ["DRAG_END", "RELEASE_ALL"])
        self.assertEqual(cancelled[0].reason, "HAND_LOST")
        self.assertEqual(controller.mode, ClickDragMode.IDLE)
        self.assertFalse(controller.button_down)

    def test_reset_while_idle_is_silent(self):
        controller = self.make_controller()
        self.assertEqual(controller.reset(1.0, reason="EXIT"), ())

    def test_invalid_parameters_and_timestamps_are_rejected(self):
        for kwargs in (
            {"click_cooldown": -1},
            {"click_max_duration": math.inf},
            {"drag_start_distance_px": 0},
            {"drag_move_epsilon_px": -1},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.make_controller(**kwargs)
        controller = self.make_controller()
        with self.assertRaises(ValueError):
            controller.update(Gesture.PINCH, None, math.nan)
        controller.update(Gesture.PINCH, None, 2.0)
        with self.assertRaises(ValueError):
            controller.update(Gesture.MOVE, None, 1.0)


if __name__ == "__main__":
    unittest.main()
