import math
import unittest

from cursor_mapper import CursorMapper


class CursorMapperTests(unittest.TestCase):
    def test_operation_area_maps_to_all_screen_corners_and_center(self):
        for point, expected in (
            ((0.1, 0.2), (0, 0)), ((0.9, 0.2), (1919, 0)),
            ((0.1, 0.8), (0, 1079)), ((0.9, 0.8), (1919, 1079)),
            ((0.5, 0.5), (959.5, 539.5)),
        ):
            with self.subTest(point=point):
                mapper = CursorMapper((1920, 1080), margin_x=0.1, margin_y=0.2)
                position = mapper.update(*point)
                self.assertAlmostEqual(position.x, expected[0])
                self.assertAlmostEqual(position.y, expected[1])

    def test_coordinates_outside_region_are_clamped(self):
        for point, expected in (((-2, -1), (0, 0)), ((2, 3), (99, 79))):
            mapper = CursorMapper((100, 80), margin_x=0.1, margin_y=0.1)
            position = mapper.update(*point)
            self.assertEqual((position.x, position.y), expected)

    def test_exponential_smoothing_uses_configured_alpha_at_30_fps(self):
        mapper = CursorMapper((101, 101), smoothing=0.25, margin_x=0, margin_y=0, max_speed=100)
        mapper.update(0.2, 0.4, timestamp=0)
        position = mapper.update(0.6, 0.8, timestamp=1 / 30)
        self.assertAlmostEqual(position.x, 30)
        self.assertAlmostEqual(position.y, 50)
        self.assertAlmostEqual(position.normalized_x, 0.3)
        self.assertEqual((position.target_x, position.target_y), (60, 80))

    def test_smoothing_has_same_response_at_30_and_60_fps(self):
        results = []
        for fps in (30, 60):
            mapper = CursorMapper((101, 101), smoothing=0.25, margin_x=0, margin_y=0,
                                  max_speed=100, jitter_deadzone_px=0)
            mapper.update(0, 0, timestamp=0)
            for step in range(1, fps + 1):
                position = mapper.update(1, 1, timestamp=step / fps)
            results.append(position.x)
        self.assertAlmostEqual(*results)

    def test_inactive_period_clears_history_and_reinitializes_at_current_point(self):
        mapper = CursorMapper((101, 101), margin_x=0, margin_y=0)
        mapper.update(0.1, 0.1, timestamp=0)
        self.assertIsNone(mapper.update(0, 0, active=False))
        self.assertIsNone(mapper.last_position)
        resumed = mapper.update(0.9, 0.8, timestamp=100)
        self.assertEqual((resumed.x, resumed.y), (90, 80))
        following = mapper.update(0.9, 0.8, timestamp=100 + 1 / 30)
        self.assertEqual((following.x, following.y), (90, 80))

    def test_speed_limit_bounds_outliers_and_long_frame_stalls(self):
        mapper = CursorMapper((101, 101), smoothing=1, margin_x=0, margin_y=0, max_speed=1,
                              jitter_deadzone_px=0)
        mapper.update(0, 0, timestamp=0)
        position = mapper.update(1, 1, timestamp=1 / 30)
        self.assertAlmostEqual(math.hypot(position.x, position.y), math.hypot(100, 100) / 30)
        next_position = mapper.update(1, 1, timestamp=50)
        displacement = math.hypot(next_position.x - position.x, next_position.y - position.y)
        self.assertAlmostEqual(displacement, math.hypot(100, 100) * 0.05)

    def test_invalid_samples_clear_filter_and_position(self):
        for value in (math.nan, math.inf):
            mapper = CursorMapper((101, 101), margin_x=0, margin_y=0)
            mapper.update(0.2, 0.2, timestamp=0)
            self.assertIsNone(mapper.update(value, 0.5, timestamp=1))
            self.assertIsNone(mapper.last_position)
            resumed = mapper.update(0.8, 0.8, timestamp=2)
            self.assertEqual((resumed.x, resumed.y), (80, 80))

    def test_constant_input_stays_still(self):
        mapper = CursorMapper((1920, 1080))
        first = mapper.update(0.5, 0.5, timestamp=0)
        for step in range(1, 61):
            position = mapper.update(0.5, 0.5, timestamp=step / 60)
            self.assertEqual((position.x, position.y), (first.x, first.y))

    def test_jitter_inside_deadzone_keeps_actual_output_still(self):
        mapper = CursorMapper((101, 101), smoothing=1, margin_x=0, margin_y=0,
                              max_speed=100, jitter_deadzone_px=4)
        first = mapper.update(0.5, 0.5, timestamp=0)
        for step, x in enumerate((0.52, 0.48, 0.53, 0.49), 1):
            position = mapper.update(x, 0.5, timestamp=step / 30)
            self.assertEqual(position.x, first.x)

    def test_small_motion_accumulates_until_filtered_position_crosses_deadzone(self):
        mapper = CursorMapper((101, 101), smoothing=1, margin_x=0, margin_y=0,
                              max_speed=100, jitter_deadzone_px=4)
        first = mapper.update(0.5, 0.5, timestamp=0)
        for step in range(1, 4):
            position = mapper.update(0.5 + step * 0.01, 0.5, timestamp=step / 30)
            self.assertEqual(position.x, first.x)
        position = mapper.update(0.54, 0.5, timestamp=4 / 30)
        self.assertAlmostEqual(position.x, 54)

    def test_zero_deadzone_preserves_existing_filter_response(self):
        mapper = CursorMapper((101, 101), smoothing=0.25, margin_x=0, margin_y=0,
                              max_speed=100, jitter_deadzone_px=0)
        mapper.update(0.2, 0.4, timestamp=0)
        position = mapper.update(0.6, 0.8, timestamp=1 / 30)
        self.assertAlmostEqual(position.x, 30)
        self.assertAlmostEqual(position.y, 50)

    def test_invalid_screen_parameters_and_timestamps_are_rejected(self):
        for screen_size in ((1, 10), (10, 0), (math.nan, 100), (100.5, 100)):
            with self.subTest(screen_size=screen_size), self.assertRaises(ValueError):
                CursorMapper(screen_size)
        for value in (0, -0.1, 1.1, math.nan):
            with self.subTest(smoothing=value), self.assertRaises(ValueError):
                CursorMapper((100, 100), smoothing=value)
        for name in ("margin_x", "margin_y"):
            for value in (-0.1, 0.5, math.inf):
                with self.subTest(name=name, value=value), self.assertRaises(ValueError):
                    CursorMapper((100, 100), **{name: value})
        for speed in (0, -1, math.inf):
            with self.subTest(speed=speed), self.assertRaises(ValueError):
                CursorMapper((100, 100), max_speed=speed)
        for deadzone in (-0.1, math.nan, math.inf):
            with self.subTest(deadzone=deadzone), self.assertRaises(ValueError):
                CursorMapper((100, 100), jitter_deadzone_px=deadzone)
        mapper = CursorMapper((100, 100))
        mapper.update(0.5, 0.5, timestamp=1)
        with self.assertRaises(ValueError):
            mapper.update(0.5, 0.5, timestamp=0)
        with self.assertRaises(ValueError):
            mapper.update(0.5, 0.5, timestamp=math.nan)


if __name__ == "__main__":
    unittest.main()
