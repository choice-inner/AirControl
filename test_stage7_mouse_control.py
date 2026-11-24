import unittest
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

import pyautogui

from click_drag_controller import ActionEvent
from config import Config
from cursor_mapper import CursorPosition
from gesture_detector import Gesture, GestureState
from mouse_output import PyAutoGuiMouseOutput
from safety_monitor import SafetyMonitor
from scroll_controller import ScrollEvent
from stage7_mouse_control import Stage7Control, build_session
from test_stage6_scroll_preview import hand
from test_gesture_detector import make_hand
from test_stage5_click_drag_preview import preview_hand_from


def position(x=10, y=20):
    return CursorPosition(x, y, x / 100, y / 100, x, y)


class Stage7ControlTests(unittest.TestCase):
    def setUp(self):
        self.session = Mock()
        self.output = Mock()
        self.control = Stage7Control(self.session, self.output)
        self.t = 0

    def update(self, gesture=Gesture.MOVE, events=(), sample=True, candidate=None):
        self.t += 1 / 30
        self.session.update.return_value = (
            GestureState(gesture, candidate=candidate or gesture), position(), events,
        )
        return self.control.update(hand() if sample else None, (640, 480), self.t)

    def arm(self):
        self.control.resume(self.t)
        self.update()
        self.assertFalse(self.control.await_neutral)
        self.assertEqual(self.output.mock_calls, [])

    def test_preview_and_cleanup_never_send_os_input(self):
        self.update(Gesture.PINCH, [ActionEvent("PINCH_START", 0, 10, 20)])
        self.update(Gesture.MOVE, [ActionEvent("CLICK", 0, 10, 20)])
        self.update(Gesture.SCROLL, [ScrollEvent("SCROLL_UP", 0, amount=2)])
        self.control.cleanup(self.t)
        self.assertEqual(self.output.mock_calls, [])

    def test_startup_pinch_scroll_and_missing_hand_cannot_arm(self):
        self.control = Stage7Control(self.session, self.output, enabled=True)
        self.update(Gesture.PINCH, [ActionEvent("PINCH_START", 0, 10, 20)])
        self.update(Gesture.SCROLL, [ScrollEvent("SCROLL_UP", 0, amount=2)])
        self.update(Gesture.NONE, sample=False)
        self.update(Gesture.PINCH, candidate=Gesture.MOVE)
        self.assertTrue(self.control.await_neutral)
        self.assertEqual(self.output.mock_calls, [])
        self.assertEqual(self.control.input_status, "BLOCKED_WAIT_FOR_MOVE")
        self.update()
        self.assertFalse(self.control.await_neutral)
        self.update()
        self.output.move_to.assert_called_once_with(10, 20)

    def test_scroll_log_distinguishes_recognition_from_sent_output(self):
        self.update(Gesture.SCROLL, [ScrollEvent("SCROLL_UP", 0, amount=5)])
        self.assertEqual(self.control.input_status, "BLOCKED_PREVIEW")
        self.arm()
        self.update(Gesture.SCROLL, [ScrollEvent("SCROLL_UP", 0, amount=5)])
        self.assertEqual(self.control.input_status, "WHEEL_SENT +5")
        self.update(Gesture.SCROLL, [ScrollEvent("SCROLL_DOWN", 0, amount=3)])
        self.assertEqual(self.control.input_status, "WHEEL_SENT -3")

    def test_cancelled_or_suppressed_pinch_never_clicks(self):
        self.arm()
        self.update(Gesture.PINCH, [ActionEvent("PINCH_START", 0, 10, 20)])
        self.assertEqual(self.output.mock_calls, [])
        self.update(Gesture.NONE, [ActionEvent("PINCH_CANCEL", 0), ActionEvent("RELEASE_ALL", 0)])
        self.update(Gesture.NONE, [ActionEvent("CLICK_SUPPRESSED", 0), ActionEvent("RELEASE_ALL", 0)])
        self.assertEqual(self.output.mock_calls, [])

    def test_confirmed_click_uses_anchor_and_sends_exactly_one_press_release(self):
        self.arm()
        self.update(Gesture.PINCH, [ActionEvent("PINCH_START", 0, 10, 20)])
        self.update(events=[ActionEvent("CLICK", 0, 10, 20), ActionEvent("RELEASE_ALL", 0)])
        self.assertEqual(self.output.mock_calls, [call.move_to(10, 20), call.mouse_down(), call.mouse_up()])
        self.assertFalse(self.control.button_down)

    def begin_drag(self):
        self.update(Gesture.PINCH, [ActionEvent("PINCH_START", 0, 10, 20)])
        self.update(Gesture.PINCH, [
            ActionEvent("DRAG_START", 0, 30, 40), ActionEvent("DRAG_MOVE", 0, 30, 40),
        ])

    def test_drag_starts_at_pinch_anchor_and_releases_before_normal_move(self):
        self.arm()
        self.begin_drag()
        self.update(events=[ActionEvent("DRAG_END", 0), ActionEvent("RELEASE_ALL", 0)])
        self.assertEqual(self.output.mock_calls, [
            call.move_to(10, 20), call.mouse_down(), call.move_to(30, 40), call.mouse_up(),
        ])
        self.assertFalse(self.control.button_down)

    def test_scroll_does_not_move_cursor_or_press_and_direction_is_signed(self):
        self.arm()
        self.update(Gesture.SCROLL, [ScrollEvent("SCROLL_UP", 0, amount=2)])
        self.update(Gesture.SCROLL, [ScrollEvent("SCROLL_DOWN", 0, amount=3)])
        self.assertEqual(self.output.mock_calls, [call.scroll(2), call.scroll(-3)])

    def test_pause_release_then_resume_requires_new_move_and_clears_old_anchor(self):
        self.arm()
        self.begin_drag()
        self.control.pause(self.t)
        self.assertEqual(self.control.mode_label, "PAUSED")
        self.assertFalse(self.control.button_down)
        self.output.reset_mock()
        self.control.resume(self.t)
        self.update(Gesture.PINCH, [ActionEvent("DRAG_MOVE", 0, 80, 80)])
        self.assertTrue(self.control.await_neutral)
        self.assertEqual(self.output.mock_calls, [])

    def test_emergency_is_latched_and_cleanup_is_idempotent(self):
        self.arm()
        self.begin_drag()
        self.control.emergency_stop(self.t)
        self.control.resume(self.t)
        self.control.toggle_pause(self.t)
        self.control.cleanup(self.t)
        self.assertEqual(self.control.mode_label, "EMERGENCY STOP")
        self.output.mouse_up.assert_called_once_with()

    def test_hand_loss_releases_drag_and_requires_fresh_move(self):
        self.arm()
        self.begin_drag()
        self.update(Gesture.NONE, sample=False)
        self.output.mouse_up.assert_called_once_with()
        self.output.reset_mock()
        self.update(Gesture.PINCH, [ActionEvent("PINCH_START", 0, 80, 80)])
        self.assertTrue(self.control.await_neutral)
        self.assertEqual(self.output.mock_calls, [])

    def test_frame_timeout_releases_without_another_camera_update(self):
        self.arm()
        self.begin_drag()
        monitor = SafetyMonitor(self.control, 0.75, read_key=lambda key: False)
        monitor.poll(self.t + 0.8)
        self.assertFalse(self.control.button_down)
        self.assertEqual(self.control.mode_label, "PAUSED")
        self.assertEqual(self.control.reason, "FRAME_TIMEOUT")
        self.output.mouse_up.assert_called_once_with()

    def test_stale_frame_cannot_drag_before_watchdog_poll(self):
        self.arm()
        self.begin_drag()
        self.output.reset_mock()
        self.t += 0.8
        self.update(Gesture.PINCH, [ActionEvent("DRAG_MOVE", 0, 90, 90)])
        self.assertEqual(self.output.mock_calls, [call.mouse_up()])
        self.assertEqual(self.control.mode_label, "PAUSED")

    def test_partial_mouse_down_failure_still_attempts_release_and_stops(self):
        self.arm()
        self.output.mouse_down.side_effect = RuntimeError("partial input")
        with self.assertRaisesRegex(RuntimeError, "partial input"):
            self.update(events=[ActionEvent("CLICK", 0, 10, 20)])
        self.output.mouse_up.assert_called_once_with()
        self.assertEqual(self.control.mode_label, "EMERGENCY STOP")

    def test_failsafe_corner_releases_drag_and_latches_stop(self):
        self.arm()
        self.begin_drag()
        self.output.move_to.side_effect = pyautogui.FailSafeException()
        self.update(Gesture.PINCH, [ActionEvent("DRAG_MOVE", 0, 40, 40)])
        self.output.mouse_up.assert_called_once_with()
        self.assertEqual(self.control.reason, "MOUSE_CORNER_FAILSAFE")
        self.assertEqual(self.control.mode_label, "EMERGENCY STOP")

    def test_session_error_also_releases_and_stops(self):
        self.arm()
        self.begin_drag()
        self.session.update.side_effect = RuntimeError("inference data failed")
        with self.assertRaisesRegex(RuntimeError, "inference data failed"):
            self.update()
        self.output.mouse_up.assert_called_once_with()
        self.assertFalse(self.control.enabled)

    def test_release_failure_is_retried_at_cleanup(self):
        self.arm()
        self.begin_drag()
        self.output.mouse_up.side_effect = [OSError("temporary failure"), None]
        with self.assertRaises(OSError):
            self.control.pause(self.t)
        self.assertTrue(self.control.button_down)
        self.control.cleanup(self.t)
        self.assertFalse(self.control.button_down)
        self.assertEqual(self.output.mouse_up.call_count, 2)


