"""A zoom down to nanoseconds must reach every plot sharing the time axis.

The shared-axis callback reads the zoomed plot's limits back from the backend
as floats and re-adds the nanosecond offset. Near 1e18 a float64 sum only
resolves 256 ns, so an 80 ns window came back with begin == end: matplotlib
expanded the singular range on its own and pyqtgraph left the siblings on
their old range under a new offset, so the shared time visibly stopped
being shared.

One nanosecond is the floor of what the axis can express, so a drag
narrower than that has to stop above it instead of collapsing.
"""

import unittest
import warnings

import numpy as np
from PySide6.QtGui import QImage, QPainter

from iplotlib.core.canvas import Canvas
from iplotlib.core.plot import PlotXY
from iplotlib.core.signal import SignalXY
from iplotlib.qt.gui.iplotQtCanvasFactory import IplotQtCanvasFactory
from iplotlib.qt.testing import ensure_qapp

T0 = 1_788_873_880_000_000_000        # 2026-09-08T13:24:40Z
CENTER = T0 + 1800 * 10**9 + 377_625_600
WINDOW = (CENTER - 40, CENTER + 40)   # 80 ns, well under the 256 ns float64 step


def _make_canvas() -> Canvas:
    core = Canvas(2, 1, title="ns-zoom", shared_x_axis=True)
    core.tick_number = 5
    x = (T0 + np.arange(0, 3600) * 10**9).astype(np.int64)
    for row in range(2):
        plot = PlotXY()
        signal = SignalXY(label=f"s{row}")
        signal.set_data([x, np.sin(np.linspace(0.0, 20.0, x.size) + row)])
        plot.add_signal(signal)
        plot.axes[0].is_date = True
        core.add_plot(plot, 0)
    return core


def _painted_x_labels(backend: str, impl) -> list:
    """The tick labels the backend really paints, not the candidates."""
    if backend == 'pyqt':
        # The image must outlive the painter, so keep a reference to it.
        surface = QImage(16, 16, QImage.Format_ARGB32)
        painter = QPainter(surface)
        try:
            specs = impl.getAxis('bottom').generateDrawSpecs(painter)
        finally:
            painter.end()
        return [] if specs is None else [text for _, _, text in specs[2]]
    impl.figure.canvas.draw()
    return [t.get_text() for t in impl.get_xticklabels() if t.get_text()]


class SharedAxisNanosecondZoomTest(unittest.TestCase):
    def setUp(self) -> None:
        super().setUp()
        self.app = ensure_qapp()

    def _build(self, backend: str):
        core = _make_canvas()
        qt_canvas = IplotQtCanvasFactory.new(backend, canvas=core)
        qt_canvas.set_canvas(core)
        qt_canvas.resize(1200, 800)
        self.app.processEvents()
        parser = qt_canvas._parser
        impls = [parser._plot_impl_plot_lut.get(id(core.plots[0][row]))[0] for row in range(2)]
        return core, qt_canvas, impls

    def test_an_80ns_window_is_shared_exactly(self):
        for backend in ('pyqt', 'matplotlib'):
            with self.subTest(backend=backend):
                core, qt_canvas, impls = self._build(backend)
                parser = qt_canvas._parser
                with warnings.catch_warnings(record=True) as caught:
                    warnings.simplefilter("always")
                    parser.set_oaw_axis_limits(impls[0], 0, WINDOW)
                    self.app.processEvents()
                self.assertFalse([w for w in caught if 'singular' in str(w.message)], backend)
                for impl in impls:
                    self.assertEqual(parser.get_oaw_axis_limits(impl, 0), WINDOW, backend)
                for plot in (core.plots[0][0], core.plots[0][1]):
                    self.assertEqual(plot.axes[0].get_limits('current'), WINDOW, backend)
                    # Whole nanoseconds, so a saved workspace restores the same window.
                    self.assertIsInstance(plot.axes[0].begin, int, backend)
                qt_canvas.deleteLater()

    def test_the_wide_view_still_round_trips(self):
        for backend in ('pyqt', 'matplotlib'):
            with self.subTest(backend=backend):
                core, qt_canvas, impls = self._build(backend)
                parser = qt_canvas._parser
                lo, hi = parser.get_oaw_axis_limits(impls[0], 0)
                self.assertEqual((lo, hi), parser.get_oaw_axis_limits(impls[1], 0), backend)
                self.assertGreater(hi - lo, 3500 * 10**9, backend)
                qt_canvas.deleteLater()

    def test_a_drag_below_one_nanosecond_stops_at_the_nanosecond(self):
        for backend in ('pyqt', 'matplotlib'):
            with self.subTest(backend=backend):
                core, qt_canvas, impls = self._build(backend)
                parser = qt_canvas._parser
                parser.set_oaw_axis_limits(impls[0], 0, WINDOW)
                self.app.processEvents()
                with warnings.catch_warnings(record=True) as caught:
                    warnings.simplefilter("always")
                    # A rubber band 0.8 ns wide, in the view coordinates the
                    # backend hands back to the shared-axis callback.
                    parser.set_impl_x_axis_limits(impls[0], (-0.4, 0.4))
                    self.app.processEvents()
                self.assertFalse([w for w in caught if 'singular' in str(w.message)], backend)
                windows = {parser.get_oaw_axis_limits(impl, 0) for impl in impls}
                self.assertEqual(len(windows), 1, backend)
                begin, end = windows.pop()
                self.assertEqual(end - begin, 2, backend)
                for impl in impls:
                    # A one-nanosecond window would carry both its ticks on the
                    # edges, where pyqtgraph paints neither label.
                    self.assertTrue(_painted_x_labels(backend, impl), backend)
                for plot in (core.plots[0][0], core.plots[0][1]):
                    self.assertEqual(plot.axes[0].get_limits('current'), (begin, end), backend)
                qt_canvas.deleteLater()


if __name__ == '__main__':
    unittest.main()
