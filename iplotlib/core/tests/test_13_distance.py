"""Unit tests for DistanceCalculator (MOUSE_MODE_DIST backend).

DistanceCalculator is the state machine that backs the distance/ruler
tool in the UI: the user clicks a source point, then a destination point,
and the tool displays delta x / y between the two. Numeric mode uses
plain subtraction; datetime mode formats the delta as days/hours/min/sec
plus nanosecond breakdown (ITER nanosecond precision). Both paths have
been sources of off-by-one / formatting bugs historically.
"""

import unittest

from iplotlib.core.distance import DistanceCalculator


class DistanceNumericTest(unittest.TestCase):
    def setUp(self) -> None:
        self.calc = DistanceCalculator()

    def test_fresh_calculator_is_invalid(self):
        self.assertFalse(self.calc.is_valid())
        dx, dy, dz = self.calc.dist()
        self.assertEqual((dx, dy, dz), (None, None, None))

    def test_only_source_set_is_invalid(self):
        self.calc.set_src(1.0, 2.0, plot='p', stack_key='s')
        self.assertFalse(self.calc.is_valid())

    def test_src_and_dst_same_plot_same_stack_is_valid(self):
        self.calc.set_src(1.0, 2.0, plot='p', stack_key='s')
        self.calc.set_dst(4.0, 6.0, plot='p', stack_key='s')
        self.assertTrue(self.calc.is_valid())
        dx, dy, dz = self.calc.dist()
        self.assertAlmostEqual(dx, 3.0)
        self.assertAlmostEqual(dy, 4.0)
        self.assertAlmostEqual(dz, 0.0)

    def test_different_plots_is_invalid(self):
        self.calc.set_src(1.0, 2.0, plot='p1', stack_key='s')
        self.calc.set_dst(4.0, 6.0, plot='p2', stack_key='s')
        self.assertFalse(self.calc.is_valid())

    def test_different_stacks_is_invalid(self):
        self.calc.set_src(1.0, 2.0, plot='p', stack_key='s1')
        self.calc.set_dst(4.0, 6.0, plot='p', stack_key='s2')
        self.assertFalse(self.calc.is_valid())

    def test_dist_is_absolute(self):
        """Distance must be non-negative regardless of src/dst order."""
        self.calc.set_src(10.0, 20.0, plot='p', stack_key='s')
        self.calc.set_dst(4.0, 6.0, plot='p', stack_key='s')
        dx, dy, _ = self.calc.dist()
        self.assertAlmostEqual(dx, 6.0)
        self.assertAlmostEqual(dy, 14.0)

    def test_z_component_respected(self):
        self.calc.set_src(0.0, 0.0, plot='p', stack_key='s', pz=1.0)
        self.calc.set_dst(0.0, 0.0, plot='p', stack_key='s', pz=4.5)
        _, _, dz = self.calc.dist()
        self.assertAlmostEqual(dz, 3.5)

    def test_reset_clears_state(self):
        self.calc.set_src(1.0, 2.0, plot='p', stack_key='s')
        self.calc.set_dst(4.0, 6.0, plot='p', stack_key='s')
        self.calc.reset()
        self.assertFalse(self.calc.is_valid())


class DistanceDatetimeTest(unittest.TestCase):
    """Datetime mode formats delta as a HH:MM:SS + ns breakdown string."""

    def setUp(self) -> None:
        self.calc = DistanceCalculator()
        self.calc.set_dx_is_datetime(True)

    def test_ten_seconds_apart(self):
        # 2024-01-15 12:34:56.000000000 and +10s
        t0 = 1705322096000000000
        t1 = t0 + 10 * 10**9
        self.calc.set_src(t0, 0.0, plot='p', stack_key='s')
        self.calc.set_dst(t1, 0.0, plot='p', stack_key='s')
        dx, _, _ = self.calc.dist()
        self.assertIn('T0H0M10S', dx)

    def test_nanosecond_precision_preserved(self):
        t0 = 1705322096000000000
        t1 = t0 + 456  # 456 ns
        self.calc.set_src(t0, 0.0, plot='p', stack_key='s')
        self.calc.set_dst(t1, 0.0, plot='p', stack_key='s')
        dx, _, _ = self.calc.dist()
        self.assertIn('+456n', dx)

    def test_one_day_plus_one_hour(self):
        t0 = 1705322096000000000
        t1 = t0 + (86400 + 3600) * 10**9
        self.calc.set_src(t0, 0.0, plot='p', stack_key='s')
        self.calc.set_dst(t1, 0.0, plot='p', stack_key='s')
        dx, _, _ = self.calc.dist()
        self.assertIn('1D', dx)
        self.assertIn('T1H', dx)


if __name__ == '__main__':
    unittest.main()
