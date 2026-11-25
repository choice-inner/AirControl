from __future__ import annotations

import ctypes
import threading
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .stage7_mouse_control import Stage7Control
    from .stage8_b_control import SchemeBControl


class SafetyMonitor:
    """Windows hotkeys and frame watchdog, independent of camera/inference."""

    KEYS = (0x77, 0x78, 0x1B)  # F8, F9, Esc

    def __init__(self, control: Stage7Control | SchemeBControl, frame_timeout: float, read_key=None):
        self.control = control
        self.frame_timeout = frame_timeout
        if read_key is None:
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
            user32.GetAsyncKeyState.restype = ctypes.c_short
            self.read_key = lambda key: bool(user32.GetAsyncKeyState(key) & 0x8000)
        else:
            self.read_key = read_key
        self._down = {key for key in self.KEYS if self.read_key(key)}
        self.exit_requested = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.error: Exception | None = None

    def poll(self, timestamp: float | None = None) -> None:
        with self.control.lock:
            now = time.monotonic() if timestamp is None else timestamp
            down = {key for key in self.KEYS if self.read_key(key)}
            pressed = down - self._down
            self._down = down
            # Stop always wins over a simultaneous resume.
            if 0x1B in pressed:
                self.control.emergency_stop(now, "GLOBAL_ESCAPE")
                self.exit_requested.set()
            elif 0x78 in pressed:
                self.control.emergency_stop(now, "GLOBAL_F9")
            elif 0x77 in pressed:
                self.control.toggle_pause(now)
            self.control.check_timeout(now, self.frame_timeout)

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="AirControlSafety", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.wait(0.02):
            try:
                self.poll()
            except Exception as error:
                self.error = error
                try:
                    self.control.emergency_stop(time.monotonic(), "SAFETY_MONITOR_ERROR")
                finally:
                    self.exit_requested.set()
                return

    def close(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1)
