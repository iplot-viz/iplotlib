"""Unit tests for the matplotlib NanosecondDateFormatter edge cases.

The formatter is tricky: it takes nanosecond-precision timestamps from ITER
(int64 offsets on top of a base) and produces the axis labels. Rounding,
offset propagation, date-segment truncation and the round-to-hour mode
have each been the source of bugs in the past, so we pin them here.
"""

import unittest

from iplotlib.impl.matplotlib.dateFormatter import NanosecondDateFormatter


# 2024-01-15 12:34:56.789 UTC in nanoseconds since epoch.
TS_1 = 1705322096789000000
# 2024-01-15 12:34:56.789123456 UTC in nanoseconds since epoch.
TS_1_NS = 1705322096789123456
# 2024-06-15 18:45:30.000 UTC.
TS_2 = 1718477130000000000


class FormatterSegmentsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.fmt = NanosecondDateFormatter(ax_idx=0, label_segments=4,
                                           postfix_end=False, postfix_start=False)

    def test_year_segment_is_4_digits(self):
        out = self.fmt.date_fmt(TS_1, start=self.fmt.YEAR, end=self.fmt.YEAR)
        self.assertEqual(out, '2024')

    def test_month_segment_is_2_digits_zero_padded(self):
        out = self.fmt.date_fmt(TS_1, start=self.fmt.MONTH, end=self.fmt.MONTH)
        self.assertEqual(out, '01')

    def test_hour_minute_second_are_zero_padded(self):
        out = self.fmt.date_fmt(TS_1, start=self.fmt.HOUR, end=self.fmt.SECOND)
        self.assertEqual(out, '12:34:56')

    def test_nanosecond_precision_is_preserved(self):
        """A timestamp with ns detail must round-trip through date_fmt."""
        out = self.fmt.date_fmt(TS_1_NS, start=self.fmt.NANOSECOND,
                                end=self.fmt.NANOSECOND)
        # 1705322096789123456 has 456 ns after the microsecond boundary.
        self.assertEqual(out, '456')

    def test_segment_ranges_produce_expected_substring(self):
        """Year through hour gives '2024-01-15T12'."""
        out = self.fmt.date_fmt(TS_1, start=self.fmt.YEAR, end=self.fmt.HOUR)
        self.assertEqual(out, '2024-01-15T12')


class FormatterLcpTest(unittest.TestCase):
    """Common-prefix truncation between two timestamps."""

    def setUp(self) -> None:
        self.fmt = NanosecondDateFormatter(ax_idx=0)

    def test_lcp_returns_year_when_only_year_matches(self):
        """Same year, different month: year is the deepest common segment."""
        ts_a = 1705322096789000000  # 2024-01-15
        ts_b = 1718477130000000000  # 2024-06-15
        self.assertEqual(self.fmt.lcp(ts_a, ts_b), self.fmt.YEAR)

    def test_lcp_returns_negative_one_when_years_differ(self):
        """Different years share no segment; lcp returns YEAR - 1 (= -1)."""
        ts_a = 1705322096789000000  # 2024
        ts_b = 1736858096789000000  # 2025
        self.assertEqual(self.fmt.lcp(ts_a, ts_b), -1)

    def test_lcp_returns_hour_when_everything_up_to_hour_matches(self):
        """Two timestamps 10 minutes apart share Y/M/D/H."""
        ts_a = 1705322096789000000  # 2024-01-15 12:34:56
        ts_b = 1705322696789000000  # 2024-01-15 12:44:56
        self.assertEqual(self.fmt.lcp(ts_a, ts_b), self.fmt.HOUR)


class FormatterOffsetTest(unittest.TestCase):
    """The offset LUT drives per-axis base timestamp handling."""

    def test_offset_ns_returns_zero_when_no_lut(self):
        fmt = NanosecondDateFormatter(ax_idx=0, offset_lut=None)
        self.assertEqual(fmt.offset_ns, 0)

    def test_offset_ns_returns_value_from_lut(self):
        fmt = NanosecondDateFormatter(ax_idx=1, offset_lut=[100, 200, 300])
        self.assertEqual(fmt.offset_ns, 200)

    def test_offset_ns_returns_zero_when_lut_entry_is_none(self):
        fmt = NanosecondDateFormatter(ax_idx=0, offset_lut=[None, 200])
        self.assertEqual(fmt.offset_ns, 0)

    def test_offset_ns_returns_zero_when_ax_idx_out_of_range(self):
        fmt = NanosecondDateFormatter(ax_idx=5, offset_lut=[100, 200])
        self.assertEqual(fmt.offset_ns, 0)


class FormatterRoundHourTest(unittest.TestCase):
    """round_hour collapses the minute (and second) part to 00 when enabled."""

    def test_round_hour_minute_over_30_rounds_up(self):
        rounded = NanosecondDateFormatter.round_hour('2024-01-15T12:40:00')
        self.assertEqual(rounded, '2024-01-15T13:00:00')

    def test_round_hour_minute_under_30_rounds_down(self):
        rounded = NanosecondDateFormatter.round_hour('2024-01-15T12:20:00')
        self.assertEqual(rounded, '2024-01-15T12:00:00')

    def test_round_hour_exactly_30_rounds_up(self):
        rounded = NanosecondDateFormatter.round_hour('2024-01-15T12:30:00')
        self.assertEqual(rounded, '2024-01-15T13:00:00')


if __name__ == '__main__':
    unittest.main()
