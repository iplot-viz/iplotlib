# Description: Tests for minmax_decimate, including the NaN-gap handling that
# keeps the streaming archive/live break intact through display decimation.

import unittest

import numpy as np

from iplotlib.core.decimation import bucket_reduce_envelope, bucket_reduce_lines, minmax_decimate


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
        self.assertGreaterEqual(len(ox), 2 * pairs)
        self.assertLessEqual(len(ox), 2 * pairs + 2)
        self.assertEqual(oy.min(), y.min())
        self.assertEqual(oy.max(), y.max())
        self.assertTrue(np.all(np.diff(ox) >= 0))

    def test_run_endpoints_are_pinned(self):
        n = 10104
        x = np.arange(n)
        y = np.sin(np.linspace(0, 400, n))
        ox, oy = minmax_decimate(x, y, 4990)
        self.assertEqual(ox[0], x[0])
        self.assertEqual(ox[-1], x[-1])

    def test_repeated_decimation_does_not_erode_the_left_edge(self):
        # A capped stream re-decimates history as batches arrive; without
        # pinned endpoints and evenly spread buckets each pass ate the oldest
        # samples and the plotted block visibly shrank from the left.
        x = np.arange(10104, dtype=np.int64)
        y = np.sin(np.linspace(0, 400, 10104))
        for _ in range(300):
            x, y = minmax_decimate(x, y, 4990)
            new_x = np.arange(x[-1] + 1, x[-1] + 31, dtype=np.int64)
            x = np.concatenate([x, new_x])
            y = np.concatenate([y, np.zeros(30)])
        self.assertEqual(x[0], 0)

    def test_envelope_reduction_fills_the_whole_budget(self):
        n, target = 10104, 10000
        x = np.arange(n)
        y = np.sin(np.linspace(0, 400, n))
        ox, omin, omax, oavg = bucket_reduce_envelope(x, y - 1, y + 1, y, target)
        self.assertEqual(len(ox), target)
        self.assertTrue(np.all(omin <= oavg + 1e-9))
        self.assertTrue(np.all(oavg <= omax + 1e-9))

    def test_repeated_envelope_reduction_keeps_the_left_stamp(self):
        x = np.arange(10104, dtype=np.int64)
        lo = np.zeros(10104)
        hi = np.ones(10104)
        avg = np.full(10104, 0.5)
        for _ in range(300):
            x, lo, hi, avg = bucket_reduce_envelope(x, lo, hi, avg, 10000)
            new_x = np.arange(x[-1] + 1, x[-1] + 31, dtype=np.int64)
            x = np.concatenate([x, new_x])
            lo = np.concatenate([lo, np.zeros(30)])
            hi = np.concatenate([hi, np.ones(30)])
            avg = np.concatenate([avg, np.full(30, 0.5)])
        self.assertEqual(x[0], 0)


class BucketReduceLinesTests(unittest.TestCase):

    def test_keeps_the_first_extremes_and_last_of_each_bucket(self):
        x = np.arange(4000, dtype=np.int64)
        y = np.sin(np.linspace(0, 60, 4000))
        y[1234] = -5.0
        y[2345] = 7.0
        ox, oy = bucket_reduce_lines(x, y, 100)
        self.assertEqual(len(ox), 400)
        self.assertEqual(len(oy), 400)
        self.assertTrue(np.all(np.diff(ox) >= 0))
        buckets = y.reshape(100, 40)
        self.assertTrue(np.array_equal(oy[0::4], buckets[:, 0]))
        self.assertTrue(np.array_equal(oy[1::4], buckets.min(axis=1)))
        self.assertTrue(np.array_equal(oy[2::4], buckets.max(axis=1)))
        self.assertTrue(np.array_equal(oy[3::4], buckets[:, -1]))
        self.assertEqual((ox[0], ox[-1]), (0, 3999))
        # The extremes at the X of the middle sample of their span, the first and the last at their own.
        starts = np.arange(0, 4000, 40)
        self.assertTrue(np.array_equal(ox[0::4], x[starts]))
        self.assertTrue(np.array_equal(ox[1::4], x[starts + 19]))
        self.assertTrue(np.array_equal(ox[2::4], x[starts + 19]))
        self.assertTrue(np.array_equal(ox[3::4], x[starts + 39]))

    def test_lines_of_a_2d_y_share_their_x(self):
        rng = np.random.default_rng(3)
        x = np.linspace(0.0, 10.0, 5000)
        y = rng.standard_normal((5000, 3))
        ox, oy = bucket_reduce_lines(x, y, 200)
        self.assertEqual(oy.shape, (800, 3))
        for column in range(3):
            cx, cy = bucket_reduce_lines(x, np.ascontiguousarray(y[:, column]), 200)
            self.assertTrue(np.array_equal(cx, ox))
            self.assertTrue(np.array_equal(cy, oy[:, column]))

    def test_a_span_without_samples_draws_nothing(self):
        # Samples until 2000 s and again from 10000 s: nothing is drawn in between.
        x = np.concatenate((np.arange(0.0, 2000.0), np.arange(10000.0, 12000.0)))
        rng = np.random.default_rng(5)
        for name, y in (('1D', np.sin(x)), ('2D', rng.standard_normal((len(x), 3)))):
            with self.subTest(name):
                ox, oy = bucket_reduce_lines(x, y, 100)
                self.assertFalse(np.any((ox > 1999.0) & (ox < 10000.0)))
                self.assertEqual((ox[0], ox[-1]), (0.0, 11999.0))
                self.assertTrue(np.array_equal(oy.min(axis=0), y.min(axis=0)))
                self.assertTrue(np.array_equal(oy.max(axis=0), y.max(axis=0)))

    def test_lines_it_does_not_reduce_are_returned_as_they_are(self):
        x = np.arange(4000, dtype=float)
        y = np.ones(4000)
        gap = y.copy()
        gap[10] = np.nan
        endless = y.copy()
        endless[20] = np.inf
        backwards = x[::-1].copy()
        one_step_back = x.copy()
        one_step_back[2000] = one_step_back[1998]
        infinite_end = x.copy()
        infinite_end[-1] = np.inf
        for name, (lx, ly, buckets) in {'few samples': (x, y, 501), 'gap': (x, gap, 100),
                                        'infinite': (x, endless, 100), 'x back': (backwards, y, 100),
                                        'x one step back': (one_step_back, y, 100),
                                        'x ends at infinity': (infinite_end, y, 100),
                                        'y shorter': (x, y[:-1], 100)}.items():
            with self.subTest(name):
                ox, oy = bucket_reduce_lines(lx, ly, buckets)
                self.assertIs(ox, lx)
                self.assertIs(oy, ly)


if __name__ == '__main__':
    unittest.main()
