"""Unit coverage for BackendParserBase._plot_signal_ts_range."""

import unittest

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


if __name__ == '__main__':
    unittest.main()
