"""Unit tests for the pyqtgraph NanosecondDateFormatter edge cases.

The pyqtgraph variant is a pg.AxisItem subclass (needs a QApplication) but
its date-fmt / lcp / round-hour logic mirrors the matplotlib variant. Both
have been sources of bugs historically (ITER nanosecond precision, rounding
to hour in the oscilloscope mode, common-prefix truncation), so the
invariants are pinned here too.
"""

import unittest

from iplotlib.impl.pyqtgraph.dateFormatter import NanosecondDateFormatter
from iplotlib.qt.testing import ensure_qapp


TS_1 = 1705322096789000000       # 2024-01-15 12:34:56.789 UTC
TS_1_NS = 1705322096789123456    # 2024-01-15 12:34:56.789123456 UTC


def _formatter() -> NanosecondDateFormatter:
    return NanosecondDateFormatter(orientation='bottom')


class FormatterSegmentsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = ensure_qapp()

    def test_year_month_day(self):
        fmt = _formatter()
        self.assertEqual(fmt.date_fmt(TS_1, fmt.YEAR, fmt.YEAR), '2024')
        self.assertEqual(fmt.date_fmt(TS_1, fmt.MONTH, fmt.MONTH), '01')
        self.assertEqual(fmt.date_fmt(TS_1, fmt.DAY, fmt.DAY), '15')

    def test_time_segments(self):
        fmt = _formatter()
        self.assertEqual(fmt.date_fmt(TS_1, fmt.HOUR, fmt.SECOND), '12:34:56')

    def test_nanosecond_precision(self):
        fmt = _formatter()
        self.assertEqual(fmt.date_fmt(TS_1_NS, fmt.NANOSECOND,
                                      fmt.NANOSECOND), '456')

    def test_year_to_hour(self):
        fmt = _formatter()
        self.assertEqual(fmt.date_fmt(TS_1, fmt.YEAR, fmt.HOUR),
                         '2024-01-15T12')


class FormatterLcpTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = ensure_qapp()

    def test_lcp_same_year_different_month_returns_year(self):
        fmt = _formatter()
        ts_a = 1705322096789000000  # 2024-01-15
        ts_b = 1718477130000000000  # 2024-06-15
        self.assertEqual(fmt.lcp(ts_a, ts_b), fmt.YEAR)

    def test_lcp_different_years_returns_negative_one(self):
        fmt = _formatter()
        ts_a = 1705322096789000000  # 2024
        ts_b = 1736858096789000000  # 2025
        self.assertEqual(fmt.lcp(ts_a, ts_b), -1)

    def test_lcp_ten_minutes_apart_returns_hour(self):
        fmt = _formatter()
        ts_a = 1705322096789000000  # 2024-01-15 12:34:56
        ts_b = 1705322696789000000  # 2024-01-15 12:44:56
        self.assertEqual(fmt.lcp(ts_a, ts_b), fmt.HOUR)


class FormatterRoundHourTest(unittest.TestCase):
    def test_round_hour_minute_over_30_rounds_up(self):
        self.assertEqual(
            NanosecondDateFormatter.round_hour('2024-01-15T12:40:00'),
            '2024-01-15T13:00:00')

    def test_round_hour_minute_under_30_rounds_down(self):
        self.assertEqual(
            NanosecondDateFormatter.round_hour('2024-01-15T12:20:00'),
            '2024-01-15T12:00:00')

    def test_round_hour_exactly_30_rounds_up(self):
        self.assertEqual(
            NanosecondDateFormatter.round_hour('2024-01-15T12:30:00'),
            '2024-01-15T13:00:00')


class FormatterSpacingLabelTest(unittest.TestCase):
    """Oscilloscope-style per-division labels for the pyqt backend."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.app = ensure_qapp()

    def test_spacing_label_in_nanoseconds(self):
        fmt = _formatter()
        fmt._spacing = 50  # ns
        self.assertIn('ns/div', fmt.get_spacing_label())

    def test_spacing_label_in_microseconds(self):
        fmt = _formatter()
        fmt._spacing = 2_000  # 2 µs
        self.assertIn('μs/div', fmt.get_spacing_label())

    def test_spacing_label_in_seconds(self):
        fmt = _formatter()
        fmt._spacing = 2e9  # 2 s
        self.assertIn('s/div', fmt.get_spacing_label())

    def test_spacing_label_in_minutes(self):
        fmt = _formatter()
        fmt._spacing = 180e9  # 3 min
        self.assertIn('min/div', fmt.get_spacing_label())

    def test_spacing_label_zero_returns_empty(self):
        fmt = _formatter()
        fmt._spacing = 0
        self.assertEqual(fmt.get_spacing_label(), '')


class FormatterTickValuesTest(unittest.TestCase):
    """tickValues reuses the previous ticks when only the range shifts (panning).
    If a shift leaves a single surviving tick, the step must not be read from a
    second, non-existent tick — otherwise pan/undo raises IndexError mid-paint."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.app = ensure_qapp()

    def test_pan_leaving_one_surviving_tick_does_not_raise(self):
        fmt = _formatter()
        fmt.n_ticks = 7
        fmt.tickValues(0.0, 100.0, 500.0)          # seed ticks across [0, 100]
        fmt.tickValues(90.0, 190.0, 500.0)         # same span shifted: one survivor

    def test_pan_still_produces_ticks_after_one_survivor(self):
        fmt = _formatter()
        fmt.n_ticks = 7
        fmt.tickValues(0.0, 100.0, 500.0)
        levels = fmt.tickValues(90.0, 190.0, 500.0)
        ticks = [v for _, group in levels for v in group]
        self.assertGreater(len(ticks), 1)


if __name__ == '__main__':
    unittest.main()
