"""Unit tests for SignalXY and SignalContour."""

import unittest
from unittest import mock

import numpy as np
from iplotlib.core.signal import SignalXY, SignalContour


class TestSignalXY(unittest.TestCase):
    def test_set_data_populates_buffers(self):
        s = SignalXY(label="s")
        s.set_data([np.array([0.0, 1.0, 2.0]),
                    np.array([10.0, 11.0, 12.0])])
        self.assertEqual(len(s.data_store[0]), 3)
        self.assertEqual(len(s.data_store[1]), 3)

    def test_label_is_stored(self):
        s = SignalXY(label="my_label")
        self.assertEqual(s.label, "my_label")

    def test_color_is_stored(self):
        s = SignalXY(label="s", color="#ff0000")
        self.assertEqual(s.color, "#ff0000")


class TestSignalContour(unittest.TestCase):
    def test_set_data_populates_buffers(self):
        x = np.array([0.0, 1.0, 2.0])
        y = np.array([0.0, 1.0])
        z = np.outer(y, x)
        s = SignalContour(label="contour")
        s.set_data([x, y, z])
        self.assertEqual(len(s.data_store[0]), 3)
        self.assertEqual(len(s.data_store[1]), 2)


class SetLimitsTest(unittest.TestCase):
    """Custom x_expr with sparse x_data must not collapse the zoom range."""

    @staticmethod
    def _make_signal(x_expr, x_data, data_store_time):
        s = SignalXY(label="s")
        s.data_store[0] = data_store_time
        s.data_store[1] = np.ones_like(data_store_time, dtype=float)
        s.x_data = x_data
        s.x_expr = x_expr
        return s

    def test_passes_ranges_when_x_data_is_sparse_summary(self):
        time = np.linspace(1000, 2000, 100).astype(np.int64)
        s = self._make_signal(
            x_expr="np.array([${self}.time[0],${self}.time[-1]])",
            x_data=np.asarray([time[0], time[-1]], dtype=np.int64),
            data_store_time=time,
        )
        s.set_limits((1200, 1500))
        self.assertEqual(s.ts_start, 1200)
        self.assertEqual(s.ts_end, 1500)

    def test_snaps_when_x_data_matches_data_store_length(self):
        # 1:1 mapping keeps the snap behaviour: result is bounded by the
        # requested window expanded by one sample on each side.
        time = np.linspace(1000, 2000, 101).astype(np.int64)
        s = self._make_signal(
            x_expr="${alias}.time",
            x_data=time.copy(),
            data_store_time=time,
        )
        s.set_limits((1200, 1500))
        self.assertGreaterEqual(s.ts_start, 1180)
        self.assertLessEqual(s.ts_start, 1210)
        self.assertGreaterEqual(s.ts_end, 1490)
        self.assertLessEqual(s.ts_end, 1520)

    def test_passes_ranges_for_default_x_expr(self):
        time = np.linspace(1000, 2000, 100).astype(np.int64)
        s = self._make_signal(
            x_expr="${self}.time",
            x_data=time.copy(),
            data_store_time=time,
        )
        s.set_limits((1234, 1789))
        self.assertEqual(s.ts_start, 1234)
        self.assertEqual(s.ts_end, 1789)

    def test_passes_ranges_when_x_data_is_empty(self):
        time = np.linspace(1000, 2000, 100).astype(np.int64)
        s = self._make_signal(
            x_expr="np.array([])",
            x_data=np.array([], dtype=np.int64),
            data_store_time=time,
        )
        s.set_limits((1111, 1999))
        self.assertEqual(s.ts_start, 1111)
        self.assertEqual(s.ts_end, 1999)


