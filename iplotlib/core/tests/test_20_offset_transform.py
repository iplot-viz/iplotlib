"""The view/absolute conversion must stay exact at nanosecond scale.

Backends hand view coordinates back as floats. Added to a nanosecond offset
near 1e18, a float64 sum only resolves 256 ns, so a window narrower than
that came back with begin == end and the shared time axis had nothing left
to share.
"""

import unittest

import numpy as np

from iplotlib.core.canvas import Canvas
from iplotlib.core.impl_base import ImplementationPlotCacheTable
from iplotlib.core.plot import PlotXY

OFFSET = 1_788_875_680_377_625_600   # 2026-09-08T13:24:40.377625600Z


class _Impl:
    pass


class OffsetTransformTests(unittest.TestCase):
    def setUp(self) -> None:
        self.table = ImplementationPlotCacheTable()
        self.impl = _Impl()
        self.canvas, self.plot = Canvas(1, 1), PlotXY()
        self.table.register(self.impl, canvas=self.canvas, plot=self.plot)
        self.ci = self.table.get_cache_item(self.impl)

    def test_float_view_coordinates_map_back_to_exact_nanoseconds(self):
        self.ci.offsets[0] = OFFSET
        lo = self.table.transform_value(self.impl, 0, np.float64(-40.0))
        hi = self.table.transform_value(self.impl, 0, np.float64(40.0))
        self.assertEqual((lo, hi), (OFFSET - 40, OFFSET + 40))
        self.assertIsInstance(lo, int)

    def test_round_trip_keeps_an_80ns_window(self):
        self.ci.offsets[0] = OFFSET
        for value in (OFFSET - 40, OFFSET + 40):
            view = self.table.transform_value(self.impl, 0, value, inverse=True)
            self.assertEqual(self.table.transform_value(self.impl, 0, float(view)), value)

    def test_scaled_axis_units_stay_exact(self):
        self.ci.offsets[0] = OFFSET
        self.ci.scales[0] = 10
        self.assertEqual(self.table.transform_value(self.impl, 0, np.float64(-4.0)), OFFSET - 40)

    def test_axis_without_offset_is_left_alone(self):
        self.ci.offsets[1] = 0
        out = self.table.transform_value(self.impl, 1, 0.25)
        self.assertEqual(out, 0.25)
        self.assertIsInstance(out, float)

    def test_non_finite_values_pass_through(self):
        self.ci.offsets[0] = OFFSET
        self.assertTrue(np.isnan(self.table.transform_value(self.impl, 0, float('nan'))))

    def test_legacy_fixed_scale_offset_is_unchanged(self):
        self.ci.offsets[0] = 100_000
        self.assertEqual(self.table.transform_value(self.impl, 0, 3.0), 300_000.0)
        self.assertEqual(self.table.transform_value(self.impl, 0, 300_000, inverse=True), 3.0)


if __name__ == '__main__':
    unittest.main()
