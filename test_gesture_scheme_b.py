import unittest
import math
from types import SimpleNamespace

from gesture_scheme_b import SchemeBDetector, SchemeBGesture, SchemeBSession
from test_gesture_detector import make_hand
from test_stage5_click_drag_preview import preview_hand_from


def sample(*, index_up=True, middle_up=False, ring_up=False, pinky_up=False, pinch_ratio=0.8, dx=0, dy=0):
    hand = make_hand(index_up=index_up, middle_up=middle_up, pinch_ratio=pinch_ratio)
    for mcp, up in ((13, ring_up), (17, pinky_up)):
        x = hand.points[mcp][0]
        hand.points[mcp] = (x, 0.6, 0)
        if up:
            hand.points[mcp + 1:mcp + 4] = [
                (x, 0.45, 0), (x, 0.32, 0), (x, 0.2, 0),
            ]
        else:
            hand.points[mcp + 1:mcp + 4] = [
                (x, 0.46, 0), (x + 0.04, 0.54, 0), (x + 0.01, 0.6, 0),
            ]
    hand.points = [(x + dx, y + dy, z) for x, y, z in hand.points]
    return preview_hand_from(hand)


def open_hand(dx=0, dy=0):
    hand = make_hand(index_up=True, middle_up=True)
    for mcp, x in ((5, 0.34), (9, 0.45), (13, 0.56), (17, 0.68)):
        hand.points[mcp] = (x, 0.6, 0)
        hand.points[mcp + 1:mcp + 4] = [
            (x, 0.45, 0), (x, 0.32, 0), (x, 0.2, 0),
        ]
    hand.points[4] = (0.82, 0.4, 0)
    hand.points = [(x + dx, y + dy, z) for x, y, z in hand.points]
    return preview_hand_from(hand)


