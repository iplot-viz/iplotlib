"""Interactions must survive a canvas that changes under them.

Panning can trigger a data refetch that redraws the canvas before the
mouse is released, and data-derived limits reach the axes as numpy scalars.
Neither may crash the gesture or flood the ViewBox with overflow warnings.
"""

import unittest
import warnings

import numpy as np

from iplotlib.core.canvas import Canvas
from iplotlib.core.plot import PlotXY
from iplotlib.core.signal import SignalXY
from iplotlib.interface.iplotSignalAdapter import _as_python_number
from iplotlib.qt.gui.iplotQtCanvasFactory import IplotQtCanvasFactory
from iplotlib.qt.testing import ensure_qapp

T_LO = 1_778_058_000_000_000_000
T_HI = T_LO + 16 * 86400 * 10**9


def _make_canvas(rows: int, shared: bool) -> Canvas:
    core = Canvas(rows, 1, title="rebuild", shared_x_axis=shared)
    x = np.linspace(T_LO, T_HI, 2000).astype(np.uint64)
    for row in range(rows):
        plot = PlotXY()
        signal = SignalXY(label=f"s{row}")
        signal.set_data([x, np.sin(np.linspace(0.0, 20.0, x.size) + row).astype(np.float32)])
        plot.add_signal(signal)
        plot.axes[0].is_date = True
        core.add_plot(plot, 0)
    return core


class CommitAfterPlotSetChangeTest(unittest.TestCase):
    def setUp(self) -> None:
        super().setUp()
        self.app = ensure_qapp()

    def _build(self, backend: str, rows: int = 2, shared: bool = True):
        core = _make_canvas(rows, shared)
        qt_canvas = IplotQtCanvasFactory.new(backend, canvas=core)
        qt_canvas.set_canvas(core)
        qt_canvas.resize(1000, 700)
        self.app.processEvents()
        impl = qt_canvas._parser._plot_impl_plot_lut.get(id(core.plots[0][0]))[0]
        return core, qt_canvas, impl

    def test_commit_drops_the_command_when_the_plot_set_changed(self):
        for backend in ('pyqt', 'matplotlib'):
            with self.subTest(backend=backend):
                core, qt_canvas, impl = self._build(backend)
                qt_canvas.stage_view_lim_cmd(impl, name='Pan')
                self.assertEqual(len(qt_canvas._staging_cmds[0].old_lim), 2)
                # A redraw during the drag narrows what the release can see.
                qt_canvas._parser._focus_plot = core.plots[0][0]
                qt_canvas.commit_view_lim_cmd(impl)
                self.assertEqual(qt_canvas._staging_cmds, [])
                self.assertEqual(qt_canvas._commitd_cmds, [])
                qt_canvas.deleteLater()

    def test_commit_still_records_a_real_change(self):
        for backend in ('pyqt', 'matplotlib'):
            with self.subTest(backend=backend):
                core, qt_canvas, impl = self._build(backend)
                parser = qt_canvas._parser
                qt_canvas.stage_view_lim_cmd(impl, name='Zoom')
                lo, hi = parser.get_oaw_axis_limits(impl, 0)
                span = hi - lo
                parser.set_oaw_axis_limits(impl, 0, (lo + span * 0.25, hi - span * 0.25))
                self.app.processEvents()
                qt_canvas.commit_view_lim_cmd(impl)
                self.assertEqual(len(qt_canvas._commitd_cmds), 1)
                qt_canvas.deleteLater()


class MinimapNumpyBaselineTest(unittest.TestCase):
    def setUp(self) -> None:
        super().setUp()
        self.app = ensure_qapp()

    def _build_with_minimap(self, baseline):
        core = _make_canvas(1, shared=False)
        qt_canvas = IplotQtCanvasFactory.new('pyqt', canvas=core)
        qt_canvas.set_canvas(core)
        qt_canvas.resize(1000, 700)
        self.app.processEvents()
        core.show_minimap = True
        core.snapshot_minimap_baseline(*baseline)
        return core, qt_canvas

    def _pan_and_zoom(self, core, qt_canvas):
        impl = qt_canvas._parser._plot_impl_plot_lut.get(id(core.plots[0][0]))[0]
        view_box = impl.getViewBox()
        (xmin, xmax), _ = view_box.viewRange()
        span = xmax - xmin
        for k in range(1, 4):
            view_box.setXRange(xmin + 0.1 * k * span, xmax - 0.1 * k * span, padding=0)
            self.app.processEvents()
        view_box.translateBy(x=0.05 * span)
        self.app.processEvents()
        qt_canvas._sync_minimap_viewport()
        self.app.processEvents()

    def test_numpy_baselines_neither_warn_nor_wrap(self):
        # float32 limits used to overflow the ViewBox casts on every pan; a
        # uint64 pair wrapped past 2**64 when shifted by the offset.
        for dtype in (np.float32, np.uint64, np.int64, np.float64):
            with self.subTest(dtype=dtype.__name__):
                core, qt_canvas = self._build_with_minimap((dtype(T_LO), dtype(T_HI)))
                with warnings.catch_warnings(record=True) as caught:
                    warnings.simplefilter('always')
                    qt_canvas._update_minimap()
                    self.app.processEvents()
                    self._pan_and_zoom(core, qt_canvas)
                overflow = [w for w in caught if issubclass(w.category, RuntimeWarning)]
                self.assertEqual(overflow, [], [str(w.message) for w in overflow])
                limits = qt_canvas._minimap_plot.getViewBox().state['limits']['xLimits']
                self.assertTrue(all(type(v) is int for v in limits), limits)
                qt_canvas.deleteLater()


class DataXRangeTypeTest(unittest.TestCase):
    def test_data_xrange_returns_python_numbers(self):
        for dtype, kind in ((np.uint64, int), (np.int64, int), (np.float32, float), (np.float64, float)):
            with self.subTest(dtype=dtype.__name__):
                lo, hi = _as_python_number(dtype(3)), _as_python_number(dtype(7))
                self.assertIs(type(lo), kind)
                self.assertIs(type(hi), kind)
        self.assertEqual(_as_python_number(np.uint64(T_LO)), T_LO)
        self.assertEqual(_as_python_number(5), 5)


if __name__ == "__main__":
    unittest.main()
