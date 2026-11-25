import unittest
from contextlib import ExitStack
from unittest.mock import patch

from aircontrol import aircontrol_app


class AppLifecycleTests(unittest.TestCase):
    def test_self_check_returns_before_camera_screen_mouse_or_monitor(self):
        with ExitStack() as stack:
            check = stack.enter_context(patch("aircontrol.self_check.run_self_check"))
            boundaries = [stack.enter_context(patch.object(aircontrol_app, name))
                          for name in ("primary_screen_size", "PyAutoGuiMouseOutput",
                                       "SafetyMonitor", "run_preview")]
            aircontrol_app.main(["--self-check", "--model", "custom.task", "--control"])
            self.assertEqual(str(check.call_args.args[0]), "custom.task")
            for boundary in boundaries:
                boundary.assert_not_called()

    def test_default_preview_keeps_monitor_when_c_enables_b(self):
        with ExitStack() as stack:
            output = stack.enter_context(patch.object(aircontrol_app, "PyAutoGuiMouseOutput"))
            stack.enter_context(patch.object(aircontrol_app, "primary_screen_size", return_value=(1000, 800)))
            monitor_factory = stack.enter_context(patch.object(aircontrol_app, "SafetyMonitor"))
            monitor = monitor_factory.return_value
            monitor.error = None
            monitor.exit_requested.is_set.return_value = False
            run = stack.enter_context(patch.object(aircontrol_app, "run_preview"))

            def preview(*args, **kwargs):
                monitor.start.assert_called_once_with()
                control = monitor_factory.call_args.args[0]
                self.assertEqual(control.mode_label, "PREVIEW")
                kwargs["on_key"](ord("c"))
                self.assertEqual(control.mode_label, "WAIT FOR NEUTRAL")
                self.assertEqual(output.return_value.mock_calls, [])
                kwargs["on_exit"]()
                self.assertFalse(control.enabled)

            run.side_effect = preview
            aircontrol_app.main([])
            self.assertEqual(run.call_args.args[3], "AirControl - Scheme B")
            monitor.close.assert_called_once_with()

    def test_monitor_closes_even_if_exit_release_fails(self):
        with ExitStack() as stack:
            stack.enter_context(patch.object(aircontrol_app, "PyAutoGuiMouseOutput"))
            stack.enter_context(patch.object(aircontrol_app, "primary_screen_size", return_value=(1000, 800)))
            control = stack.enter_context(patch.object(aircontrol_app, "SchemeBControl")).return_value
            control.cleanup.side_effect = RuntimeError("release failed")
            monitor = stack.enter_context(patch.object(aircontrol_app, "SafetyMonitor")).return_value
            stack.enter_context(patch.object(aircontrol_app, "run_preview", side_effect=RuntimeError("camera error")))
            with self.assertRaisesRegex(RuntimeError, "release failed"):
                aircontrol_app.main(["--control"])
            monitor.close.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
