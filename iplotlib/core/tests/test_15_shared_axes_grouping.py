"""Unit coverage for BackendParserBase shared-axes discriminators."""

import types
import unittest

import numpy as np

from iplotlib.core.impl_base import BackendParserBase
from iplotlib.core.plot import PlotXY
from iplotlib.core.signal import SignalXY
from iplotlib.interface.iplotSignalAdapter import ParserHelper
from iplotProcessing.common.interpolation import InterpolationKind


def _signal_with_ts(label, ts_start, ts_end):
    s = SignalXY(label=label)
    s.ts_start = ts_start
    s.ts_end = ts_end
    return s


class PlotSignalTsRangeTest(unittest.TestCase):
    def test_returns_ts_of_first_valid_signal(self):
        plot = PlotXY()
        plot.add_signal(_signal_with_ts("a", 1000, 2000))
        plot.add_signal(_signal_with_ts("b", 5000, 6000))
        self.assertEqual(
            BackendParserBase._plot_signal_ts_range(plot), (1000, 2000)
        )

    def test_returns_none_when_plot_is_none(self):
        self.assertIsNone(BackendParserBase._plot_signal_ts_range(None))

    def test_returns_none_when_plot_has_no_signals(self):
        plot = PlotXY()
        self.assertIsNone(BackendParserBase._plot_signal_ts_range(plot))

    def test_returns_none_when_ts_is_empty_string(self):
        # '' is the pre-resolution sentinel; must be skipped rather than returned.
        plot = PlotXY()
        s = SignalXY(label="empty")
        s.ts_start = ''
        s.ts_end = ''
        plot.add_signal(s)
        self.assertIsNone(BackendParserBase._plot_signal_ts_range(plot))

    def test_skips_invalid_signal_and_returns_next_valid(self):
        plot = PlotXY()
        bad = SignalXY(label="bad")
        bad.ts_start = ''
        bad.ts_end = ''
        plot.add_signal(bad, stack=1)
        plot.add_signal(_signal_with_ts("good", 7000, 8000), stack=2)
        self.assertEqual(
            BackendParserBase._plot_signal_ts_range(plot), (7000, 8000)
        )

    def test_accepts_float_ts_in_relative_time_mode(self):
        plot = PlotXY()
        plot.add_signal(_signal_with_ts("rel", 0.0, 60.0))
        self.assertEqual(
            BackendParserBase._plot_signal_ts_range(plot), (0.0, 60.0)
        )


class PlotXIsTimeTest(unittest.TestCase):
    def test_default_x_expr_is_time(self):
        plot = PlotXY()
        plot.add_signal(SignalXY(label="t"))  # x_expr defaults to '${self}.time'
        self.assertTrue(BackendParserBase._plot_x_is_time(plot))

    def test_data_derived_x_expr_is_not_time(self):
        plot = PlotXY()
        plot.add_signal(SignalXY(label="xy", x_expr="${T}.data"))
        self.assertFalse(BackendParserBase._plot_x_is_time(plot))

    def test_any_non_time_signal_makes_plot_non_time(self):
        plot = PlotXY()
        plot.add_signal(SignalXY(label="t"), stack=1)
        plot.add_signal(SignalXY(label="xy", x_expr="${C}.data"), stack=2)
        self.assertFalse(BackendParserBase._plot_x_is_time(plot))

    def test_none_plot_defaults_to_time(self):
        self.assertTrue(BackendParserBase._plot_x_is_time(None))

    def test_plot_without_signals_defaults_to_time(self):
        self.assertTrue(BackendParserBase._plot_x_is_time(PlotXY()))


