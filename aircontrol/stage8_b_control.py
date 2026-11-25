from __future__ import annotations

import math
import threading

import pyautogui

from .cursor_mapper import CursorPosition
from .gesture_detector import Gesture
from .gesture_scheme_b import SchemeBGesture, SchemeBSession
from .mouse_output import MouseOutput
from .scroll_controller import ScrollController
from .stage5_click_drag_preview import valid_landmarks


class SchemeBControl:
    """Safety-gated real mouse output for the experimental Scheme B session."""

    def __init__(self, session: SchemeBSession, output: MouseOutput,
                 scroll: ScrollController, enabled: bool = False,
                 frame_timeout: float = 0.75):
        if not math.isfinite(frame_timeout) or frame_timeout <= 0:
            raise ValueError("frame_timeout must be finite and positive")
        self.session = session
        self.output = output
        self.scroll = scroll
        self.frame_timeout = frame_timeout
        self.lock = threading.RLock()
        self.enabled = enabled
        self.paused = False
        self.emergency_stopped = False
        self.await_neutral = enabled
        self.button_down = False
        self.reason = "STARTUP"
        self.input_status = "NO_INPUT"
        self._last_frame_at: float | None = None
        self._latest_timestamp = 0.0
        self._neutral_frames = 0
        self._frame_timed_out = False

    @property
    def mode_label(self):
        if self.emergency_stopped:
            return "EMERGENCY STOP"
        if self.paused:
            return "PAUSED"
        if not self.enabled:
            return "PREVIEW"
        return "WAIT FOR NEUTRAL" if self.await_neutral else "CONTROL"

    @property
    def recovery_hint(self):
        if self.emergency_stopped:
            return "Stop latched: restart the program"
        if self.paused:
            return "F8 to resume, then hold neutral"
        if not self.enabled:
            return "Preview only: press C in the preview window to enable"
        if self.await_neutral:
            if self.reason == "FRAME_TIMEOUT":
                return "Waiting for camera and neutral pose; no F8 needed"
            return "Hold neutral: curl fingers, separate thumb and index"
        return "Ready | F8 pause | F9 stop | Esc quit"

    def _time(self, timestamp):
        if not math.isfinite(timestamp):
            raise ValueError("timestamp must be finite")
        self._latest_timestamp = max(timestamp, self._latest_timestamp)
        return self._latest_timestamp

    def _release(self):
        if self.button_down:
            self.output.mouse_up()
            self.button_down = False

    def _press(self):
        self.button_down = True
        self.output.mouse_down()

    def _finish_scroll(self, timestamp, reason):
        events = self.scroll.reset(timestamp, reason)
        for event in events:
            if event.kind == "SCROLL_END":
                self.input_status = f"{event.kind} {event.reason}"

    def pause(self, timestamp, reason="PAUSED"):
        with self.lock:
            timestamp = self._time(timestamp)
            self.enabled = False
            self.paused = True
            self.reason = reason
            self._release()
            self._finish_scroll(timestamp, reason)

    def resume(self, timestamp):
        with self.lock:
            timestamp = self._time(timestamp)
            if self.emergency_stopped or self.enabled:
                return
            self._release()
            self._finish_scroll(timestamp, "ENABLE")
            self.enabled = True
            self.paused = False
            self.await_neutral = True
            self._neutral_frames = 0
            self._frame_timed_out = False
            # Give capture a fresh timeout window after a long manual pause.
            self._last_frame_at = timestamp
            self.reason = "ENABLE"

    def toggle_pause(self, timestamp):
        if self.enabled:
            self.pause(timestamp)
        elif self.paused:
            self.resume(timestamp)

    def emergency_stop(self, timestamp, reason="EMERGENCY_STOP"):
        with self.lock:
            timestamp = self._time(timestamp)
            self.enabled = False
            self.paused = False
            self.emergency_stopped = True
            self.reason = reason
            self._release()
            self._finish_scroll(timestamp, reason)

    def check_timeout(self, timestamp, timeout):
        with self.lock:
            if (self.enabled and not self._frame_timed_out
                    and self._last_frame_at is not None
                    and timestamp - self._last_frame_at > timeout):
                timestamp = self._time(timestamp)
                self._frame_timed_out = True
                self.await_neutral = True
                self._neutral_frames = 0
                self.reason = "FRAME_TIMEOUT"
                self._release()
                self._finish_scroll(timestamp, "FRAME_TIMEOUT")
                self.session.reset()
                self.input_status = "BLOCKED_WAIT_FOR_NEUTRAL"

    @staticmethod
    def _scroll_point(hand, frame_size):
        width, height = frame_size
        index, middle = hand.landmarks[8], hand.landmarks[12]
        x = (index.x + middle.x) * width * 0.5
        y = (index.y + middle.y) * height * 0.5
        return CursorPosition(x, y, x / max(1, width - 1), y / max(1, height - 1), x, y)

    def update(self, hand, frame_size, timestamp):
        with self.lock:
            timestamp = self._time(timestamp)
            self.input_status = "NO_INPUT"
            self.check_timeout(timestamp, self.frame_timeout)
            self._last_frame_at = timestamp
            self._frame_timed_out = False
            try:
                state, position, events = self.session.update(hand, frame_size)
                if not self.enabled:
                    self.input_status = f"BLOCKED_{self.mode_label}"
                    return state, position, events
                if hand is None or not valid_landmarks(hand):
                    self._release()
                    self._finish_scroll(timestamp, "HAND_LOST")
                    self.await_neutral = True
                    self._neutral_frames = 0
                    self.reason = "HAND_LOST"
                    return state, position, events
                if self.await_neutral:
                    self.input_status = "BLOCKED_WAIT_FOR_NEUTRAL"
                    if state.gesture == SchemeBGesture.NONE and state.candidate == SchemeBGesture.NONE:
                        self._neutral_frames += 1
                    else:
                        self._neutral_frames = 0
                    if self._neutral_frames >= 3:
                        self.await_neutral = False
                        self.reason = "READY"
                        self.input_status = "ARMED_NEXT_FRAME"
                    self._finish_scroll(timestamp, "WAIT_FOR_NEUTRAL")
                    return state, position, events

                if any(event.startswith("DRAG_END") for event in events):
                    self._release()
                    self.input_status = "LEFT_UP_SENT"

                if state.gesture == SchemeBGesture.SCROLL:
                    scroll_events = self.scroll.update(
                        Gesture.SCROLL, self._scroll_point(hand, frame_size), timestamp)
                    for event in scroll_events:
                        if event.kind in ("SCROLL_UP", "SCROLL_DOWN"):
                            amount = event.amount if event.kind == "SCROLL_UP" else -event.amount
                            self.output.scroll(amount)
                            self.input_status = f"WHEEL_SENT {amount:+d}"
                else:
                    self._finish_scroll(timestamp, "GESTURE_" + state.gesture.value)

                if "CLICK" in events and position is not None:
                    try:
                        self._press()
                    finally:
                        self._release()
                    self.input_status = "CLICK_SENT"
                elif (state.gesture == SchemeBGesture.PINCH_AIM and state.aim_frozen):
                    self.input_status = "AIM_FROZEN"
                elif state.gesture in (SchemeBGesture.PINCH_AIM, SchemeBGesture.DRAG_OPEN) and position is not None:
                    self.output.move_to(position.x, position.y)
                    self.input_status = "MOVE_SENT"

                if "DRAG_START" in events and not self.button_down:
                    self._press()
                    self.input_status = "LEFT_DOWN_SENT"
                return state, position, events
            except pyautogui.FailSafeException:
                self.emergency_stop(timestamp, "MOUSE_CORNER_FAILSAFE")
                return state, position, events
            except BaseException:
                self.emergency_stop(timestamp, "EXCEPTION")
                raise

    def cleanup(self, timestamp, reason="EXIT"):
        with self.lock:
            timestamp = self._time(timestamp)
            self.enabled = False
            self._release()
            self._finish_scroll(timestamp, reason)
