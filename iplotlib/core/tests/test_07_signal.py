"""Unit tests for SignalXY and SignalContour."""

import unittest

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


if __name__ == '__main__':
    unittest.main()