class PlotXExprYieldsTimeTest(unittest.TestCase):
    @staticmethod
    def _plot_with_x_expr(*x_exprs):
        plot = PlotXY()
        for i, x_expr in enumerate(x_exprs):
            plot.add_signal(SignalXY(label=f"s{i}", x_expr=x_expr), stack=i + 1)
        return plot

    def test_time_buffer_expression_is_time(self):
        plot = self._plot_with_x_expr("${T}.time")
        self.assertTrue(BackendParserBase._plot_x_expr_yields_time(plot))

    def test_data_buffer_expression_is_not_time(self):
        plot = self._plot_with_x_expr("${T}.data")
        self.assertFalse(BackendParserBase._plot_x_expr_yields_time(plot))

    def test_any_data_expression_makes_plot_not_time(self):
        plot = self._plot_with_x_expr("${T}.time", "${T_ssf}.data")
        self.assertFalse(BackendParserBase._plot_x_expr_yields_time(plot))

    def test_time_accessor_inside_larger_expression_is_time(self):
        plot = self._plot_with_x_expr("${T}.time - 1000000")
        self.assertTrue(BackendParserBase._plot_x_expr_yields_time(plot))

    def test_lookalike_accessor_is_not_time(self):
        # '.timestamp' must not match the '${...}.time' accessor.
        plot = self._plot_with_x_expr("${T}.timestamp")
        self.assertFalse(BackendParserBase._plot_x_expr_yields_time(plot))

    def test_none_plot_or_empty_plot_is_not_time(self):
        self.assertFalse(BackendParserBase._plot_x_expr_yields_time(None))
        self.assertFalse(BackendParserBase._plot_x_expr_yields_time(PlotXY()))


class PlotFirstXInRangeTest(unittest.TestCase):
    @staticmethod
    def _plot_with_x_data(x_data):
        plot = PlotXY()
        s = SignalXY(label="ech", x_expr="${T}.time")
        x = np.asarray(x_data, dtype=float)
        s.set_data([x, np.zeros_like(x)])
        plot.add_signal(s)
        return plot

    def test_first_sample_inside_interval(self):
        plot = self._plot_with_x_data([150.0, 250.0, 350.0])
        self.assertTrue(BackendParserBase._plot_first_x_in_range(plot, 100, 400))

    def test_first_sample_outside_interval(self):
        # Only the first sample decides, even if later ones fall inside.
        plot = self._plot_with_x_data([5.0, 150.0])
        self.assertFalse(BackendParserBase._plot_first_x_in_range(plot, 100, 400))

    def test_leading_nan_samples_are_skipped(self):
        plot = self._plot_with_x_data([np.nan, 200.0])
        self.assertTrue(BackendParserBase._plot_first_x_in_range(plot, 100, 400))

    def test_plot_without_x_data_is_out(self):
        plot = PlotXY()
        plot.add_signal(SignalXY(label="empty", x_expr="${T}.data"))
        self.assertFalse(BackendParserBase._plot_first_x_in_range(plot, 100, 400))

    def test_none_plot_or_bounds_are_out(self):
        plot = self._plot_with_x_data([150.0])
        self.assertFalse(BackendParserBase._plot_first_x_in_range(None, 100, 400))
        self.assertFalse(BackendParserBase._plot_first_x_in_range(plot, None, 400))
        self.assertFalse(BackendParserBase._plot_first_x_in_range(plot, 100, None))


class _SharedTimeBaseHost:
    """Minimal stand-in exposing what ``_plot_shares_time_base`` reads from the parser."""

    def __init__(self, max_diff=1.0):
        self.canvas = object()
        self._pm = types.SimpleNamespace(get_value=lambda obj, key: max_diff)

    _plot_signal_ts_range = staticmethod(BackendParserBase._plot_signal_ts_range)
    _plot_shares_time_base = BackendParserBase._plot_shares_time_base


