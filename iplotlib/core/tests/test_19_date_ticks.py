# Description: Tests for the shared civil-time tick ladder: the interval
#              choice tracks the requested tick count and the generated
#              positions stay anchored while the view pans.

import datetime
import unittest

from iplotlib.core.date_ticks import (
    generate_ticks,
    linear_ticks,
    pick_interval,
    relative_ticks,
    segments_for_interval,
)

_SEC = 1_000_000_000
_MIN = 60 * _SEC
_HOUR = 60 * _MIN
_DAY = 24 * _HOUR
_WEEK = 7 * _DAY

# 2026-05-06T09:00:00Z, a Wednesday: week boundaries fall inside the window
# rather than on its edges, the layout where the count used to collapse.
T0 = 1_778_058_000_000_000_000
_UTC = datetime.timezone.utc


def _count(lo, hi, target, min_step=0):
    step, kind = pick_interval(lo, hi, target, min_step)
    return len(generate_ticks(lo, hi, step, kind))


class PickIntervalTests(unittest.TestCase):

    def test_sixteen_days_stays_near_a_small_target(self):
        # A 16-day window holds only two Mondays, so a week step leaves two
        # ticks no matter what the user asks for; the choice must fall back
        # to a finer rung instead.
        n = _count(T0, T0 + 16 * _DAY, 5)
        self.assertGreaterEqual(n, 5)
        self.assertLessEqual(n, 8)

    def test_configured_count_is_a_minimum(self):
        # The setting means "at least this many ticks": no span/target
        # combination may come back under the request.
        for span in (45 * _SEC, 7 * _MIN, 3 * _HOUR, _DAY, 5 * _DAY,
                     16 * _DAY, 42 * _DAY, 61 * _DAY, 200 * _DAY,
                     730 * _DAY):
            for target in (2, 5, 7, 10):
                self.assertGreaterEqual(_count(T0, T0 + span, target),
                                        target, (span, target))

    def test_count_tracks_a_growing_target(self):
        counts = [_count(T0, T0 + 16 * _DAY, t) for t in range(2, 16)]
        self.assertEqual(counts, sorted(counts))
        self.assertGreater(counts[-1], counts[0])

    def test_windows_between_calendar_rungs_keep_a_usable_count(self):
        # Spans falling in the day/week/month gaps of the ladder used to
        # come out with one or two ticks.
        for span in (6 * _HOUR, _DAY, 3 * _DAY, 42 * _DAY, 61 * _DAY,
                     183 * _DAY, 548 * _DAY):
            self.assertGreaterEqual(_count(T0, T0 + span, 7), 5, span)

    def test_round_windows_pick_the_largest_sufficient_step(self):
        # 1 h / 7 -> 10 min gives exactly 7; 5 min / 7 -> 1 min gives only 6,
        # so the guarantee drops one rung to 30 s.
        for span, step in ((_HOUR, 10 * _MIN), (5 * _MIN, 30 * _SEC),
                           (30 * _SEC, 5 * _SEC)):
            self.assertEqual(pick_interval(T0, T0 + span, 7),
                             (step, "fixed"))

    def test_min_step_floors_the_choice(self):
        step, kind = pick_interval(T0, T0 + 50_000_000, 20,
                                   min_step_ns=100_000)
        self.assertEqual(kind, "fixed")
        self.assertGreaterEqual(step, 100_000)

    def test_degenerate_range_returns_a_step(self):
        step, kind = pick_interval(T0, T0, 7)
        self.assertGreaterEqual(step, 1)

    def test_huge_target_is_capped(self):
        # Must return promptly instead of descending to nanosecond rungs
        # over a year-wide window.
        step, kind = pick_interval(T0, T0 + 365 * _DAY, 10 ** 9)
        self.assertEqual(len(generate_ticks(T0, T0 + 365 * _DAY, step, kind)),
                         _count(T0, T0 + 365 * _DAY, 10 ** 9))

    def test_reversed_bounds_match_ordered_bounds(self):
        self.assertEqual(pick_interval(T0 + 16 * _DAY, T0, 5),
                         pick_interval(T0, T0 + 16 * _DAY, 5))


