import ctypes
import unittest
from unittest.mock import Mock, patch

import pyautogui

from mouse_output import PyAutoGuiMouseOutput
from windows_wheel import INPUT, MOUSEEVENTF_WHEEL, WindowsWheelOutput


class WindowsWheelTests(unittest.TestCase):
    def test_steps_are_converted_to_signed_wheel_delta_without_moving_pointer(self):
        packets = []

        def capture(count, pointer, size):
            packet = ctypes.cast(pointer, ctypes.POINTER(INPUT)).contents
            packets.append((count, size, packet.type, packet.mi.dwFlags,
                            ctypes.c_int32(packet.mi.mouseData).value,
                            packet.mi.dx, packet.mi.dy))
            return 1

        wheel = WindowsWheelOutput(send_input=capture)
        wheel.scroll(5)
        wheel.scroll(-3)
        self.assertEqual(packets, [
            (1, ctypes.sizeof(INPUT), 0, MOUSEEVENTF_WHEEL, 600, 0, 0),
            (1, ctypes.sizeof(INPUT), 0, MOUSEEVENTF_WHEEL, -360, 0, 0),
        ])
        self.assertEqual(ctypes.sizeof(INPUT), 40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28)

    def test_zero_and_invalid_steps_never_send_input(self):
        send = Mock(return_value=1)
        wheel = WindowsWheelOutput(send_input=send)
        wheel.scroll(0)
        for invalid in (True, 0.5, 2 ** 31):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                wheel.scroll(invalid)
        send.assert_not_called()

    def test_rejected_input_reports_error_instead_of_silently_dropping(self):
        wheel = WindowsWheelOutput(send_input=Mock(return_value=0))
        with self.assertRaisesRegex(OSError, "Windows rejected wheel input"):
            wheel.scroll(1)

    def test_mouse_adapter_routes_wheel_to_windows_and_preserves_failsafe(self):
        with (
            patch("mouse_output.WindowsWheelOutput") as native,
            patch("mouse_output.pyautogui.failSafeCheck") as check,
            patch("mouse_output.pyautogui.scroll") as old_scroll,
        ):
            output = PyAutoGuiMouseOutput((100, 100))
            output.scroll(-3)
            check.assert_called_once_with()
            native.return_value.scroll.assert_called_once_with(-3)
            old_scroll.assert_not_called()
            check.side_effect = pyautogui.FailSafeException()
            with self.assertRaises(pyautogui.FailSafeException):
                output.scroll(3)
            native.return_value.scroll.assert_called_once_with(-3)

    def test_stable_hand_motion_reaches_windows_packet_with_full_notches(self):
        from config import Config
        from stage7_mouse_control import Stage7Control, build_session
        from test_stage6_scroll_preview import hand

        deltas = []

        def capture(count, pointer, size):
            packet = ctypes.cast(pointer, ctypes.POINTER(INPUT)).contents
            deltas.append(ctypes.c_int32(packet.mi.mouseData).value)
            return 1

        with (
            patch("mouse_output.WindowsWheelOutput", return_value=WindowsWheelOutput(capture)),
            patch("mouse_output.pyautogui.failSafeCheck"),
            patch("mouse_output.pyautogui.moveTo"),
            patch("mouse_output.pyautogui.mouseDown") as down,
            patch("mouse_output.pyautogui.mouseUp") as up,
        ):
            output = PyAutoGuiMouseOutput((1000, 1000))
            control = Stage7Control(build_session(Config(), (1000, 1000)), output, enabled=True)
            timestamp = 0
            for sample in (hand(), hand(middle_up=True),
                           hand(middle_up=True, dy=-0.1), hand(middle_up=True, dy=0.1)):
                for _ in range(6):
                    timestamp += 1 / 30
                    control.update(sample, (640, 480), timestamp)
            self.assertEqual(deltas, [600, -600])
            down.assert_not_called()
            up.assert_not_called()


if __name__ == "__main__":
    unittest.main()