class PlotSharesTimeBaseTest(unittest.TestCase):
    @staticmethod
    def _plot_with_ts(ts_start, ts_end):
        plot = PlotXY()
        s = SignalXY(label="xy", x_expr="${T}.data")
        s.ts_start = ts_start
        s.ts_end = ts_end
        plot.add_signal(s)
        return plot

    def test_identical_ts_shares_time_base(self):
        host = _SharedTimeBaseHost()
        plot = self._plot_with_ts(1000, 2000)
        self.assertTrue(host._plot_shares_time_base(plot, (1000, 2000)))

    def test_ts_within_max_diff_shares_time_base(self):
        host = _SharedTimeBaseHost(max_diff=5.0)
        plot = self._plot_with_ts(1002.0, 2003.0)
        self.assertTrue(host._plot_shares_time_base(plot, (1000.0, 2000.0)))

    def test_disjoint_ts_does_not_share_time_base(self):
        host = _SharedTimeBaseHost(max_diff=5.0)
        plot = self._plot_with_ts(9000.0, 9500.0)
        self.assertFalse(host._plot_shares_time_base(plot, (1000.0, 2000.0)))

    def test_date_ts_uses_nanosecond_tolerance(self):
        host = _SharedTimeBaseHost(max_diff=5.0)  # seconds
        base = (1_754_463_600_000_000_000, 1_754_503_200_000_000_000)
        plot = self._plot_with_ts(base[0] + 2_000_000_000, base[1] - 2_000_000_000)  # +/-2s
        self.assertTrue(host._plot_shares_time_base(plot, base))
        far = self._plot_with_ts(base[0] + 60_000_000_000, base[1])  # +60s
        self.assertFalse(host._plot_shares_time_base(far, base))

    def test_missing_ts_info_defaults_to_shared(self):
        # Shared time ticked is the user's assertion of a common time base
        # (iplot-viz/mint#120): without request info, take their word for it.
        host = _SharedTimeBaseHost()
        plot = PlotXY()
        plot.add_signal(SignalXY(label="xy", x_expr="${T}.data"))
        self.assertTrue(host._plot_shares_time_base(plot, (1000, 2000)))
        with_ts = self._plot_with_ts(1000, 2000)
        self.assertTrue(host._plot_shares_time_base(with_ts, None))


class SignalLutKeyTest(unittest.TestCase):
    def test_uid_is_used_when_present(self):
        s = SignalXY(label="a")
        s.uid = "signal-42"
        self.assertEqual(BackendParserBase.signal_lut_key(s), "signal-42")

    def test_uid_less_signals_do_not_collide(self):
        # Signals without a uid used to collide on the shared None key, making
        # every uid-less signal resolve to the last processed plot.
        s1, s2 = SignalXY(label="a"), SignalXY(label="b")
        k1, k2 = BackendParserBase.signal_lut_key(s1), BackendParserBase.signal_lut_key(s2)
        self.assertNotEqual(k1, k2)
        self.assertEqual(k1, BackendParserBase.signal_lut_key(s1))  # stable


class SetTimeWindowRefreshTest(unittest.TestCase):
    """A shared-time zoom hands a plot with a data-valued X a trusted *time*
    window; the signal must then allow a refetch/reprocess even when its
    processed X data is not monotonically increasing (mint#120)."""

    @staticmethod
    def _non_monotonic_xy_signal():
        s = SignalXY(label="xy", x_expr="${T}.data")
        x = np.array([3.0, 1.0, 2.0])  # non-bijective X
        s.set_data([x, np.zeros_like(x)])
        return s

    def test_time_window_forces_refresh_and_is_one_shot(self):
        s = self._non_monotonic_xy_signal()
        self.assertTrue(s._needs_refresh())  # establishes the hash baseline

        # A plain ts change (zoom made on the XY plot itself) keeps the
        # conservative behaviour: non-monotonic X cannot map back to times.
        s.set_xranges((100, 200))
        self.assertFalse(s._needs_refresh())

        # A trusted time window propagated from a time plot does refresh.
        s.set_time_window(300, 400)
        self.assertEqual((s.ts_start, s.ts_end), (300, 400))
        self.assertTrue(s._needs_refresh())

        # The flag is one-shot: the next plain ts change is conservative again.
        s.set_xranges((500, 600))
        self.assertFalse(s._needs_refresh())

    def test_monotonic_x_still_refreshes_without_the_flag(self):
        s = SignalXY(label="xy", x_expr="${T}.data")
        x = np.array([1.0, 2.0, 3.0])
        s.set_data([x, np.zeros_like(x)])
        self.assertTrue(s._needs_refresh())
        s.set_xranges((100, 200))
        self.assertTrue(s._needs_refresh())


