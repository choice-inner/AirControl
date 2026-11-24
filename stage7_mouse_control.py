from __future__ import annotations

import argparse
import math
import threading
import time
from pathlib import Path

import pyautogui

from click_drag_controller import ActionEvent, ClickDragController
from config import Config
from cursor_mapper import CursorMapper
from gesture_detector import Gesture, GestureDetector, GestureState
from mouse_output import MouseOutput, PyAutoGuiMouseOutput
from scroll_controller import ScrollController, ScrollEvent
from stage2_hand_preview import DEFAULT_MODEL, run_preview
from stage4_cursor_preview import primary_screen_size
from stage5_click_drag_preview import valid_landmarks
from stage6_scroll_preview import Stage6Session, draw_status


class Stage7Control:
    """Serialize safety commands and translate confirmed events to mouse input."""

    def __init__(self, session: Stage6Session, output: MouseOutput, enabled: bool = False,
                 frame_timeout: float = 0.75):
        if not math.isfinite(frame_timeout) or frame_timeout <= 0:
            raise ValueError("frame_timeout must be finite and positive")
        self.session = session
        self.output = output
        self.lock = threading.RLock()
        self.enabled = enabled
        self.paused = False
        self.emergency_stopped = False
        self.await_neutral = enabled
        self.button_down = False
        self.reason = "STARTUP"
        self.input_status = "NO_INPUT"
        self.frame_timeout = frame_timeout
        self._latest_timestamp = 0.0
        self._anchor: tuple[float, float] | None = None
        self._last_frame_at: float | None = None

    def _time(self, timestamp: float) -> float:
        if not math.isfinite(timestamp):
            raise ValueError("timestamp must be finite")
        # UI and monitor may capture times before waiting for the shared lock.
        self._latest_timestamp = max(timestamp, self._latest_timestamp)
        return self._latest_timestamp

    @property
    def mode_label(self) -> str:
        if self.emergency_stopped:
            return "EMERGENCY STOP"
        if not self.enabled:
            return "PAUSED" if self.paused else "PREVIEW"
        return "WAIT FOR MOVE" if self.await_neutral else "CONTROL"

    def _release_button(self) -> None:
        if self.button_down:
            self.output.mouse_up()
            self.button_down = False
            self.input_status = "LEFT_UP_SENT"
        self._anchor = None

    def _release(self, timestamp: float, reason: str) -> None:
        try:
            self.session.cleanup(timestamp, reason)
        finally:
            self._release_button()

    def pause(self, timestamp: float, reason: str = "PAUSED") -> None:
        with self.lock:
            timestamp = self._time(timestamp)
            self.enabled = False
            self.paused = True
            self.await_neutral = False
            self.reason = reason
            self._release(timestamp, reason)

    def resume(self, timestamp: float) -> None:
        with self.lock:
            timestamp = self._time(timestamp)
            if self.emergency_stopped or self.enabled:
                return
            self._release(timestamp, "ENABLE")
            self.enabled = True
            self.paused = False
            self.await_neutral = True
            self.reason = "ENABLE"

    def toggle_pause(self, timestamp: float) -> None:
        with self.lock:
            if self.enabled:
                self.pause(timestamp)
            elif self.paused:
                self.resume(timestamp)

    def emergency_stop(self, timestamp: float, reason: str = "EMERGENCY_STOP") -> None:
        with self.lock:
            timestamp = self._time(timestamp)
            self.emergency_stopped = True
            self.enabled = False
            self.paused = False
            self.await_neutral = False
            self.reason = reason
            self._release(timestamp, reason)

    def check_timeout(self, timestamp: float, timeout: float) -> None:
        """Called by an independent monitor while capture/inference may be blocked."""
        with self.lock:
            if (self.enabled and self._last_frame_at is not None
                    and timestamp - self._last_frame_at > timeout):
                self.pause(timestamp, "FRAME_TIMEOUT")

    def update(self, hand, frame_size: tuple[int, int], timestamp: float):
        with self.lock:
            self.input_status = "NO_INPUT"
            timestamp = self._time(timestamp)
            self.check_timeout(timestamp, self.frame_timeout)
            self._last_frame_at = timestamp
            try:
                state, position, events = self.session.update(hand, frame_size, timestamp)
                if not self.enabled:
                    self.input_status = f"BLOCKED_{self.mode_label}"
                    return state, position, events
                if hand is None or not valid_landmarks(hand):
                    self._release_button()
                    self.await_neutral = True
                    self.reason = "HAND_LOST" if hand is None else "INVALID_HAND"
                    return state, position, events
                if self.await_neutral:
                    self.input_status = "BLOCKED_WAIT_FOR_MOVE"
                    # Require a newly confirmed, visibly released MOVE gesture.
                    # Discard preview actions collected before enabling/resuming.
                    if state.gesture == Gesture.MOVE and state.candidate == Gesture.MOVE:
                        self.session.cleanup(timestamp, "REARM")
                        self.await_neutral = False
                        self.reason = "READY"
                        self.input_status = "ARMED_NEXT_FRAME"
                    return state, position, events

                # Release before normal movement on a drag's final frame.
                for event in events:
                    self._apply_event(event)
                finished = any(event.kind in ("CLICK", "DRAG_END", "RELEASE_ALL") for event in events)
                if (not self.button_down and not finished and state.gesture == Gesture.MOVE
                        and state.candidate == Gesture.MOVE and position is not None):
                    self.output.move_to(position.x, position.y)
                    self.input_status = "MOVE_SENT"
                return state, position, events
            except pyautogui.FailSafeException:
                self.emergency_stop(timestamp, "MOUSE_CORNER_FAILSAFE")
                return GestureState(), None, ()
            except BaseException:
                self.emergency_stop(timestamp, "EXCEPTION")
                raise

    @staticmethod
    def _point(event: ActionEvent) -> tuple[float, float]:
        if event.x is None or event.y is None or not all(math.isfinite(v) for v in (event.x, event.y)):
            raise ValueError("action event requires finite coordinates")
        return event.x, event.y

    def _press(self) -> None:
        # Set ownership first: a backend may throw after sending a partial input.
        self.button_down = True
        self.output.mouse_down()
        self.input_status = "LEFT_DOWN_SENT"

    def _apply_event(self, event: ActionEvent | ScrollEvent) -> None:
        if isinstance(event, ScrollEvent):
            if event.kind in ("SCROLL_UP", "SCROLL_DOWN") and not self.button_down:
                if event.amount <= 0:
                    raise ValueError("scroll amount must be positive")
                steps = event.amount if event.kind == "SCROLL_UP" else -event.amount
                self.output.scroll(steps)
                self.input_status = f"WHEEL_SENT {steps:+d}"
            return
        if event.kind == "PINCH_START":
            self._anchor = self._point(event)
        elif event.kind == "CLICK":
            self.output.move_to(*self._point(event))
            try:
                self._press()
            finally:
                self._release_button()
            self.input_status = "CLICK_SENT"
        elif event.kind == "DRAG_START":
            if self._anchor is None:
                raise ValueError("drag requires a preceding pinch anchor")
            self.output.move_to(*self._anchor)
            self._press()
        elif event.kind == "DRAG_MOVE" and self.button_down:
            self.output.move_to(*self._point(event))
            self.input_status = "DRAG_MOVE_SENT"
        elif event.kind in ("DRAG_END", "RELEASE_ALL", "PINCH_CANCEL", "CLICK_SUPPRESSED"):
            self._release_button()

    def cleanup(self, timestamp: float, reason: str = "EXIT") -> None:
        with self.lock:
            timestamp = self._time(timestamp)
            self.enabled = False
            self.await_neutral = False
            self._release(timestamp, reason)