class RebasedTimeLimitsTest(unittest.TestCase):
    """X re-bases time ('${self}.time - T0'): its view maps back to a time
    window through the samples in memory, which must not stop a wider view
    (zoom out, undo) from bringing the rest of the data back."""

    START, END, STEP = 1000, 2000, 10

    def _drawn_signal(self):
        """Signal drawn over [START, END], its draw-time snapshot taken."""
        time = np.arange(self.START, self.END + 1, self.STEP, dtype=np.int64)
        s = SignalXY(label="rel", x_expr="${self}.time - 1000")
        s.ts_start, s.ts_end = self.START, self.END
        s.data_store[0] = time
        s.data_store[1] = np.ones(time.size)
        s._finalize_xyz_data([(time - self.START).astype(float), np.ones(time.size), np.zeros(0)])
        return s

    def _load(self, s, begin, end):
        """Replace the buffers with what a zoom over [begin, end] would fetch."""
        time = np.arange(begin, end + 1, self.STEP, dtype=np.int64)
        s.data_store[0] = time
        s.data_store[1] = np.ones(time.size)
        s.x_data = (time - self.START).astype(float)
        s.ts_start, s.ts_end = begin, end

    def test_wider_view_extends_the_window_past_the_loaded_samples(self):
        s = self._drawn_signal()
        self._load(s, 1300, 1500)
        s.set_limits((0, 1000))
        self.assertEqual((s.ts_start, s.ts_end), (self.START, self.END))

    def test_extension_stops_at_the_window_drawn(self):
        s = self._drawn_signal()
        self._load(s, 1300, 1500)
        s.set_limits((-5000, 9000))
        self.assertEqual((s.ts_start, s.ts_end), (self.START, self.END))

    def test_narrower_view_still_snaps_to_the_samples(self):
        s = self._drawn_signal()
        s.set_limits((200, 400))
        self.assertEqual((s.ts_start, s.ts_end), (1190, 1400))

    def test_view_of_the_requested_window_keeps_the_request(self):
        # Re-deriving the same window only changes the data hash (a refetch of
        # the same samples); within a sampling step at each edge it is the same.
        s = self._drawn_signal()
        for view in ((0, 1000), (3, 997)):
            with self.subTest(view=view), mock.patch.object(s, 'set_xranges') as set_xranges:
                s.set_limits(view)
                set_xranges.assert_not_called()

    def test_non_monotonic_x_is_not_extended(self):
        s = self._drawn_signal()
        self._load(s, 1300, 1500)
        s.x_data = s.x_data[::-1].copy()
        s.set_limits((0, 1000))
        self.assertEqual((s.ts_start, s.ts_end), (1300, 1500))

    def test_no_extension_without_a_draw_time_snapshot(self):
        time = np.arange(1300, 1501, self.STEP, dtype=np.int64)
        s = SignalXY(label="rel", x_expr="${self}.time - 1000")
        s.data_store[0] = time
        s.data_store[1] = np.ones(time.size)
        s.x_data = (time - self.START).astype(float)
        s.set_limits((0, 1000))
        self.assertEqual((s.ts_start, s.ts_end), (1300, 1500))

    def test_restore_keeps_an_equivalent_request(self):
        s = self._drawn_signal()
        s.ts_start, s.ts_end = self.START + 3, self.END - 3
        with mock.patch.object(s, 'set_xranges') as set_xranges:
            s.restore_xranges((self.START, self.END))
            set_xranges.assert_not_called()

    def test_restore_applies_a_different_request(self):
        s = self._drawn_signal()
        self._load(s, 1300, 1500)
        s.restore_xranges((self.START, self.END))
        self.assertEqual((s.ts_start, s.ts_end), (self.START, self.END))

    def test_whole_pulse_request_counts_as_what_was_drawn(self):
        # Pulse mode without start/end: the request names no bounds ('', '').
        time = np.arange(0.0, 10.01, 0.01)
        s = SignalXY(label="rel", x_expr="${self}.time - 2", pulse_nb="ITER:TEST/1")
        s.data_store[0] = time
        s.data_store[1] = np.ones(time.size)
        s._finalize_xyz_data([time - 2, np.ones(time.size), np.zeros(0)])
        self.assertEqual((s.ts_start, s.ts_end), ('', ''))
        with mock.patch.object(s, 'set_xranges') as set_xranges:
            s.set_limits((-2.0, 8.0))
            s.restore_xranges(('', ''))
            set_xranges.assert_not_called()
        s.set_limits((1.0, 3.0))
        s.restore_xranges(('', ''))
        self.assertEqual((s.ts_start, s.ts_end), ('', ''))

    def test_restore_of_a_time_signal_applies_the_request(self):
        time = np.arange(self.START, self.END + 1, self.STEP, dtype=np.int64)
        s = SignalXY(label="t")
        s.set_data([time, np.ones(time.size)])
        s.ts_start, s.ts_end = self.START + 3, self.END - 3
        s.restore_xranges((self.START, self.END))
        self.assertEqual((s.ts_start, s.ts_end), (self.START, self.END))


if __name__ == '__main__':
    unittest.main()
