import unittest
from unittest.mock import Mock, call

from cursor_mapper import CursorPosition
from gesture_scheme_b import SchemeBGesture, SchemeBState
from scroll_controller import ScrollController
from stage8_b_control import SchemeBControl
from test_gesture_detector import make_hand
from test_stage5_click_drag_preview import preview_hand_from


def cursor(x=100, y=120):
    return CursorPosition(x, y, x / 640, y / 480, x, y)


class FakeSession:
    def __init__(self):
        self.result = (SchemeBState(), None, ())

    def update(self, hand, frame_size):
        return self.result


class SchemeBControlTests(unittest.TestCase):
    def setUp(self):
        self.session = FakeSession()
        self.output = Mock()
        self.control = SchemeBControl(self.session, self.output, ScrollController(), enabled=True)
        self.hand = preview_hand_from(make_hand())
        self.timestamp = 0.0

    def update(self, state, position=None, events=(), hand="valid"):
        self.timestamp += 1 / 30
        self.session.result = state, position, events
        sample = self.hand if hand == "valid" else None
        return self.control.update(sample, (640, 480), self.timestamp)

    def arm(self):
        self.update(SchemeBState())
        self.assertFalse(self.control.await_neutral)
        self.output.reset_mock()

    def test_control_waits_for_neutral_and_moves_only_when_enabled(self):
        self.update(SchemeBState(SchemeBGesture.PINCH_AIM), cursor())
        self.assertEqual(self.output.mock_calls, [])
        self.arm()
        self.update(SchemeBState(SchemeBGesture.PINCH_AIM), cursor())
        self.output.move_to.assert_called_once_with(100, 120)

    def test_click_sends_one_press_and_release(self):
        self.arm()
        self.update(SchemeBState(SchemeBGesture.CLICK_OPEN), cursor(), ("CLICK",))
        self.assertEqual(self.output.mock_calls, [
            call.mouse_down(), call.mouse_up(),
        ])
        self.assertFalse(self.control.button_down)

    def test_drag_and_hand_loss_always_release_button(self):
        self.arm()
        self.update(SchemeBState(SchemeBGesture.DRAG_OPEN), cursor(), ("DRAG_START",))
        self.assertTrue(self.control.button_down)
        self.update(SchemeBState(), cursor(), ("DRAG_END",))
        self.assertFalse(self.control.button_down)
        self.update(SchemeBState(SchemeBGesture.DRAG_OPEN), cursor(), ("DRAG_START",))
        self.update(SchemeBState(), None, ("DRAG_END HAND_LOST",), hand="lost")
        self.assertFalse(self.control.button_down)
        self.assertEqual(self.output.mouse_up.call_count, 2)

    def test_pause_and_emergency_release_and_emergency_is_latched(self):
        self.arm()
        self.update(SchemeBState(SchemeBGesture.DRAG_OPEN), cursor(), ("DRAG_START",))
        self.control.pause(self.timestamp + 0.01)
        self.assertFalse(self.control.button_down)
        self.control.resume(self.timestamp + 0.02)
        self.update(SchemeBState())
        self.update(SchemeBState(SchemeBGesture.DRAG_OPEN), cursor(), ("DRAG_START",))
        self.control.emergency_stop(self.timestamp + 0.01)
        self.control.resume(self.timestamp + 0.02)
        self.assertTrue(self.control.emergency_stopped)
        self.assertFalse(self.control.enabled)


if __name__ == "__main__":
    unittest.main()