class ExpressionSignalTimeWindowTest(unittest.TestCase):
    """MINT X-versus-Y rows are expression-only signals (empty name,
    x_expr='${A}.data', y_expr='${B}.data') whose buffers derive from alias
    dependencies. A shared-time zoom must re-evaluate those expressions once
    the dependencies were refreshed over the window (mint#120, Test34)."""

    def _make_dep(self, alias, x, y):
        dep = SignalXY(label=alias.upper(), alias=alias)
        dep.data_access_enabled = False
        dep.set_data([np.asarray(x, dtype=float), np.asarray(y, dtype=float)])
        return dep

    def test_reprocesses_expressions_after_dependencies_change(self):
        a = self._make_dep("m120a", [0, 1, 2], [10.0, 20.0, 30.0])
        b = self._make_dep("m120b", [0, 1, 2], [1.0, 2.0, 3.0])

        tot = SignalXY(label="Tot", name="",
                       x_expr="${m120a}.data", y_expr="${m120b}.data")
        tot.get_data()  # initial processing
        np.testing.assert_array_equal(tot.x_data, [10.0, 20.0, 30.0])
        np.testing.assert_array_equal(tot.y_data, [1.0, 2.0, 3.0])

        # Emulate the dependencies being refetched over a narrower time window
        # (as the shared-time zoom does for the plots that display them).
        a.set_data([np.array([1.0]), np.array([20.0])])
        b.set_data([np.array([1.0]), np.array([2.0])])

        # Without the trusted window, the expression signal stays as it is.
        tot.get_data()
        np.testing.assert_array_equal(tot.x_data, [10.0, 20.0, 30.0])

        # With it, processing is re-run and the X column re-derived.
        tot.refresh_over_time_window(100, 200)
        np.testing.assert_array_equal(tot.x_data, [20.0])
        np.testing.assert_array_equal(tot.y_data, [2.0])
        self.assertEqual((tot.ts_start, tot.ts_end), (100, 200))
        # One-shot: a plain get_data afterwards does not re-run processing.
        self.assertFalse(tot._ts_is_time_window)

    def test_dependency_walk_tolerates_missing_and_cyclic_aliases(self):
        a = self._make_dep("m120c", [0, 1], [5.0, 6.0])
        tot = SignalXY(label="Tot", name="",
                       x_expr="${m120c}.data + ${m120missing}.data",
                       y_expr="${m120c}.data")
        # Missing alias must not raise during the dependency walk.
        tot.refresh_over_time_window(0, 10)
        self.assertEqual((tot.ts_start, tot.ts_end), (0, 10))

    def test_result_cropped_to_window_when_dependencies_hold_superset(self):
        """Once a zoom drops below the downsampling threshold, dependency buffers
        hold raw data covering more than the requested window and are not
        refetched on deeper zooms. The expression result must still be cropped to
        the requested ts window, otherwise the X-versus-Y axis stops following
        the zoom (mint#120, 'x axis not refreshed when zooming more than once')."""
        t = np.arange(1000, 2001, 10, dtype=np.int64)  # superset time base
        a = self._make_dep("m120e", t, np.linspace(100.0, 200.0, t.size))
        b = self._make_dep("m120f", t, np.linspace(0.0, 1.0, t.size))
        tot = SignalXY(label="Tot", name="",
                       x_expr="${m120e}.data", y_expr="${m120f}.data")
        tot.refresh_over_time_window(1000, 2000)
        self.assertAlmostEqual(float(np.asarray(tot.x_data).min()), 100.0)
        self.assertAlmostEqual(float(np.asarray(tot.x_data).max()), 200.0)

        # Deeper window; dependency buffers unchanged (raw superset, no refetch).
        tot.refresh_over_time_window(1400, 1600)
        x = np.asarray(tot.x_data, dtype=float)
        y = np.asarray(tot.y_data, dtype=float)
        self.assertEqual(x.size, y.size)
        self.assertGreaterEqual(x.min(), 139.9)
        self.assertLessEqual(x.max(), 160.1)

    def test_realignment_interpolation_auto_and_explicit(self):
        """The default 'auto' picks linear only when every dependency is raw
        (not downsampled) and sampled above CONTINUOUS_RATE_THRESHOLD_HZ.
        Downsampled buffers and event-driven (slow) dependencies keep
        sample-and-hold — no new sample means the value is constant. An
        explicit InterpolationKind on the signal always wins (mint#120)."""
        resolve = ParserHelper.resolve_alignment_kind

        def dep(rate_hz, seconds=2.0, downsampled=False):
            n = max(int(rate_hz * seconds), 2)
            t = (1_700_000_000_000_000_000
                 + np.linspace(0, seconds * 1e9, n)).astype(np.int64)
            return types.SimpleNamespace(isDownsampled=downsampled,
                                         data_store=[t])

        auto = SignalXY(label="auto_pref", name="")
        # Every dependency raw and fast -> continuous -> linear.
        self.assertEqual(resolve(auto, [dep(2500), dep(10000)]),
                         InterpolationKind.LINEAR)
        # One event-driven (slow) dependency keeps hold for the alignment.
        self.assertEqual(resolve(auto, [dep(2500), dep(0.5)]),
                         InterpolationKind.PREVIOUS)
        # A downsampled dependency keeps hold: its grid is the downsampler's,
        # not the signal's, so no assumption is made from it.
        self.assertEqual(resolve(auto, [dep(2500), dep(10000, downsampled=True)]),
                         InterpolationKind.PREVIOUS)

        forced = SignalXY(label="forced_pref", name="")
        forced.interpolation = InterpolationKind.LINEAR
        self.assertEqual(resolve(forced, [dep(0.5, downsampled=True)]),
                         InterpolationKind.LINEAR)
        forced.interpolation = InterpolationKind.PREVIOUS
        self.assertEqual(resolve(forced, [dep(10000)]),
                         InterpolationKind.PREVIOUS)

    def test_auto_linear_shape_through_the_pipeline(self):
        """Raw, fast dependencies (e.g. a 2.5 kHz relative time X against a
        1 MHz Y): the sparse X must advance smoothly on the union grid instead
        of holding plateaus that render as a staircase of vertical strokes
        (mint#120)."""
        base = 1_700_000_000_000_000_000
        t_sparse = (base + np.linspace(0, 1e9, 250)).astype(np.int64)   # 250 Hz
        t_dense = (base + np.linspace(0, 1e9, 1001)).astype(np.int64)   # 1 kHz
        self._make_dep("m120g", t_sparse, np.linspace(0.0, 500.0, 250))
        self._make_dep("m120h", t_dense, np.sin(np.linspace(0, 20, 1001)))
        tot = SignalXY(label="Tot", name="",
                       x_expr="${m120g}.data", y_expr="${m120h}.data")
        tot.refresh_over_time_window(base, base + 1_000_000_000)
        x = np.asarray(tot.x_data, dtype=float)
        dx = np.diff(x[np.isfinite(x)])
        self.assertGreater(float(np.count_nonzero(dx > 0)) / dx.size, 0.99)


