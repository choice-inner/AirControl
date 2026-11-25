from __future__ import annotations

import argparse
import time
from pathlib import Path

import cv2

from config import Config
from gesture_detector import Gesture
from gesture_scheme_b import SchemeBDetector, SchemeBGesture, SchemeBSession
from mouse_output import PyAutoGuiMouseOutput
from safety_monitor import SafetyMonitor
from scroll_controller import ScrollController
from stage2_hand_preview import DEFAULT_MODEL, draw_hand, run_preview
from stage4_cursor_preview import draw_operation_region, draw_screen_preview, primary_screen_size
from stage6_scroll_preview import draw_status
from stage7_mouse_control import build_session as build_a_session
from stage8_b_control import SchemeBControl


def build_b_session(config: Config, screen_size):
    detector = SchemeBDetector(config.gesture_stable_frames, config.finger_min_angle)
    return SchemeBSession(detector, screen_size)


def main() -> None:
    parser = argparse.ArgumentParser(description="AirControl stage 8: compare gesture schemes A and B")
    parser.add_argument("--camera", type=int, default=0)
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--scheme", choices=("A", "B"), default="A")
    parser.add_argument("--control", action="store_true",
                        help="enable real mouse input for scheme B after neutral posture")
    args = parser.parse_args()
    if args.control and args.scheme != "B":
        parser.error("--control requires --scheme B")
    config = Config(camera_index=args.camera)
    screen_size = primary_screen_size()
    session_a = build_a_session(config, screen_size)
    session_b = build_b_session(config, screen_size)
    b_control = SchemeBControl(
        session_b, PyAutoGuiMouseOutput(screen_size),
        ScrollController(config.scroll_deadzone_px, config.scroll_step_px,
                         config.scroll_gain, config.scroll_max_steps_per_update,
                         config.scroll_min_interval, config.scroll_max_sample_gap),
        enabled=args.control, frame_timeout=config.control_frame_timeout,
    )
    monitor = SafetyMonitor(b_control, config.control_frame_timeout) if args.control else None
    selected = {"scheme": args.scheme}
    previous = {"gesture": None}
    recent: list[str] = []

    def switch(scheme):
        if selected["scheme"] == scheme:
            return
        selected["scheme"] = scheme
        now = time.monotonic()
        if b_control.enabled:
            b_control.pause(now, "SCHEME_SWITCH")
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
            state, position, events = session_a.update(hand, (width, height), now)
            for event in events:
                message = f"{event.kind}{f' x{event.amount}' if getattr(event, 'amount', 0) else ''}{f' {event.reason}' if event.reason else ''}"
                recent.insert(0, message)
            active = position is not None and state.gesture == Gesture.MOVE
            draw_status(frame, hand, fps, state, config, screen_size, position,
                        session_a.scroll, recent[:4], session_a.controller,
                        status_note="PREVIEW ONLY | A/B switch | Q quit", stage_number=8,
                        mode_label="Scheme A")
        else:
            state, position, events = b_control.update(hand, (width, height), now)
            gesture_name = state.gesture.value
            candidate_name = state.candidate.value
            if previous["gesture"] != gesture_name:
                transition = f"{previous['gesture']} -> {gesture_name}" if previous["gesture"] else gesture_name
                recent.insert(0, transition)
                previous["gesture"] = gesture_name
            for event in events:
                recent.insert(0, event)
                print(f"[B] {event}", flush=True)
            active = position is not None and state.gesture == SchemeBGesture.PINCH_AIM
            draw_operation_region(frame, config)
            draw_screen_preview(frame, screen_size, position, active)
            lines = [
                f"Stage 8 | Scheme B | FPS: {fps:.1f}",
                f"Gesture: {gesture_name} | Candidate: {candidate_name} ({state.candidate_frames})",
                f"Mapped: ({round(position.x)}, {round(position.y)})" if position else "Mapped: -",
                f"{b_control.mode_label} | A/B switch | C enable | P pause | E stop | Q quit",
                f"Input: {b_control.input_status}",
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
        elif key == ord("c"):
            b_control.resume(time.monotonic())
        elif key == ord("p"):
            b_control.toggle_pause(time.monotonic())
        elif key == ord("e"):
            b_control.emergency_stop(time.monotonic(), "WINDOW_E")
        return bool(monitor and monitor.exit_requested.is_set())

    mode = "REAL CONTROL" if args.control else "PREVIEW ONLY"
    print(f"Stage 8 {mode}. Starting scheme {args.scheme}. Press A or B to switch.", flush=True)
    print("B control: C enable | P/F8 pause or resume | E/F9 stop | Esc stop and quit.", flush=True)
    try:
        if monitor:
            monitor.start()
        run_preview(config, args.model, overlay, "AirControl - Stage 8 A/B Preview", on_key=on_key,
                    should_stop=monitor.exit_requested.is_set if monitor else None)
    finally:
        if b_control.enabled or b_control.button_down:
            b_control.cleanup(time.monotonic(), "EXIT")
        if monitor:
            monitor.close()
    if monitor and monitor.error is not None:
        raise RuntimeError("Safety monitor failed; control has stopped") from monitor.error


if __name__ == "__main__":
    main()