class SafetyMonitorTests(unittest.TestCase):
    def setUp(self):
        self.control = Stage7Control(Mock(), Mock(), enabled=True)
        self.keys = set()
        self.monitor = SafetyMonitor(self.control, 0.75, read_key=lambda key: key in self.keys)

    def test_global_pause_is_edge_triggered_and_held_key_does_not_toggle(self):
        self.keys.add(0x77)
        self.monitor.poll(1)
        self.assertEqual(self.control.mode_label, "PAUSED")
        self.monitor.poll(2)
        self.assertEqual(self.control.mode_label, "PAUSED")
        self.keys.clear()
        self.monitor.poll(3)
        self.keys.add(0x77)
        self.monitor.poll(4)
        self.assertEqual(self.control.mode_label, "WAIT FOR MOVE")

    def test_global_stop_wins_over_pause_and_cannot_be_resumed(self):
        self.keys.update((0x77, 0x78))
        self.monitor.poll(1)
        self.control.resume(2)
        self.assertEqual(self.control.mode_label, "EMERGENCY STOP")
        self.assertFalse(self.monitor.exit_requested.is_set())

    def test_global_escape_stops_and_requests_exit(self):
        self.keys.add(0x1B)
        self.monitor.poll(1)
        self.assertEqual(self.control.mode_label, "EMERGENCY STOP")
        self.assertTrue(self.monitor.exit_requested.is_set())