class _InvertHost:
    """Minimal host exposing what ``_invert_xy_zoom_to_time`` needs."""

    def __init__(self, signals):
        import weakref
        self._signals = list(signals)  # keep the test signals alive
        item = types.SimpleNamespace(signals=[weakref.ref(s) for s in self._signals])
        self._impl_plot_cache_table = types.SimpleNamespace(
            get_cache_item=lambda impl: item)

    _invert_xy_zoom_to_time = BackendParserBase._invert_xy_zoom_to_time


class InvertXyZoomToTimeTest(unittest.TestCase):
    """A zoom on an X-versus-Y plot maps back to a time window only when the X
    column is invertible: evaluated over a known time base and strictly
    monotonically increasing (mint#120 reverse direction)."""

    @staticmethod
    def _signal(x, time_base):
        s = SignalXY(label="xy", name="", x_expr="${T}.data")
        s.data_access_enabled = False
        s.set_data([np.asarray(x, dtype=float), np.zeros(len(x))])
        s._expr_time_base = None if time_base is None else np.asarray(time_base)
        return s

    def test_strictly_increasing_x_maps_to_time_window(self):
        t = np.linspace(1_000_000, 2_000_000, 11)
        x = np.linspace(100.0, 200.0, 11)  # x = 100 + (t-1e6)/1e4
        sig = self._signal(x, t)
        host = _InvertHost([sig])
        window = host._invert_xy_zoom_to_time(None, 120.0, 150.0)
        self.assertIsNotNone(window)
        self.assertAlmostEqual(window[0], 1_200_000, delta=1)
        self.assertAlmostEqual(window[1], 1_500_000, delta=1)
        # Beyond the data: linear edge extrapolation (zoom out / undo).
        window = host._invert_xy_zoom_to_time(None, 50.0, 250.0)
        self.assertAlmostEqual(window[0], 500_000, delta=1)
        self.assertAlmostEqual(window[1], 2_500_000, delta=1)

    def test_non_monotonic_x_is_not_invertible(self):
        t = np.linspace(0, 100, 50)
        x = np.sin(np.linspace(0, 10, 50))
        host = _InvertHost([self._signal(x, t)])
        self.assertIsNone(host._invert_xy_zoom_to_time(None, -0.5, 0.5))

    def test_sample_and_hold_plateaus_are_invertible(self):
        """Sample-and-hold realignment of a strictly increasing dependency
        repeats X values on the fine union grid; the mapping must tolerate
        those plateaus (mint#120: '${A}.data incremented monotonically was
        reported not invertible' after a kind=previous realign)."""
        t = np.linspace(1_000_000, 2_000_000, 101)  # fine union grid
        x = np.repeat(np.linspace(100.0, 200.0, 11), 10)[:101]  # 10-sample holds
        x[-1] = 200.0
        host = _InvertHost([self._signal(x, t)])
        window = host._invert_xy_zoom_to_time(None, 120.0, 150.0)
        self.assertIsNotNone(window)
        # First point of each hold run: within one hold interval of the ideal.
        self.assertAlmostEqual(window[0], 1_200_000, delta=110_000)
        self.assertAlmostEqual(window[1], 1_500_000, delta=110_000)
        self.assertLess(window[0], window[1])

    def test_data_independent_x_is_not_invertible(self):
        # e.g. x_expr='np.ones(10)': no dependency, hence no time base retained.
        host = _InvertHost([self._signal(np.ones(10), None)])
        self.assertIsNone(host._invert_xy_zoom_to_time(None, 0.5, 1.5))


