"""Wide date windows on the pyqtgraph backend.

Qt 6.9.x treats a view matrix whose horizontal scale (m11) falls below its
1e-12 fuzzy-null epsilon as degenerate. With axis coordinates in raw
nanoseconds, a date window wider than a few days crosses that threshold: the
zoom rubber band never appears and the applied ranges are garbage. Only
Qt 6.9.x shows the visual breakage, but the near-degenerate matrix itself is
measurable on every platform, which is what these tests pin down: the
adaptive unit scale keeps the coordinate span — and therefore m11 — far from
the epsilon, narrow windows keep integer-nanosecond coordinates, and the
matplotlib backend keeps raw units entirely.
"""

import unittest

import numpy as np

from iplotlib.core.canvas import Canvas
from iplotlib.core.plot import PlotXY
from iplotlib.core.signal import SignalXY
from iplotlib.impl.pyqtgraph.dateFormatter import NanosecondDateFormatter
from iplotlib.qt.gui.iplotQtCanvasFactory import IplotQtCanvasFactory
from iplotlib.qt.testing import ensure_qapp

T0 = 1_683_802_010_522_704_384  # absolute ns epoch, ~May 2023
DAY_NS = 86_400_000_000_000


def _make_canvas(span_ns: int) -> Canvas:
    core = Canvas(1, 1, title="wide-window")
    x = (T0 + np.linspace(0, span_ns, 500)).astype(np.int64)
    plot = PlotXY()
    signal = SignalXY(label="s")
    signal.set_data([x, np.sin(np.linspace(0.0, 20.0, x.size))])
    plot.add_signal(signal)
    plot.axes[0].is_date = True
    core.add_plot(plot, 0)
    return core


class WideWindowZoomTest(unittest.TestCase):
    def setUp(self) -> None:
        super().setUp()
        self.app = ensure_qapp()

    def _build(self, backend: str, span_ns: int):
        canvas = _make_canvas(span_ns)
        qt_canvas = IplotQtCanvasFactory.new(backend, canvas=canvas)
        qt_canvas.set_canvas(canvas)
        qt_canvas.resize(800, 600)
        self.app.processEvents()
        self.assertFalse(qt_canvas.grab().isNull())
        parser = qt_canvas._parser
        impl = parser._plot_impl_plot_lut.get(id(canvas.plots[0][0]))[0]
        return parser, impl

    def test_wide_window_transform_stays_representable(self):
        parser, impl = self._build('pyqt', 20 * DAY_NS)
        ci = parser._impl_plot_cache_table.get_cache_item(impl)
        self.assertEqual(ci.scales[0], 10_000)
        m11 = impl.getViewBox().childGroup.transform().m11()
        self.assertGreater(m11, 1e-10)

    def test_narrow_window_keeps_integer_ns_unit(self):
        parser, impl = self._build('pyqt', 600_000_000_000)  # 10 minutes
        ci = parser._impl_plot_cache_table.get_cache_item(impl)
        self.assertEqual(ci.scales[0], 1)

    def test_zoom_round_trip_on_wide_window(self):
        parser, impl = self._build('pyqt', 20 * DAY_NS)
        ci = parser._impl_plot_cache_table.get_cache_item(impl)

        parser.set_oaw_axis_limits(impl, 0, (T0 + DAY_NS, T0 + 3 * DAY_NS))
        self.app.processEvents()
        self.assertEqual(ci.scales[0], 1_000)
        begin, end = parser.get_oaw_axis_limits(impl, 0)
        self.assertAlmostEqual(begin, T0 + DAY_NS, delta=1e3)
        self.assertAlmostEqual(end, T0 + 3 * DAY_NS, delta=1e3)

        # Deep zoom returns to integer-nanosecond coordinates: precision that
        # a coarse unit could not represent must survive the transition.
        parser.set_oaw_axis_limits(impl, 0, (T0, T0 + 1_000))
        self.app.processEvents()
        self.assertEqual(ci.scales[0], 1)
        begin, end = parser.get_oaw_axis_limits(impl, 0)
        self.assertAlmostEqual(begin, T0, delta=1)
        self.assertAlmostEqual(end, T0 + 1_000, delta=1)

    def test_matplotlib_keeps_raw_units(self):
        parser, impl = self._build('matplotlib', 20 * DAY_NS)
        ci = parser._impl_plot_cache_table.get_cache_item(impl)
        self.assertEqual(ci.scales[0], 1)
        begin, end = parser.get_oaw_axis_limits(impl, 0)
        self.assertAlmostEqual(begin, T0, delta=1e9)
        self.assertAlmostEqual(end, T0 + 20 * DAY_NS, delta=1e9)

    def test_formatter_round_trip_with_unit_scale(self):
        axis = NanosecondDateFormatter(orientation='bottom')
        midpoint = T0 + 10 * DAY_NS
        axis.set_offset(midpoint)
        axis.set_unit_scale(10_000)
        for tick_ns in (T0, T0 + DAY_NS, T0 + 19 * DAY_NS + 3_600_000_000_000):
            self.assertEqual(axis.get_real_value(axis._abs_to_axis(tick_ns)), tick_ns)


if __name__ == '__main__':
    unittest.main()