def build_session(config: Config, screen_size: tuple[int, int]) -> Stage6Session:
    mapper = CursorMapper(screen_size, smoothing=config.smoothing, margin_x=config.cursor_margin_x,
                          margin_y=config.cursor_margin_y, max_speed=config.cursor_max_speed,
                          jitter_deadzone_px=config.cursor_jitter_deadzone_px)
    detector = GestureDetector(
        pinch_on=config.pinch_on_distance, pinch_off=config.pinch_off_distance,
        stable_frames=config.gesture_stable_frames, finger_min_angle=config.finger_min_angle,
        middle_finger_angle_hysteresis=config.middle_finger_angle_hysteresis,
        middle_stable_frames=config.middle_stable_frames,
    )
    click = ClickDragController(config.click_cooldown, config.click_max_duration,
                                config.drag_start_distance_px, config.drag_move_epsilon_px)
    scroll = ScrollController(config.scroll_deadzone_px, config.scroll_step_px, config.scroll_gain,
                              config.scroll_max_steps_per_update, config.scroll_min_interval,
                              config.scroll_max_sample_gap)
    return Stage6Session(detector, mapper, click, scroll, config.drag_release_grace_seconds)


def main() -> None:
    from safety_monitor import SafetyMonitor

    parser = argparse.ArgumentParser(description="AirControl stage 7: safe real mouse integration")
    parser.add_argument("--camera", type=int, default=0)
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--control", action="store_true", help="enable real mouse input after stable MOVE")
    args = parser.parse_args()
    config = Config(camera_index=args.camera)
    size = primary_screen_size()
    control = Stage7Control(build_session(config, size), PyAutoGuiMouseOutput(size),
                            enabled=args.control, frame_timeout=config.control_frame_timeout)
    recent_events: list[ActionEvent | ScrollEvent] = []
    monitor = SafetyMonitor(control, config.control_frame_timeout)
    last_mode = None

    def draw_overlay(frame, hand, fps, model_path):
        nonlocal last_mode
        with control.lock:
            state, position, events = control.update(hand, frame.shape[1::-1], time.monotonic())
            mode = control.mode_label
            held = control.button_down
            reason = control.reason
            output_status = control.input_status
        if events:
            recent_events[0:0] = events
            for event in events:
                print(f"[GESTURE] {event.kind} {getattr(event, 'amount', '')} {event.reason}"
                      f" | mode={mode} | output={output_status}", flush=True)
        del recent_events[4:]
        mode_state = (mode, reason)
        if mode_state != last_mode:
            print(f"[CONTROL] {mode} | {reason}", flush=True)
            last_mode = mode_state
        draw_status(frame, hand, fps, state, config, size, position,
                    control.session.scroll, recent_events, control.session.controller,
                    status_note="C: enable | P/F8: pause/resume | E/F9: stop | Q/Esc: quit",
                    stage_number=7, real_button_down=held, mode_label=f"{mode} | {reason}",
                    output_status=output_status)

    def on_key(key: int) -> bool:
        now = time.monotonic()
        if key == ord("p"):
            control.toggle_pause(now)
        elif key == ord("c"):
            control.resume(now)
        elif key == ord("e"):
            control.emergency_stop(now)
        return monitor.exit_requested.is_set()

    print("PREVIEW by default. C / --control enables real input; show stable MOVE to arm.", flush=True)
    print("Global: F8 pause/resume | F9 latched stop | Esc stop & exit. Window: C/P/E/Q.", flush=True)
    try:
        monitor.start()
        run_preview(config, args.model, draw_overlay, "AirControl - Stage 7 Mouse Control",
                    lambda: control.cleanup(time.monotonic(), "EXIT"), on_key=on_key,
                    should_stop=monitor.exit_requested.is_set)
    finally:
        try:
            control.cleanup(time.monotonic(), "EXIT")
        finally:
            monitor.close()
    if monitor.error is not None:
        raise RuntimeError("Safety monitor failed; control has stopped") from monitor.error


if __name__ == "__main__":
    main()