class _TransformDataHost:
    """Minimal host exposing what ``transform_data`` needs from the parser."""

    def __init__(self, offsets):
        item = types.SimpleNamespace(offsets=offsets)
        self._impl_plot_cache_table = types.SimpleNamespace(
            get_cache_item=lambda impl: item)

    transform_data = BackendParserBase.transform_data


class TransformDataNaNTest(unittest.TestCase):
    def test_nan_survives_offset_transform(self):
        # Realigned expression signals can carry NaNs (left-edge extrapolation).
        # Casting NaN to int64 yields INT64_MIN, which draws as a spurious line
        # across the plot; NaNs must come out as NaNs (mint#120).
        offset = 1_781_184_632_976_126
        host = _TransformDataHost(offsets=[offset, 0])
        x = np.array([np.nan, 1_781_184_469_510_126.0, 1_781_184_470_468_326.0, np.nan])
        y = np.array([1.0, 2.0, 3.0, 4.0])
        tx, ty = host.transform_data(None, [x, y])
        self.assertTrue(np.isnan(tx[0]) and np.isnan(tx[3]))
        self.assertAlmostEqual(float(tx[1]), 1_781_184_469_510_126 - offset)
        self.assertAlmostEqual(float(tx[2]), 1_781_184_470_468_326 - offset)
        self.assertGreater(float(np.nanmin(np.asarray(tx))), -1e12)  # no INT64_MIN garbage
        np.testing.assert_array_equal(ty, y)

    def test_all_finite_data_keeps_integer_path(self):
        host = _TransformDataHost(offsets=[1000, None])
        x = np.array([1500, 2500], dtype=np.int64)
        tx, ty = host.transform_data(None, [x, np.array([1.0, 2.0])])
        np.testing.assert_array_equal(np.asarray(tx), [500, 1500])


if __name__ == '__main__':
    unittest.main()
