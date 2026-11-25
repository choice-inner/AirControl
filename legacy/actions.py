from __future__ import annotations

import time
from typing import Optional

import pyautogui


class MouseController:
    def __init__(self, screen_size: tuple[int, int], smoothing: float, click_cooldown: float, scroll_gain: float, enabled: bool):
        self.screen_w, self.screen_h = screen_size
        self.smoothing = smoothing
        self.click_cooldown = click_cooldown
        self.scroll_gain = scroll_gain
        self.enabled = enabled
        self.last_x: Optional[float] = None
        self.last_y: Optional[float] = None
        self.last_pinch = False
        self.last_click = 0.0

        pyautogui.PAUSE = 0.01
        pyautogui.FAILSAFE = True

    def move_from_normalized(self, x: float, y: float) -> None:
        # Keep a margin so the pointer is easier to reach and less jumpy.
        x = max(0.05, min(0.95, x))
        y = max(0.05, min(0.95, y))
        target_x = (x - 0.05) / 0.90 * self.screen_w
        target_y = (y - 0.05) / 0.90 * self.screen_h
        if self.last_x is None:
            self.last_x, self.last_y = target_x, target_y
        else:
            self.last_x += (target_x - self.last_x) * self.smoothing
            self.last_y += (target_y - self.last_y) * self.smoothing
        if self.enabled:
            pyautogui.moveTo(round(self.last_x), round(self.last_y), _pause=False)

    def update_pinch(self, active: bool) -> str | None:
        event = None
        now = time.monotonic()
        if active and not self.last_pinch:
            if now - self.last_click >= self.click_cooldown:
                if self.enabled:
                    pyautogui.mouseDown(button="left")
                self.last_click = now
                event = "DRAG_START"
        elif not active and self.last_pinch:
            if self.enabled:
                pyautogui.mouseUp(button="left")
            event = "DRAG_END"
        self.last_pinch = active
        return event

    def scroll(self, delta: float) -> None:
        amount = int(-delta * self.scroll_gain * 10)
        if amount and self.enabled:
            pyautogui.scroll(amount)

    def release(self) -> None:
        if self.last_pinch and self.enabled:
            pyautogui.mouseUp(button="left")
        self.last_pinch = False