class GenerateTicksTests(unittest.TestCase):

    def _weekday(self, ns):
        return datetime.datetime.fromtimestamp(ns / 1e9, tz=_UTC).weekday()

    def test_multi_day_steps_hold_still_while_panning(self):
        for step in (2 * _DAY, 3 * _DAY):
            a = set(generate_ticks(T0, T0 + 16 * _DAY, step, "day"))
            b = set(generate_ticks(T0 + _DAY, T0 + 17 * _DAY, step, "day"))
            overlap_a = {t for t in a if t >= T0 + _DAY}
            self.assertTrue(overlap_a)
            self.assertEqual(overlap_a, {t for t in b if t <= T0 + 16 * _DAY})

    def test_week_steps_fall_on_mondays(self):
        for step in (_WEEK, 2 * _WEEK):
            ticks = generate_ticks(T0, T0 + 90 * _DAY, step, "week")
            self.assertTrue(ticks)
            self.assertTrue(all(self._weekday(t) == 0 for t in ticks))

    def test_fortnight_keeps_the_same_alternate_mondays(self):
        base = generate_ticks(T0, T0 + 90 * _DAY, 2 * _WEEK, "week")
        moved = generate_ticks(T0 + 10 * _DAY, T0 + 100 * _DAY,
                               2 * _WEEK, "week")
        self.assertEqual(set(base) & set(moved),
                         {t for t in base if t >= T0 + 10 * _DAY})

    def test_two_month_step_lands_on_odd_months(self):
        ticks = generate_ticks(T0, T0 + 365 * _DAY, 2, "month")
        months = [datetime.datetime.fromtimestamp(t / 1e9, tz=_UTC).month
                  for t in ticks]
        self.assertTrue(ticks)
        self.assertTrue(all(m % 2 == 1 for m in months))

    def test_fixed_steps_do_not_depend_on_the_start_day(self):
        a = generate_ticks(T0, T0 + 6 * _HOUR, _HOUR, "fixed")
        b = generate_ticks(T0 + 3 * _DAY, T0 + 3 * _DAY + 6 * _HOUR,
                           _HOUR, "fixed")
        self.assertEqual([t - 3 * _DAY for t in b], a)


class RelativeTicksTests(unittest.TestCase):

    def test_configured_count_is_a_minimum(self):
        # 77 min asking for 5 used to land on 30-minute steps (3 ticks);
        # the guarantee picks 15 minutes instead.
        ticks = relative_ticks(0, 77 * _MIN, 5)
        self.assertGreaterEqual(len(ticks), 5)
        self.assertEqual(ticks[1] - ticks[0], 15 * _MIN)

    def test_default_target_also_gets_at_least_the_request(self):
        ticks = relative_ticks(0, 77 * _MIN, 7)
        self.assertGreaterEqual(len(ticks), 7)
        self.assertEqual(ticks[1] - ticks[0], 10 * _MIN)

    def test_anchored_at_zero_and_stable_while_panning(self):
        a = set(relative_ticks(0, 30 * _MIN, 7))
        b = set(relative_ticks(5 * _MIN, 35 * _MIN, 7))
        self.assertEqual({t for t in a if t >= 5 * _MIN},
                         {t for t in b if t <= 30 * _MIN})

    def test_negative_window_keeps_round_positions(self):
        ticks = relative_ticks(-5 * _SEC, 4 * _SEC, 5)
        self.assertGreaterEqual(len(ticks), 5)
        self.assertTrue(all(t % (ticks[1] - ticks[0]) == 0 for t in ticks))

    def test_degenerate_span(self):
        self.assertEqual(relative_ticks(3 * _SEC, 3 * _SEC, 7), [3 * _SEC])


class LinearTicksTests(unittest.TestCase):

    def test_configured_count_is_a_minimum(self):
        for lo, hi in ((0.0, 1.0), (-3.7, 12.9), (24.25, 25.55),
                       (1e-6, 5e-6), (-2e9, 7e9)):
            for target in (3, 5, 7, 10):
                ticks = linear_ticks(lo, hi, target)
                self.assertGreaterEqual(len(ticks), target, (lo, hi, target))
                self.assertTrue(all(lo <= t <= hi + (hi - lo) * 1e-9
                                    for t in ticks))

    def test_positions_are_step_multiples_and_pan_stable(self):
        a = set(linear_ticks(0.0, 10.0, 5))
        b = set(linear_ticks(2.0, 12.0, 5))
        self.assertEqual({t for t in a if t >= 2.0},
                         {t for t in b if t <= 10.0})

    def test_zero_is_exact(self):
        # An accumulated float step rendered zero as -5.6e-17 on the axis.
        for lo, hi in ((-1.05, 1.05), (-0.3, 0.9), (-7.0, 3.0)):
            ticks = linear_ticks(lo, hi, 7)
            self.assertIn(0.0, ticks, (lo, hi))

    def test_degenerate_span(self):
        self.assertEqual(linear_ticks(4.2, 4.2, 7), [4.2])


class SegmentsForIntervalTests(unittest.TestCase):

    def test_calendar_kinds_map_to_their_segment(self):
        self.assertEqual(segments_for_interval(1, "year"), 0)
        self.assertEqual(segments_for_interval(2, "month"), 1)
        self.assertEqual(segments_for_interval(3 * _DAY, "day"), 2)
        self.assertEqual(segments_for_interval(2 * _WEEK, "week"), 2)

    def test_sub_day_steps_map_by_magnitude(self):
        self.assertEqual(segments_for_interval(10 * _MIN, "fixed"), 4)
        self.assertEqual(segments_for_interval(5 * _SEC, "fixed"), 5)
        self.assertEqual(segments_for_interval(200_000, "fixed"), 7)


if __name__ == "__main__":
    unittest.main()
