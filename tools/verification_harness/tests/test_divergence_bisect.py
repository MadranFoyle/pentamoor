import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from divergence_bisect import bisect_divergence


def make_sides(diverge_at):
    def side_a(t):
        return 0

    def side_b(t):
        return 0 if t < diverge_at else 1

    return side_a, side_b


def int_diff(a, b):
    return [] if a == b else [f"{a} != {b}"]


class TestBisect(unittest.TestCase):
    def test_finds_exact_divergence_point(self):
        side_a, side_b = make_sides(diverge_at=37)
        result = bisect_divergence(side_a, side_b, int_diff, max_tick=100)
        self.assertIsNotNone(result)
        tick, diff = result
        self.assertEqual(tick, 37)
        self.assertEqual(diff, ["0 != 1"])

    def test_no_divergence_returns_none(self):
        side_a, side_b = make_sides(diverge_at=1000)  # never within range
        result = bisect_divergence(side_a, side_b, int_diff, max_tick=100)
        self.assertIsNone(result)

    def test_divergence_at_tick_zero(self):
        side_a, side_b = make_sides(diverge_at=0)
        result = bisect_divergence(side_a, side_b, int_diff, max_tick=100)
        self.assertEqual(result[0], 0)

    def test_divergence_at_max_tick(self):
        side_a, side_b = make_sides(diverge_at=100)
        result = bisect_divergence(side_a, side_b, int_diff, max_tick=100)
        self.assertEqual(result[0], 100)


if __name__ == "__main__":
    unittest.main()
