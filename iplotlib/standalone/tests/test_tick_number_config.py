"""The configured tick_number must steer the date axis on both backends.

A multi-day window whose span falls between the calendar rungs of the tick
ladder (16 days: too long for day steps at a low target, too short for
weeks) used to collapse to two ticks regardless of the configured value.
The minimap builds its own bottom axis, so it must inherit the resolved
tick target instead of its constructor default.
"""

import unittest

import numpy as np

from iplotlib.core.canvas import Canvas
from iplotlib.core.plot import PlotXY
from iplotlib.core.signal import SignalXY
from iplotlib.qt.gui.iplotQtCanvasFactory import IplotQtCanvasFactory
from iplotlib.qt.testing import ensure_qapp

T_LO = 1_778_058_000_000_000_000   # 2026-05-06T09:00:00Z
T_HI = 1_779_440_400_000_000_000   # 2026-05-22T09:00:00Z (16 days later)


def _make_canvas(tick_number):
    core = Canvas(1, 1, title="tick-number")
    core.tick_number = tick_number
    x = np.linspace(T_LO, T_HI, 2000).astype(np.int64)
    plot = PlotXY()
    signal = SignalXY(label="s")
    signal.set_data([x, np.sin(np.linspace(0.0, 20.0, x.size))])
    plot.add_signal(signal)
    plot.axes[0].is_date = True
    core.add_plot(plot, 0)
    return core


class TickNumberConfigTest(unittest.TestCase):
    def setUp(self) -> None:
        super().setUp()
        self.app = ensure_qapp()

    def _build(self, backend: str, tick_number: int):
        core = _make_canvas(tick_number)
        qt_canvas = IplotQtCanvasFactory.new(backend, canvas=core)
        qt_canvas.set_canvas(core)
        qt_canvas.resize(1200, 700)
        self.app.processEvents()
        self.assertFalse(qt_canvas.grab().isNull())
        parser = qt_canvas._parser
        impl = parser._plot_impl_plot_lut.get(id(core.plots[0][0]))[0]
        return core, qt_canvas, impl

    def _visible_x_ticks(self, backend: str, impl) -> int:
        if backend == 'pyqt':
            axis = impl.getAxis('bottom')
            (xmin, xmax), _ = impl.getViewBox().viewRange()
            levels = axis.tickValues(xmin, xmax, axis.geometry().width())
            return len([v for _, grp in levels for v in grp if xmin <= v <= xmax])
        xaxis = impl.xaxis
        vmin, vmax = xaxis.get_view_interval()
        return len([t for t in xaxis.get_major_locator()() if vmin <= t <= vmax])

    def test_low_target_no_longer_collapses_to_two_ticks(self):
        for backend in ('pyqt', 'matplotlib'):
            _, qt_canvas, impl = self._build(backend, 5)
            n = self._visible_x_ticks(backend, impl)
            self.assertGreaterEqual(n, 4, backend)
            self.assertLessEqual(n, 8, backend)
            qt_canvas.deleteLater()

    def test_raising_the_target_adds_ticks(self):
        for backend in ('pyqt', 'matplotlib'):
            _, canvas_low, impl_low = self._build(backend, 5)
            n_low = self._visible_x_ticks(backend, impl_low)
            _, canvas_high, impl_high = self._build(backend, 12)
            n_high = self._visible_x_ticks(backend, impl_high)
            self.assertGreater(n_high, n_low, backend)
            canvas_low.deleteLater()
            canvas_high.deleteLater()

    def test_minimap_inherits_the_configured_tick_number(self):
        core, qt_canvas, impl = self._build('pyqt', 5)
        core.show_minimap = True
        core.snapshot_minimap_baseline(T_LO, T_HI)
        qt_canvas._update_minimap()
        self.app.processEvents()
        mm_axis = qt_canvas._minimap_plot.getAxis('bottom')
        self.assertEqual(mm_axis.n_ticks, impl.getAxis('bottom').n_ticks)
        qt_canvas.deleteLater()

    def test_matplotlib_minimap_inherits_the_configured_tick_number(self):
        core, qt_canvas, impl = self._build('matplotlib', 5)
        core.show_minimap = True
        core.snapshot_minimap_baseline(T_LO, T_HI)
        qt_canvas._update_minimap()
        self.app.processEvents()
        locator = qt_canvas._minimap_axes.xaxis.get_major_locator()
        self.assertEqual(locator.target_ticks,
                         impl.xaxis.get_major_locator().target_ticks)
        qt_canvas.deleteLater()


if __name__ == "__main__":
    unittest.main()
