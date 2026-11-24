from __future__ import annotations

from typing import Protocol
import math
import threading

import pyautogui

from windows_wheel import WindowsWheelOutput


class MouseOutput(Protocol):
    """Small boundary between gesture logic and operating-system input."""

    def move_to(self, x: float, y: float) -> None: ...
    def mouse_down(self) -> None: ...
    def mouse_up(self) -> None: ...
    def scroll(self, amount: int) -> None: ...


class PyAutoGuiMouseOutput:
    def __init__(self, screen_size: tuple[int, int]) -> None:
        self.width, self.height = screen_size
        if self.width < 3 or self.height < 3:
            raise ValueError("screen_size must be at least 3x3")
        self._lock = threading.RLock()
        self._wheel = WindowsWheelOutput()
        pyautogui.PAUSE = 0
        pyautogui.FAILSAFE = True

    def move_to(self, x: float, y: float) -> None:
        if not all(math.isfinite(value) for value in (x, y)):
            raise ValueError("mouse coordinates must be finite")
        # Preserve the physical screen corners as the user's fail-safe escape.
        x = min(self.width - 2, max(1, round(x)))
        y = min(self.height - 2, max(1, round(y)))
        with self._lock:
            pyautogui.moveTo(x, y, _pause=False)

    def mouse_down(self) -> None:
        with self._lock:
            pyautogui.mouseDown(button="left", _pause=False)

    def mouse_up(self) -> None:
        # A fail-safe corner must still allow releasing our held button.
        # Disable the check only for mouseUp and always restore its setting.
        with self._lock:
            previous = pyautogui.FAILSAFE
            try:
                pyautogui.FAILSAFE = False
                pyautogui.mouseUp(button="left", _pause=False)
            finally:
                pyautogui.FAILSAFE = previous

    def scroll(self, amount: int) -> None:
        if amount:
            with self._lock:
                pyautogui.failSafeCheck()
                self._wheel.scroll(amount)
