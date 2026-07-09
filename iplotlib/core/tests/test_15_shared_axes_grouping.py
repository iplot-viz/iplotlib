"""Unit coverage for BackendParserBase shared-axes discriminators."""

import types
import unittest

import numpy as np

from iplotlib.core.impl_base import BackendParserBase
from iplotlib.core.plot import PlotXY
from iplotlib.core.signal import SignalXY


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


if __name__ == '__main__':
    unittest.main()
