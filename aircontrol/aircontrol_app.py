from __future__ import annotations

import argparse
import time
from pathlib import Path

import cv2

from .config import Config
from .gesture_scheme_b import SchemeBDetector, SchemeBGesture, SchemeBSession
from .mouse_output import PyAutoGuiMouseOutput
from .safety_monitor import SafetyMonitor
from .scroll_controller import ScrollController
from .stage2_hand_preview import DEFAULT_MODEL, draw_hand, run_preview
from .stage4_cursor_preview import draw_screen_preview, primary_screen_size
from .stage6_scroll_preview import draw_status
from .stage8_b_control import SchemeBControl


def build_b_session(config: Config, screen_size):
    detector = SchemeBDetector(config.gesture_stable_frames, config.finger_min_angle)
    return SchemeBSession(detector, screen_size)


def main(argv=None, *, compare: bool = False) -> None:
    parser = argparse.ArgumentParser(description=(
        "AirControl stage 8: compare gesture schemes A and B" if compare
        else "AirControl: Scheme B gesture mouse (preview by default)"))
    parser.add_argument("--camera", type=int, default=0)
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--self-check", action="store_true",
                        help="check model inference without camera or mouse input, then exit")
    if compare:
        parser.add_argument("--scheme", choices=("A", "B"), default="A")
    parser.add_argument("--control", action="store_true",
                        help="enable real mouse input for scheme B after neutral posture")
    args = parser.parse_args(argv)
    if args.self_check:
        from .self_check import run_self_check
        run_self_check(args.model)
        return
    scheme = args.scheme if compare else "B"
    if args.control and scheme != "B":
        parser.error("--control requires --scheme B")
    config = Config(camera_index=args.camera)
    screen_size = primary_screen_size()
    session_a = None
    if compare:
        from .stage7_mouse_control import build_session as build_a_session
        session_a = build_a_session(config, screen_size)
    session_b = build_b_session(config, screen_size)
    b_control = SchemeBControl(
        session_b, PyAutoGuiMouseOutput(screen_size),
        ScrollController(config.scroll_deadzone_px, config.scroll_step_px,
                         config.scroll_gain, config.scroll_max_steps_per_update,
                         config.scroll_min_interval, config.scroll_max_sample_gap),
        enabled=args.control, frame_timeout=config.control_frame_timeout,
    )
    monitor = SafetyMonitor(b_control, config.control_frame_timeout)
    selected = {"scheme": scheme}
    previous = {"gesture": None}
    recent: list[str] = []
    last_control_status = None

    def report_control_status():
        nonlocal last_control_status
        with b_control.lock:
            status = (b_control.mode_label, b_control.reason)
            if status != last_control_status:
                print(f"[CONTROL] {status[0]} | {status[1]} | {b_control.recovery_hint}", flush=True)
                last_control_status = status

    def switch(scheme):
        if not compare:
            return
        if selected["scheme"] == scheme:
            return
        selected["scheme"] = scheme
        now = time.monotonic()
        if b_control.enabled or b_control.button_down:
            b_control.pause(now, "SCHEME_SWITCH")
        assert session_a is not None
        session_a.cleanup(now, "SCHEME_SWITCH")
        session_b.detector.reset()
        session_b._clear()
        previous["gesture"] = None
        recent.clear()
        print(f"[SCHEME] {scheme}", flush=True)

    def overlay(frame, hand, fps, model_path):
        now = time.monotonic()
        width, height = frame.shape[1::-1]
        draw_hand(frame, hand)
        if selected["scheme"] == "A":
            assert session_a is not None
            state, position, events = session_a.update(hand, (width, height), now)
            for event in events:
                message = f"{event.kind}{f' x{event.amount}' if getattr(event, 'amount', 0) else ''}{f' {event.reason}' if event.reason else ''}"
                recent.insert(0, message)
            draw_status(frame, hand, fps, state, config, screen_size, position,
                        session_a.scroll, recent[:4], session_a.controller,
                        status_note="PREVIEW ONLY | A/B switch | Q quit", stage_number=8,
                        mode_label="Scheme A")
        else:
            state, position, events = b_control.update(hand, (width, height), now)
            report_control_status()
            gesture_name = state.gesture.value
            candidate_name = state.candidate.value
            if previous["gesture"] != gesture_name:
                transition = f"{previous['gesture']} -> {gesture_name}" if previous["gesture"] else gesture_name
                recent.insert(0, transition)
                previous["gesture"] = gesture_name
            for event in events:
                recent.insert(0, event)
                print(f"[B] {event} | mode={b_control.mode_label}"
                      f" | output={b_control.input_status}", flush=True)
            active = position is not None and state.gesture in (
                SchemeBGesture.PINCH_AIM, SchemeBGesture.DRAG_OPEN)
            draw_screen_preview(frame, screen_size, position, active)
            lines = [
                f"AirControl | Scheme B | FPS: {fps:.1f}",
                f"Gesture: {gesture_name} | Candidate: {candidate_name} ({state.candidate_frames})",
                f"Virtual cursor: ({round(position.x)}, {round(position.y)})" if position else "Virtual cursor: -",
                f"Mode: {b_control.mode_label} | {b_control.reason}",
                f"Input: {b_control.input_status} | Left held: {b_control.button_down}",
                f"Aim locked: {state.aim_frozen}",
                b_control.recovery_hint,
                "C enable | P/F8 pause | E/F9 stop | Q/Esc quit",
                *(["A/B: switch scheme"] if compare else []),
                *recent[:4],
            ]
            cv2.rectangle(frame, (8, 8), (min(width - 8, 580), min(height - 8, 28 + 22 * len(lines))), (25, 25, 25), -1)
            for index, line in enumerate(lines):
                cv2.putText(frame, line, (18, 30 + index * 22), cv2.FONT_HERSHEY_SIMPLEX,
                            0.5, (220, 220, 220), 1, cv2.LINE_AA)
        del recent[8:]

    def on_key(key):
        if key == ord("a"):
            switch("A")
        elif key == ord("b"):
            switch("B")
        elif key == ord("c") and selected["scheme"] == "B":
            b_control.resume(time.monotonic())
        elif key == ord("p") and selected["scheme"] == "B":
            b_control.toggle_pause(time.monotonic())
        elif key == ord("e"):
            b_control.emergency_stop(time.monotonic(), "WINDOW_E")
        report_control_status()
        return monitor.exit_requested.is_set()

    mode = "REAL CONTROL" if args.control else "PREVIEW ONLY"
    print(f"AirControl {mode}. Scheme {scheme}." + (" A/B to switch." if compare else ""), flush=True)
    print("B control: C enable | P/F8 pause or resume | E/F9 stop | Esc stop and quit.", flush=True)
    print("Before control: hold a neutral pose (fist with thumb relaxed); wait for CONTROL.", flush=True)

    def cleanup():
        b_control.cleanup(time.monotonic(), "EXIT")

    try:
        monitor.start()
        title = "AirControl - A/B Comparison" if compare else "AirControl - Scheme B"
        run_preview(config, args.model, overlay, title, on_key=on_key,
                    on_exit=cleanup, should_stop=monitor.exit_requested.is_set)
    finally:
        try:
            cleanup()
        finally:
            monitor.close()
    if monitor.error is not None:
        raise RuntimeError("Safety monitor failed; control has stopped") from monitor.error


if __name__ == "__main__":
    main()
