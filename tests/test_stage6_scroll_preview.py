import unittest
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from aircontrol.click_drag_controller import ClickDragController, ClickDragMode
from aircontrol.config import Config
from aircontrol.cursor_mapper import CursorMapper
from aircontrol.gesture_detector import Gesture, GestureDetector
from aircontrol.scroll_controller import ScrollController, ScrollMode
from aircontrol.stage6_scroll_preview import Stage6Session, draw_status
from tests.test_gesture_detector import make_hand
from tests.test_stage5_click_drag_preview import preview_hand_from


def hand(middle_up=False, pinch_ratio=0.8, dy=0):
    result = make_hand(middle_up=middle_up, pinch_ratio=pinch_ratio)
    result.points = [(x, y + dy, z) for x, y, z in result.points]
    return preview_hand_from(result)


class Stage6SessionTests(unittest.TestCase):
    def setUp(self):
        self.session = Stage6Session(
            GestureDetector(0.34, 0.42), CursorMapper((1000, 1000)),
            ClickDragController(), ScrollController(),
        )
        self.timestamp = 0

    def update(self, sample):
        self.timestamp += 1 / 30
        return self.session.update(sample, (640, 480), self.timestamp)

    def settle(self, sample, frames=5):
        events = []
        for _ in range(frames):
            state, position, current = self.update(sample)
            events.extend(current)
        return state, position, events

    def test_scroll_confirmation_freezes_cursor_and_entry_never_scrolls(self):
        _, anchor, _ = self.settle(hand())
        state, frozen, events = self.settle(hand(middle_up=True))
        self.assertEqual(state.gesture, Gesture.SCROLL)
        self.assertEqual(frozen, anchor)
        self.assertEqual([event.kind for event in events], ["SCROLL_START"])
        self.assertIsNone(self.session.mapper.last_position)
        self.assertFalse(self.session.controller.button_down)
        state, frozen_again, events = self.settle(hand(middle_up=True, dy=-0.1))
        self.assertEqual(frozen_again, anchor)
        self.assertEqual([event.kind for event in events], ["SCROLL_UP"])

    def test_pinch_candidate_stops_scroll_immediately_without_click_or_press(self):
        self.settle(hand(middle_up=True))
        state, _, events = self.update(hand(middle_up=True, pinch_ratio=0.3))
        self.assertEqual(state.gesture, Gesture.SCROLL)
        self.assertEqual(state.candidate, Gesture.PINCH)
        self.assertEqual([event.kind for event in events], ["SCROLL_END"])
        self.assertEqual(self.session.scroll.mode, ScrollMode.IDLE)
        _, _, events = self.settle(hand(middle_up=True, pinch_ratio=0.3, dy=-0.2))
        self.assertEqual(events, [])
        self.assertFalse(self.session.controller.button_down)

    def test_click_then_drag_are_retained_and_drag_ends_before_scroll_starts(self):
        self.settle(hand())
        self.settle(hand(pinch_ratio=0.3), 3)
        _, _, events = self.settle(hand(), 3)
        self.assertIn("CLICK", [event.kind for event in events])
        self.settle(hand(pinch_ratio=0.3), 3)
        _, _, events = self.settle(hand(pinch_ratio=0.3, dy=0.2), 8)
        self.assertIn("DRAG_START", [event.kind for event in events])
        _, _, events = self.settle(hand(middle_up=True), 6)
        kinds = [event.kind for event in events]
        self.assertLess(kinds.index("DRAG_END"), kinds.index("SCROLL_START"))
        self.assertNotIn("CLICK", kinds)
        self.assertEqual(self.session.controller.mode, ClickDragMode.IDLE)

    def test_loss_invalid_hand_and_exit_clear_scroll_and_cursor(self):
        invalid = hand(middle_up=True)
        invalid.landmarks = (SimpleNamespace(x=float("nan"), y=0, z=0),) + invalid.landmarks[1:]
        for sample, reason in ((None, "HAND_LOST"), (invalid, "INVALID_HAND")):
            with self.subTest(reason=reason):
                self.settle(hand(middle_up=True))
                _, position, events = self.update(sample)
                self.assertIsNone(position)
                self.assertEqual([event.kind for event in events], ["SCROLL_END"])
                self.assertEqual(events[0].reason, reason)
                self.assertEqual(self.session.scroll.mode, ScrollMode.IDLE)
        self.settle(hand(middle_up=True))
        self.timestamp += 0.1
        self.assertEqual(self.session.cleanup(self.timestamp)[0].reason, "EXIT")
        self.assertEqual(self.session.cleanup(self.timestamp), ())

    def test_reentry_at_new_location_never_reuses_scroll_displacement(self):
        self.settle(hand(middle_up=True))
        self.update(None)
        _, _, events = self.settle(hand(middle_up=True, dy=0.25))
        self.assertEqual([event.kind for event in events], ["SCROLL_START"])
        self.settle(hand())
        _, _, events = self.settle(hand(middle_up=True, dy=-0.15))
        self.assertEqual([event.kind for event in events], ["SCROLL_START"])

    def test_render_shows_scroll_events_and_marks_frozen_cursor_inactive(self):
        self.settle(hand())
        state, position, events = self.settle(hand(middle_up=True))
        with patch("aircontrol.stage6_scroll_preview.draw_screen_preview") as screen:
            draw_status(np.zeros((480, 640, 3), dtype=np.uint8), hand(middle_up=True), 30,
                        state, Config(), (1000, 1000), position, self.session.scroll, events)
        self.assertFalse(screen.call_args.args[3])

    def test_render_accepts_preformatted_event_strings(self):
        state, position, _ = self.settle(hand())
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        with patch("aircontrol.stage6_scroll_preview.cv2.putText") as put_text:
            draw_status(frame, hand(), 30, state, Config(), (1000, 1000), position,
                        self.session.scroll, ["CLICK x=120 y=240"], self.session.controller)
        rendered = [call.args[1] for call in put_text.call_args_list]
        self.assertIn("CLICK x=120 y=240", rendered)


if __name__ == "__main__":
    unittest.main()
