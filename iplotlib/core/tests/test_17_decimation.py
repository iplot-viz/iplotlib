# Description: Tests for minmax_decimate, including the NaN-gap handling that
# keeps the streaming archive/live break intact through display decimation.

import unittest

import numpy as np

from iplotlib.core.decimation import bucket_reduce_envelope, minmax_decimate


class MinMaxDecimateTests(unittest.TestCase):

    def test_passthrough_when_below_target(self):
        x = np.arange(6)
        y = np.arange(6, dtype=float)
        ox, oy = minmax_decimate(x, y, 5)
        self.assertTrue(np.array_equal(ox, x))
        self.assertTrue(np.array_equal(oy, y))

    def test_preserves_extremes_without_nan(self):
        x = np.arange(1000)
        y = np.zeros(1000)
        y[300] = -7.0
        y[700] = 9.0
        ox, oy = minmax_decimate(x, y, 50)
        self.assertLessEqual(len(ox), 2 * 50 + 2)
        self.assertIn(-7.0, oy)
        self.assertIn(9.0, oy)
        self.assertTrue(np.all(np.diff(ox) >= 0))

    def test_keeps_a_single_nan_gap_as_one_break(self):
        x = np.arange(1000)
        y = np.zeros(1000)
        y[500] = np.nan
        ox, oy = minmax_decimate(x, y, 20)
        self.assertEqual(int(np.isnan(oy).sum()), 1)

    def test_nan_does_not_poison_neighbouring_buckets(self):
        x = np.arange(1000)
        y = np.zeros(1000)
        y[100] = -5.0    # extreme in the first run
        y[500] = np.nan  # gap
        y[900] = 8.0     # extreme in the second run
        ox, oy = minmax_decimate(x, y, 20)
        finite = oy[np.isfinite(oy)]
        self.assertIn(-5.0, finite)
        self.assertIn(8.0, finite)
        self.assertTrue(np.all(np.diff(ox) >= 0))

    def test_gap_x_sits_between_the_two_runs(self):
        x = np.arange(1000)
        y = np.zeros(1000)
        y[500] = np.nan
        ox, oy = minmax_decimate(x, y, 20)
        gap_x = ox[np.isnan(oy)][0]
        self.assertTrue(0 < gap_x < 999)

    def test_multiple_gaps_are_all_kept(self):
        x = np.arange(1500)
        y = np.zeros(1500)
        y[400] = np.nan
        y[900] = np.nan
        ox, oy = minmax_decimate(x, y, 30)
        self.assertEqual(int(np.isnan(oy).sum()), 2)

    def test_short_input_is_returned_untouched(self):
        x = np.arange(3)
        y = np.array([1.0, np.nan, 2.0])
        ox, oy = minmax_decimate(x, y, 20)
        self.assertTrue(np.array_equal(ox, x))
        self.assertTrue(np.isnan(oy[1]))

    def test_output_meets_the_budget_when_ratio_is_just_above_two(self):
        # n / pairs slightly above 2 used to ceil into 3-sized buckets and
        # return only 2n/3 points, silently shrinking capped buffers.
        n, pairs = 10104, 4990
        x = np.arange(n)
        y = np.sin(np.linspace(0, 400, n))
        ox, oy = minmax_decimate(x, y, pairs)
        self.assertEqual(len(ox), 2 * pairs)
        self.assertEqual(oy.min(), y.min())
        self.assertEqual(oy.max(), y.max())
        self.assertTrue(np.all(np.diff(ox) >= 0))

    def test_envelope_reduction_fills_the_whole_budget(self):
        n, target = 10104, 10000
        x = np.arange(n)
        y = np.sin(np.linspace(0, 400, n))
        ox, omin, omax, oavg = bucket_reduce_envelope(x, y - 1, y + 1, y, target)
        self.assertEqual(len(ox), target)
        self.assertTrue(np.all(omin <= oavg + 1e-9))
        self.assertTrue(np.all(oavg <= omax + 1e-9))


if __name__ == '__main__':
    unittest.main()