class SchemeBDetectorTests(unittest.TestCase):
    def setUp(self):
        self.detector = SchemeBDetector(stable_frames=3)

    def settle(self, hand, frames=3):
        for _ in range(frames):
            state = self.detector.update(hand, (640, 480))
        return state

    def test_pinch_aim_requires_stable_pinch(self):
        gesture = sample(pinch_ratio=0.3)
        self.assertEqual(self.detector.update(gesture, (640, 480)).gesture, SchemeBGesture.NONE)
        self.assertEqual(self.detector.update(gesture, (640, 480)).candidate_frames, 2)
        self.assertEqual(self.detector.update(gesture, (640, 480)).gesture, SchemeBGesture.PINCH_AIM)

    def test_more_open_pinch_is_recognized_at_the_new_entry_threshold(self):
        state = self.settle(sample(pinch_ratio=0.40))
        self.assertEqual(state.gesture, SchemeBGesture.PINCH_AIM)

    def test_small_distance_jitter_does_not_drop_aim_or_restart_it(self):
        self.settle(sample(pinch_ratio=0.40))
        for ratio in (0.44, 0.50, 0.39, 0.54, 0.45):
            state = self.detector.update(sample(pinch_ratio=ratio), (640, 480))
            self.assertEqual(state.gesture, SchemeBGesture.PINCH_AIM)
            self.assertEqual(state.candidate, SchemeBGesture.PINCH_AIM)
            self.assertNotIn("PINCH_AIM_END", state.events)

    def test_brief_other_finger_misclassification_does_not_interrupt_pinch_aim(self):
        self.settle(sample(pinch_ratio=0.3))
        for _ in range(2):
            state = self.detector.update(sample(pinch_ratio=0.3, middle_up=True), (640, 480))
            self.assertEqual(state.gesture, SchemeBGesture.PINCH_AIM)
            self.assertEqual(state.candidate, SchemeBGesture.PINCH_AIM)

    def test_pinch_proximity_alone_arms_aim_even_when_finger_angles_are_misclassified(self):
        state = self.settle(sample(index_up=False, middle_up=True, ring_up=True,
                                    pinky_up=True, pinch_ratio=0.3))
        self.assertEqual(state.gesture, SchemeBGesture.PINCH_AIM)

    def test_sustained_release_or_scroll_posture_exits_aim_after_stability(self):
        self.settle(sample(pinch_ratio=0.3))
        released = self.settle(sample(pinch_ratio=0.62))
        self.assertEqual(released.gesture, SchemeBGesture.NONE)
        self.settle(sample(pinch_ratio=0.3))
        scroll = self.settle(sample(middle_up=True))
        self.assertEqual(scroll.gesture, SchemeBGesture.SCROLL)

    def test_wide_thumb_index_open_after_pinch_emits_single_click(self):
        self.settle(sample(pinch_ratio=0.3))
        wide = sample(pinch_ratio=0.85)
        self.assertEqual(self.detector.update(wide, (640, 480)).gesture, SchemeBGesture.PINCH_AIM)
        self.assertEqual(self.detector.update(wide, (640, 480)).gesture, SchemeBGesture.PINCH_AIM)
        state = self.detector.update(wide, (640, 480))
        self.assertEqual(state.gesture, SchemeBGesture.CLICK_OPEN)
        self.assertEqual(state.events.count("CLICK"), 1)
        self.assertNotIn("CLICK", self.detector.update(wide, (640, 480)).events)

    def test_scroll_posture_is_distinct_from_click_and_pinch(self):
        state = self.settle(sample(middle_up=True))
        self.assertEqual(state.gesture, SchemeBGesture.SCROLL)
        self.assertEqual(self.settle(sample(pinch_ratio=0.3), 5).gesture,
                         SchemeBGesture.PINCH_AIM)

    def test_spread_click_requires_middle_ring_and_pinky_curled(self):
        self.settle(sample(pinch_ratio=0.3))
        state = self.settle(sample(pinch_ratio=0.85, middle_up=True))
        self.assertNotEqual(state.gesture, SchemeBGesture.CLICK_OPEN)

    def test_spread_click_requires_index_extended(self):
        self.settle(sample(pinch_ratio=0.3))
        folded_index = sample(pinch_ratio=0.85)
        points = list(folded_index.points)
        points[7] = points[6]
        points[8] = points[6]
        folded_index.points = points
        state = self.settle(preview_hand_from(folded_index))
        self.assertNotEqual(state.gesture, SchemeBGesture.CLICK_OPEN)

    def test_open_palm_requires_thumb_spread(self):
        closed_thumb = open_hand()
        points = list(closed_thumb.points)
        points[4] = points[5]
        closed_thumb.points = points
        state = self.settle(preview_hand_from(closed_thumb))
        self.assertNotEqual(state.gesture, SchemeBGesture.DRAG_OPEN)

    def test_open_palm_drag_tolerates_one_missed_finger_and_moderate_thumb_spread(self):
        hand = open_hand()
        points = list(hand.points)
        x = points[17][0]
        points[18:21] = [(x + 0.04, 0.55, 0), (x + 0.02, 0.61, 0),
                         (x - 0.02, 0.61, 0)]
        thumb, base = points[4], points[5]
        factor = 0.41
        points[4] = tuple(base[i] + (thumb[i] - base[i]) * factor for i in range(3))
        hand.points = points
        self.assertEqual(self.settle(preview_hand_from(hand)).gesture,
                         SchemeBGesture.DRAG_OPEN)

    def test_full_hand_open_is_drag_and_releases_after_pose_changes(self):
        self.assertEqual(self.settle(open_hand()).gesture, SchemeBGesture.DRAG_OPEN)
        for _ in range(4):
            state = self.detector.update(sample(), (640, 480))
            self.assertEqual(state.gesture, SchemeBGesture.DRAG_OPEN)
        state = self.detector.update(sample(), (640, 480))
        self.assertEqual(state.gesture, SchemeBGesture.NONE)

    def test_brief_posture_noise_does_not_end_drag_or_scroll(self):
        self.settle(open_hand())
        for _ in range(4):
            self.assertEqual(self.detector.update(sample(), (640, 480)).gesture,
                             SchemeBGesture.DRAG_OPEN)
        self.detector.reset()
        self.settle(sample(middle_up=True))
        for _ in range(4):
            self.assertEqual(self.detector.update(sample(), (640, 480)).gesture,
                             SchemeBGesture.SCROLL)

    def test_hand_loss_resets_classifier(self):
        self.settle(sample(pinch_ratio=0.3))
        state = self.detector.update(None, (640, 480))
        self.assertEqual(state.gesture, SchemeBGesture.NONE)
        self.assertEqual(state.events, ("PINCH_AIM_END",))


