import unittest

from mouse_autoscroll.curve import Curve, speed

CURVE = Curve(
    deadzone=12, min_speed=1.0, slope=0.0086, exponent=1.3, edge_zone=0.05, max_speed=250
)
# Axis of a 1080 px tall screen, origin 540 px from the edge we move towards.
EDGE = dict(edge_distance=540, screen_size=1080)


class MainZoneTest(unittest.TestCase):
    def test_zero_inside_deadzone(self):
        for d in (0, 5, -5, 12, -12):
            self.assertEqual(speed(d, CURVE), 0.0)

    def test_starts_at_min_speed(self):
        self.assertAlmostEqual(speed(12.01, CURVE), 1.0, places=2)

    def test_sign_follows_offset(self):
        self.assertGreater(speed(40, CURVE), 0)
        self.assertLess(speed(-40, CURVE), 0)
        self.assertAlmostEqual(speed(80, CURVE), -speed(-80, CURVE))

    def test_gentle_growth(self):
        # ~15 notches/s at 300 px: no runaway acceleration in the main zone
        self.assertGreater(speed(300, CURVE), 10)
        self.assertLess(speed(300, CURVE), 20)

    def test_monotonic(self):
        speeds = [speed(d, CURVE, **EDGE) for d in range(13, 541)]
        self.assertEqual(speeds, sorted(speeds))

    def test_capped_without_geometry(self):
        self.assertEqual(speed(100000, CURVE), 250)


class SensitivityTest(unittest.TestCase):
    def test_scales_main_zone(self):
        fast = Curve(12, 1.0, 0.0086, 1.3, 0.05, 250, sensitivity=1.5)
        self.assertAlmostEqual(speed(300, fast), 1.5 * speed(300, CURVE))

    def test_default_is_neutral(self):
        self.assertEqual(CURVE.sensitivity, 1.0)

    def test_edge_still_reaches_max(self):
        slow = Curve(12, 1.0, 0.0086, 1.3, 0.05, 250, sensitivity=0.5)
        self.assertAlmostEqual(speed(540, slow, **EDGE), 250)


class EdgeZoneTest(unittest.TestCase):
    # Edge zone = last 5 % of 1080 px = 54 px, so it starts 486 px from the origin.

    def test_no_boost_before_edge_zone(self):
        self.assertAlmostEqual(speed(480, CURVE, **EDGE), speed(480, CURVE), places=6)

    def test_reaches_max_at_the_edge(self):
        self.assertAlmostEqual(speed(540, CURVE, **EDGE), 250)

    def test_exponential_inside_zone(self):
        start = speed(486, CURVE, **EDGE)
        mid = speed(513, CURVE, **EDGE)
        end = speed(540, CURVE, **EDGE)
        # geometric growth: the midpoint is the geometric mean of the ends
        self.assertAlmostEqual(mid, (start * end) ** 0.5, delta=0.5)
        self.assertGreater(mid, speed(513, CURVE))

    def test_origin_already_near_edge(self):
        # 30 px to the edge: the whole way is edge zone, still capped and positive
        v = speed(20, CURVE, edge_distance=30, screen_size=1080)
        self.assertGreater(v, speed(20, CURVE))
        self.assertLessEqual(v, 250)

    def test_negative_direction(self):
        self.assertAlmostEqual(speed(-540, CURVE, **EDGE), -250)


if __name__ == "__main__":
    unittest.main()