class MouseAdapterTests(unittest.TestCase):
    def test_gesture_targets_stay_one_pixel_away_from_failsafe_corners(self):
        output = PyAutoGuiMouseOutput((100, 100))
        with patch("mouse_output.pyautogui.moveTo") as move:
            output.move_to(-2, 200)
            move.assert_called_once_with(1, 98, _pause=False)
            with self.assertRaises(ValueError):
                output.move_to(float("nan"), 0)

    def test_release_bypasses_corner_check_and_restores_failsafe_even_on_error(self):
        output = PyAutoGuiMouseOutput((100, 100))

        def release(**kwargs):
            self.assertFalse(pyautogui.FAILSAFE)
            raise OSError("release failed")

        with patch("mouse_output.pyautogui.mouseUp", side_effect=release):
            with self.assertRaises(OSError):
                output.mouse_up()
        self.assertTrue(pyautogui.FAILSAFE)


class Stage7SessionIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.output = Mock()
        self.control = Stage7Control(build_session(Config(), (1000, 1000)), self.output, enabled=True)
        self.timestamp = 0

    def settle(self, sample, frames=6):
        for _ in range(frames):
            self.timestamp += 1 / 30
            self.control.update(sample, (640, 480), self.timestamp)

    def test_actual_session_click_cooldown_and_too_long_pinch_never_leak_clicks(self):
        self.settle(hand())
        self.settle(hand(pinch_ratio=0.3), 3)
        self.settle(hand(), 3)
        self.output.mouse_down.assert_called_once_with()
        self.output.mouse_up.assert_called_once_with()
        self.settle(hand(pinch_ratio=0.3), 3)
        self.settle(hand(), 3)
        self.assertEqual(self.output.mouse_down.call_count, 1)
        self.settle(hand(pinch_ratio=0.3), 35)
        self.settle(hand(), 3)
        self.assertEqual(self.output.mouse_down.call_count, 1)

    def test_actual_session_drag_loss_and_pinch_reentry(self):
        self.settle(hand())
        self.settle(hand(pinch_ratio=0.3), 3)
        self.settle(hand(pinch_ratio=0.3, dy=0.2), 8)
        self.assertTrue(self.control.button_down)
        self.output.mouse_down.assert_called_once_with()
        self.settle(None, 1)
        self.assertFalse(self.control.button_down)
        self.output.mouse_up.assert_called_once_with()
        self.output.reset_mock()
        self.settle(hand(pinch_ratio=0.3))
        self.assertEqual(self.output.mock_calls, [])

    def test_actual_session_scroll_preserves_cursor_and_stops_when_still(self):
        self.settle(hand())
        self.settle(hand(middle_up=True))
        self.output.reset_mock()
        self.settle(hand(middle_up=True, dy=-0.1))
        self.output.scroll.assert_called_once()
        self.assertGreater(self.output.scroll.call_args.args[0], 0)
        self.output.move_to.assert_not_called()
        self.output.mouse_down.assert_not_called()
        self.settle(hand(middle_up=True, dy=-0.1), 15)
        self.output.scroll.assert_called_once()

    def start_drag(self):
        self.settle(hand())
        self.settle(hand(pinch_ratio=0.3), 3)
        self.settle(hand(pinch_ratio=0.3, dy=0.2), 8)
        self.assertTrue(self.control.button_down)
        self.output.reset_mock()

    @staticmethod
    def release_sample(gesture):
        sample = make_hand(index_up=gesture != Gesture.NONE, middle_up=gesture == Gesture.SCROLL)
        sample.points = [(x, y + 0.2, z) for x, y, z in sample.points]
        return preview_hand_from(sample)

    def test_drag_freezes_short_none_scroll_and_move_candidates_then_continues_without_repress(self):
        for gesture in (Gesture.NONE, Gesture.SCROLL, Gesture.MOVE):
            with self.subTest(gesture=gesture):
                self.setUp()
                self.start_drag()
                self.settle(self.release_sample(gesture), 4)
                self.assertTrue(self.control.button_down)
                self.assertEqual(self.output.mock_calls, [])
                self.settle(hand(pinch_ratio=0.3, dy=0.25), 6)
                self.assertTrue(self.control.button_down)
                self.output.mouse_up.assert_not_called()
                self.output.mouse_down.assert_not_called()
                self.output.move_to.assert_called()
                self.output.scroll.assert_not_called()

    def test_sustained_release_ends_drag_once_without_a_click_and_scroll_waits(self):
        for gesture in (Gesture.NONE, Gesture.SCROLL, Gesture.MOVE):
            with self.subTest(gesture=gesture):
                self.setUp()
                self.start_drag()
                self.settle(self.release_sample(gesture), 4)
                self.output.mouse_up.assert_not_called()
                self.output.scroll.assert_not_called()
                self.settle(self.release_sample(gesture), 2)
                self.output.mouse_up.assert_called_once_with()
                self.output.mouse_down.assert_not_called()
                self.assertFalse(self.control.button_down)

    def test_pending_release_still_releases_immediately_on_hand_loss(self):
        self.start_drag()
        self.settle(self.release_sample(Gesture.NONE), 1)
        self.assertTrue(self.control.button_down)
        self.settle(None, 1)
        self.output.mouse_up.assert_called_once_with()
        self.assertFalse(self.control.button_down)
        self.assertTrue(self.control.await_neutral)

    def test_degenerate_hand_releases_drag_without_waiting_for_grace_period(self):
        self.start_drag()
        sample = make_hand()
        sample.points[9] = sample.points[0]
        self.settle(preview_hand_from(sample), 1)
        self.output.mouse_up.assert_called_once_with()
        self.assertFalse(self.control.button_down)

    def test_pending_release_does_not_delay_pause_or_emergency(self):
        for action in ("pause", "emergency_stop"):
            with self.subTest(action=action):
                self.setUp()
                self.start_drag()
                self.settle(self.release_sample(Gesture.NONE), 1)
                getattr(self.control, action)(self.timestamp)
                self.output.mouse_up.assert_called_once_with()
                self.assertFalse(self.control.button_down)

    def test_opposite_tip_tracking_noise_keeps_pinch_midpoint_stationary(self):
        self.start_drag()
        self.settle(hand(pinch_ratio=0.3, dy=0.2), 40)  # settle EMA after drag movement
        self.output.reset_mock()
        for step in range(20):
            sample = hand(pinch_ratio=0.3, dy=0.2)
            points = list(sample.landmarks)
            noise = 0.004 if step % 2 else -0.004
            for index, offset in ((8, noise), (4, -noise)):
                point = points[index]
                points[index] = SimpleNamespace(x=point.x + offset, y=point.y, z=point.z)
            sample.landmarks = tuple(points)
            self.settle(sample, 1)
        self.assertTrue(self.control.button_down)
        self.assertEqual(self.output.mock_calls, [])


if __name__ == "__main__":
    unittest.main()