class SchemeBSessionTests(unittest.TestCase):
    def setUp(self):
        self.session = SchemeBSession(SchemeBDetector(3), (1000, 800), sensitivity=1, smoothing=1)

    def settle(self, hand, frames=3):
        for _ in range(frames):
            state, position, events = self.session.update(hand, (640, 480))
        return state, position, events

    def test_relative_pinch_aim_starts_at_center_and_moves_by_delta(self):
        _, first, events = self.settle(sample(pinch_ratio=0.3))
        self.assertEqual((first.x, first.y), (499.5, 399.5))
        self.assertIn("AIM_START", events)
        _, moved, _ = self.settle(sample(pinch_ratio=0.3, dx=0.1))
        self.assertGreater(moved.x, first.x)
        self.assertAlmostEqual(moved.x - first.x, 1000 * 0.1 * 0.75, delta=1)

    def test_session_keeps_one_aim_anchor_through_distance_jitter(self):
        _, first, _ = self.settle(sample(pinch_ratio=0.40))
        for ratio in (0.45, 0.51, 0.43, 0.54):
            state, position, events = self.settle(sample(pinch_ratio=ratio), 1)
            self.assertEqual(state.gesture, SchemeBGesture.PINCH_AIM)
            self.assertNotIn("AIM_START", events)
            self.assertLess(math.dist((position.x, position.y), (first.x, first.y)), 40)

    def test_cursor_freezes_when_spread_click_candidate_starts(self):
        self.settle(sample(pinch_ratio=0.3))
        _, target, _ = self.settle(sample(pinch_ratio=0.3, dx=0.08))
        spread = sample(pinch_ratio=0.85, dx=0.14)
        state, frozen, _ = self.session.update(spread, (640, 480))
        self.assertEqual(state.gesture, SchemeBGesture.PINCH_AIM)
        self.assertEqual(state.candidate, SchemeBGesture.CLICK_OPEN)
        self.assertEqual(frozen, target)
        state, frozen, _ = self.session.update(sample(pinch_ratio=0.85, dx=0.18), (640, 480))
        self.assertEqual(state.gesture, SchemeBGesture.PINCH_AIM)
        self.assertEqual(frozen, target)
        state, clicked, events = self.session.update(sample(pinch_ratio=0.85, dx=0.22), (640, 480))
        self.assertEqual(state.gesture, SchemeBGesture.CLICK_OPEN)
        self.assertEqual(clicked, target)
        self.assertIn("CLICK", events)

    def test_aim_cursor_tracks_thumb_tip_not_index_tip(self):
        _, origin, _ = self.settle(sample(pinch_ratio=0.3))

        index_only = sample(pinch_ratio=0.3)
        points = list(index_only.landmarks)
        point = points[8]
        points[8] = SimpleNamespace(x=point.x + 0.01, y=point.y, z=point.z)
        index_only.landmarks = tuple(points)
        _, after_index, _ = self.settle(index_only, 1)
        self.assertEqual(after_index, origin)

        thumb_only = sample(pinch_ratio=0.3)
        points = list(thumb_only.landmarks)
        point = points[4]
        points[4] = SimpleNamespace(x=point.x + 0.01, y=point.y, z=point.z)
        thumb_only.landmarks = tuple(points)
        state, after_thumb, _ = self.settle(thumb_only, 1)
        self.assertEqual(state.gesture, SchemeBGesture.PINCH_AIM)
        self.assertGreater(after_thumb.x, after_index.x)

    def test_open_palm_drag_moves_cursor_and_emits_start_end(self):
        _, _, _ = self.settle(sample(pinch_ratio=0.3))
        _, origin, _ = self.settle(open_hand())
        state, moved, events = self.settle(open_hand(dx=0.1))
        self.assertEqual(state.gesture, SchemeBGesture.DRAG_OPEN)
        self.assertGreater(moved.x, origin.x)
        self.assertNotIn("DRAG_START", events)
        _, _, events = self.settle(sample(), 5)
        self.assertIn("DRAG_END", events)

    def test_drag_position_uses_thumb_tip_not_palm_motion(self):
        self.settle(open_hand())
        _, origin, _ = self.settle(open_hand())

        palm_only = open_hand()
        points = list(palm_only.landmarks)
        for index in (0, 5, 9, 13, 17):
            p = points[index]
            points[index] = SimpleNamespace(x=p.x + 0.08, y=p.y, z=p.z)
        palm_only.landmarks = tuple(points)
        _, after_palm, _ = self.settle(palm_only, 1)
        self.assertEqual(after_palm, origin)

        thumb_only = open_hand()
        points = list(thumb_only.landmarks)
        p = points[4]
        points[4] = SimpleNamespace(x=p.x + 0.02, y=p.y, z=p.z)
        thumb_only.landmarks = tuple(points)
        _, after_thumb, _ = self.settle(thumb_only, 1)
        self.assertGreater(after_thumb.x, after_palm.x)

    def test_large_target_error_increases_smoothing_response(self):
        session = SchemeBSession(SchemeBDetector(3), (1000, 800),
                                sensitivity=1, smoothing=0.4)
        session._set_position(100, 100)
        session._move_toward(110, 100)
        small_step = session.position.x - 100
        session._set_position(100, 100)
        session._move_toward(300, 100)
        large_step = session.position.x - 100
        self.assertGreater(large_step / 200, small_step / 10)
        self.assertAlmostEqual(large_step / 200, 0.9)

    def test_click_and_drag_are_preview_events_only(self):
        self.settle(sample(pinch_ratio=0.3))
        _, _, events = self.settle(sample(pinch_ratio=0.85))
        self.assertIn("CLICK", events)
        _, _, events = self.settle(open_hand())
        self.assertIn("DRAG_START", events)

    def test_loss_clears_virtual_cursor_and_active_drag(self):
        self.settle(open_hand())
        _, _, _ = self.settle(open_hand())
        state, position, events = self.session.update(None, (640, 480))
        self.assertIsNone(position)
        self.assertIn("DRAG_END HAND_LOST", events)
        self.assertEqual(state.gesture, SchemeBGesture.NONE)


if __name__ == "__main__":
    unittest.main()
