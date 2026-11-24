from __future__ import annotations

import math
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class CursorPosition:
    x: float
    y: float
    normalized_x: float
    normalized_y: float
    target_x: float
    target_y: float


class CursorMapper:
    """Map normalized camera coordinates to a screen-sized preview target."""

    def __init__(
        self,
        screen_size: tuple[int, int],
        smoothing: float = 0.25,
        margin_x: float = 0.15,
        margin_y: float = 0.15,
        max_speed: float = 1.5,
        jitter_deadzone_px: float = 4.0,
    ):
        width, height = screen_size
        if any(not isinstance(value, int) or isinstance(value, bool) or value < 2 for value in screen_size):
            raise ValueError("screen_size must be at least 2x2")
        if not math.isfinite(smoothing) or not 0 < smoothing <= 1:
            raise ValueError("smoothing must be in the range (0, 1]")
        if not math.isfinite(margin_x) or not 0 <= margin_x < 0.5:
            raise ValueError("margin_x must be in the range [0, 0.5)")
        if not math.isfinite(margin_y) or not 0 <= margin_y < 0.5:
            raise ValueError("margin_y must be in the range [0, 0.5)")
        if not math.isfinite(max_speed) or max_speed <= 0:
            raise ValueError("max_speed must be positive screen diagonals per second")
        if not math.isfinite(jitter_deadzone_px) or jitter_deadzone_px < 0:
            raise ValueError("jitter_deadzone_px must be finite and non-negative")

        self.width = width
        self.height = height
        self.smoothing = smoothing
        self.margin_x = margin_x
        self.margin_y = margin_y
        self.max_speed = max_speed
        self.jitter_deadzone_px = jitter_deadzone_px
        self._last_time: float | None = None
        self._filtered_x: float | None = None
        self._filtered_y: float | None = None
        self.last_position: CursorPosition | None = None

    @staticmethod
    def _map_axis(value: float, margin: float, maximum: int) -> tuple[float, float]:
        normalized = (value - margin) / (1.0 - 2.0 * margin)
        normalized = min(1.0, max(0.0, normalized))
        return normalized * maximum, normalized

    def update(
        self, x: float, y: float, active: bool = True, *, timestamp: float | None = None,
    ) -> CursorPosition | None:
        """Clear position and filter history while inactive or given invalid input."""
        if not active:
            self.reset()
            return None
        if not math.isfinite(x) or not math.isfinite(y):
            self.reset()
            return None
        now = time.monotonic() if timestamp is None else timestamp
        if not math.isfinite(now):
            raise ValueError("timestamp must be finite")
        if self._last_time is not None and now < self._last_time:
            raise ValueError("timestamp must not move backwards")

        target_x, _ = self._map_axis(x, self.margin_x, self.width - 1)
        target_y, _ = self._map_axis(y, self.margin_y, self.height - 1)
        if self._filtered_x is None or self._filtered_y is None or self.last_position is None:
            filtered_x, filtered_y = target_x, target_y
            output_x, output_y = filtered_x, filtered_y
        else:
            # Alpha is calibrated at 30 FPS. Cap elapsed time to avoid jumps after stalls.
            elapsed = 0.0 if self._last_time is None else min(now - self._last_time, 0.05)
            alpha = 0.0 if elapsed == 0 else 1.0 - (1.0 - self.smoothing) ** (elapsed * 30.0)
            dx = alpha * (target_x - self._filtered_x)
            dy = alpha * (target_y - self._filtered_y)
            distance = math.hypot(dx, dy)
            limit = self.max_speed * math.hypot(self.width - 1, self.height - 1) * elapsed
            factor = min(1.0, limit / distance) if distance > 0 else 1.0
            filtered_x = self._filtered_x + dx * factor
            filtered_y = self._filtered_y + dy * factor
            output_x, output_y = self.last_position.x, self.last_position.y
            if math.hypot(filtered_x - output_x, filtered_y - output_y) >= self.jitter_deadzone_px:
                output_x, output_y = filtered_x, filtered_y

        self._last_time = now
        self._filtered_x, self._filtered_y = filtered_x, filtered_y
        self.last_position = CursorPosition(
            x=output_x,
            y=output_y,
            normalized_x=output_x / (self.width - 1),
            normalized_y=output_y / (self.height - 1),
            target_x=target_x,
            target_y=target_y,
        )
        return self.last_position

    def reset(self) -> None:
        self._last_time = None
        self._filtered_x = None
        self._filtered_y = None
        self.last_position = None
