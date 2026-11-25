import unittest
from unittest.mock import Mock, call

from aircontrol.cursor_mapper import CursorPosition
from aircontrol.gesture_scheme_b import SchemeBDetector, SchemeBGesture, SchemeBSession, SchemeBState
from aircontrol.scroll_controller import ScrollController, ScrollEvent
from aircontrol.stage8_b_control import SchemeBControl
from tests.test_gesture_detector import make_hand
from tests.test_stage5_click_drag_preview import preview_hand_from
from tests.test_gesture_scheme_b import open_hand, sample


def cursor(x=100, y=120):
    return CursorPosition(x, y, x / 640, y / 480, x, y)


class FakeSession:
    def __init__(self):
        self.result = (SchemeBState(), None, ())
        self.reset = Mock()

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
        for _ in range(3):
            self.update(SchemeBState())
        self.assertFalse(self.control.await_neutral)
        self.output.reset_mock()

    def test_control_waits_for_neutral_and_moves_only_when_enabled(self):
        self.update(SchemeBState(SchemeBGesture.PINCH_AIM), cursor())
        self.assertEqual(self.output.mock_calls, [])
        self.arm()
        self.update(SchemeBState(SchemeBGesture.PINCH_AIM), cursor())
        self.output.move_to.assert_called_once_with(100, 120)

    def test_neutral_confirmation_requires_three_consecutive_frames(self):
        self.update(SchemeBState())
        self.update(SchemeBState())
        self.assertTrue(self.control.await_neutral)
        self.update(SchemeBState(candidate=SchemeBGesture.PINCH_AIM))
        self.update(SchemeBState())
        self.update(SchemeBState())
        self.assertTrue(self.control.await_neutral)
        self.update(SchemeBState())
        self.assertFalse(self.control.await_neutral)

    def test_click_sends_one_press_and_release(self):
        self.arm()
        self.update(SchemeBState(SchemeBGesture.CLICK_OPEN), cursor(), ("CLICK",))
        self.assertEqual(self.output.mock_calls, [
            call.mouse_down(), call.mouse_up(),
        ])
        self.assertFalse(self.control.button_down)

    def test_real_session_gradual_opening_never_moves_mouse_before_click(self):
        self.control.session = SchemeBSession(SchemeBDetector(3), (1000, 800),
                                              sensitivity=1, smoothing=1)
        neutral = sample(index_up=False)
        now = 0.0

        def feed(hand):
            nonlocal now
            now += 1 / 30
            return self.control.update(hand, (640, 480), now)

        for _ in range(3):
            feed(neutral)
        self.assertFalse(self.control.await_neutral)
        for _ in range(3):
            feed(sample(pinch_ratio=0.3))
        for _ in range(3):
            _, target, _ = feed(sample(pinch_ratio=0.3, dx=0.08))
        # Within pinch hysteresis, variation must not inhibit real movement.
        for step, ratio in enumerate((0.46, 0.40, 0.50), 1):
            state, target, _ = feed(sample(pinch_ratio=ratio, dx=0.08 + step * 0.05))
            self.assertFalse(state.aim_frozen)
        self.output.move_to.assert_called_with(target.x, target.y)
        self.output.reset_mock()
        for ratio in (0.62, 0.66, 0.85, 0.85, 0.85, 0.9):
            _, position, _ = feed(sample(pinch_ratio=ratio))
            self.assertEqual(position, target)
        self.assertEqual(self.output.mock_calls, [call.mouse_down(), call.mouse_up()])

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

    def test_drag_releases_before_scroll_output_on_transition(self):
        self.arm()
        self.update(SchemeBState(SchemeBGesture.DRAG_OPEN), cursor(), ("DRAG_START",))
        self.output.reset_mock()
        self.control.scroll.update = Mock(return_value=(ScrollEvent("SCROLL_UP", 0, amount=2),))
        self.update(SchemeBState(SchemeBGesture.SCROLL), None, ("DRAG_END",))
        self.assertEqual(self.output.mock_calls, [call.mouse_up(), call.scroll(2)])

    def test_pause_and_emergency_release_and_emergency_is_latched(self):
        self.arm()
        self.update(SchemeBState(SchemeBGesture.DRAG_OPEN), cursor(), ("DRAG_START",))
        self.control.pause(self.timestamp + 0.01)
        self.assertFalse(self.control.button_down)
        self.control.resume(self.timestamp + 0.02)
        self.arm()
        self.update(SchemeBState(SchemeBGesture.DRAG_OPEN), cursor(), ("DRAG_START",))
        self.control.emergency_stop(self.timestamp + 0.01)
        self.control.resume(self.timestamp + 0.02)
        self.assertTrue(self.control.emergency_stopped)
        self.assertFalse(self.control.enabled)

    def test_failed_click_release_is_retried_by_emergency_cleanup(self):
        self.arm()
        self.output.mouse_up.side_effect = [RuntimeError("release failed"), None]
        with self.assertRaisesRegex(RuntimeError, "release failed"):
            self.update(SchemeBState(SchemeBGesture.CLICK_OPEN), cursor(), ("CLICK",))
        self.assertEqual(self.output.mouse_up.call_count, 2)
        self.assertFalse(self.control.button_down)
        self.assertTrue(self.control.emergency_stopped)

    def test_watchdog_releases_drag_and_requires_rearming(self):
        self.arm()
        self.update(SchemeBState(SchemeBGesture.DRAG_OPEN), cursor(), ("DRAG_START",))
        self.control.check_timeout(self.timestamp + 1, self.control.frame_timeout)
        self.assertTrue(self.control.enabled)
        self.assertFalse(self.control.paused)
        self.assertFalse(self.control.button_down)
        self.assertEqual(self.control.reason, "FRAME_TIMEOUT")
        self.assertTrue(self.control.await_neutral)
        self.assertEqual(self.control.mode_label, "WAIT FOR NEUTRAL")
        self.session.reset.assert_called_once_with()

    def test_resume_after_long_pause_gets_fresh_watchdog_window(self):
        self.arm()
        self.control.pause(self.timestamp + 1)
        resumed_at = self.timestamp + 60
        self.control.resume(resumed_at)
        self.control.check_timeout(resumed_at + 0.02, self.control.frame_timeout)
        self.assertTrue(self.control.enabled)
        self.assertTrue(self.control.await_neutral)
        self.assertEqual(self.output.mock_calls, [])
        # Resuming must not disable timeout release if no fresh frame arrives.
        self.control.check_timeout(resumed_at + 1, self.control.frame_timeout)
        self.assertTrue(self.control.enabled)
        self.assertFalse(self.control.paused)
        self.assertTrue(self.control.await_neutral)
        self.assertEqual(self.control.reason, "FRAME_TIMEOUT")

    def test_loss_blocks_held_pinch_until_neutral_and_then_recovers(self):
        self.arm()
        self.update(SchemeBState(), hand="lost")
        self.assertEqual(self.control.mode_label, "WAIT FOR NEUTRAL")
        self.assertIn("Hold neutral", self.control.recovery_hint)
        for _ in range(10):
            self.update(SchemeBState(SchemeBGesture.PINCH_AIM,
                                     candidate=SchemeBGesture.PINCH_AIM), cursor())
        self.assertEqual(self.output.mock_calls, [])
        self.arm()
        self.update(SchemeBState(SchemeBGesture.PINCH_AIM), cursor())
        self.output.move_to.assert_called_once_with(100, 120)

    def test_recovery_hints_distinguish_pause_timeout_and_latched_stop(self):
        self.control.pause(1)
        self.assertIn("F8", self.control.recovery_hint)
        self.control.resume(2)
        self.control.check_timeout(3, self.control.frame_timeout)
        self.assertIn("no F8 needed", self.control.recovery_hint)
        self.control.emergency_stop(3, "MOUSE_CORNER_FAILSAFE")
        self.assertIn("restart", self.control.recovery_hint)

    def test_timeout_polling_resets_once_then_recovers_without_resume_key(self):
        self.arm()
        self.update(SchemeBState(SchemeBGesture.DRAG_OPEN), cursor(), ("DRAG_START",))
        self.output.reset_mock()
        self.timestamp += 1
        self.control.check_timeout(self.timestamp, self.control.frame_timeout)
        self.control.check_timeout(self.timestamp + 0.01, self.control.frame_timeout)
        self.control.check_timeout(self.timestamp + 0.02, self.control.frame_timeout)
        self.session.reset.assert_called_once_with()
        self.assertEqual(self.output.mock_calls, [call.mouse_up()])
        self.timestamp += 0.02
        # A held gesture or stale click cannot rearm output after a frame gap.
        self.update(SchemeBState(SchemeBGesture.CLICK_OPEN,
                                 candidate=SchemeBGesture.CLICK_OPEN), cursor(), ("CLICK",))
        self.assertEqual(self.output.mock_calls, [call.mouse_up()])
        self.arm()
        self.update(SchemeBState(SchemeBGesture.PINCH_AIM), cursor())
        self.output.move_to.assert_called_once_with(100, 120)

    def test_long_frame_gap_is_handled_before_outputs_without_monitor_poll(self):
        self.arm()
        self.timestamp += 1
        self.update(SchemeBState(SchemeBGesture.DRAG_OPEN), cursor(), ("DRAG_START",))
        self.assertEqual(self.output.mock_calls, [])
        self.assertTrue(self.control.enabled)
        self.assertTrue(self.control.await_neutral)
        self.session.reset.assert_called_once_with()

    def test_timeout_clears_real_drag_session_and_rearms_without_keyboard(self):
        session = SchemeBSession(SchemeBDetector(3), (1000, 800))
        self.control.session = session

        def feed(hand, frames=1):
            for _ in range(frames):
                self.timestamp += 1 / 30
                self.control.update(hand, (640, 480), self.timestamp)

        feed(sample(index_up=False), 3)
        feed(open_hand(), 3)
        self.assertTrue(self.control.button_down)
        self.output.reset_mock()
        self.timestamp += 1
        self.control.check_timeout(self.timestamp, self.control.frame_timeout)
        self.assertIsNone(session.position)
        self.assertEqual(session.detector.gesture, SchemeBGesture.NONE)
        self.assertEqual(self.output.mock_calls, [call.mouse_up()])
        feed(open_hand(), 5)
        self.assertTrue(self.control.await_neutral)
        self.assertEqual(self.output.mock_calls, [call.mouse_up()])
        feed(sample(index_up=False), 7)
        self.assertFalse(self.control.await_neutral)
        self.assertTrue(self.control.enabled)
        self.output.reset_mock()
        feed(sample(pinch_ratio=0.3), 3)
        self.output.move_to.assert_called_once()
        self.output.mouse_down.assert_not_called()

    def test_timeout_cannot_resume_manual_pause_or_emergency_stop(self):
        self.arm()
        self.control.pause(self.timestamp)
        self.control.check_timeout(self.timestamp + 10, self.control.frame_timeout)
        self.assertFalse(self.control.enabled)
        self.assertEqual(self.control.mode_label, "PAUSED")
        self.control.emergency_stop(self.timestamp + 11)
        self.control.check_timeout(self.timestamp + 20, self.control.frame_timeout)
        self.assertFalse(self.control.enabled)
        self.assertEqual(self.control.mode_label, "EMERGENCY STOP")
        self.session.reset.assert_not_called()


if __name__ == "__main__":
    unittest.main()
