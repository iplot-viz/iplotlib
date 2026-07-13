"""Reset-to-draw-range on real backends: toolbar Home and per-plot Reset zoom/pan.

After a zoom, both actions must restore the axis range captured at draw time,
reusing the same view-limit plumbing as undo/redo. Home is verified to be a
single undoable command so one undo reverts the whole reset, and to redraw
from the draw-time snapshot without issuing any data-access request.
"""

import copy
import unittest

import numpy as np

from iplotlib.core.canvas import Canvas
from iplotlib.core.commands.axes_range import IplotAxesRangeCmd
from iplotlib.core.plot import PlotXY
from iplotlib.core.signal import SignalXY
from iplotlib.qt.gui.iplotQtCanvasFactory import IplotQtCanvasFactory
from iplotlib.qt.gui.iplotQtMainWindow import IplotQtMainWindow
from iplotlib.qt.testing import ensure_qapp


def _make_canvas() -> Canvas:
    core = Canvas(1, 1, title="reset_view")
    x = np.linspace(0, 10, 200)
    plot = PlotXY()
    signal = SignalXY(label="s")
    signal.set_data([x, np.sin(x)])
    plot.add_signal(signal)
    core.add_plot(plot, 0)
    return core


class ResetViewTest(unittest.TestCase):
    def setUp(self) -> None:
        super().setUp()
        self.app = ensure_qapp()

    def _build(self, backend: str):
        canvas = _make_canvas()
        qt_canvas = IplotQtCanvasFactory.new(backend, canvas=canvas)
        qt_canvas.set_canvas(canvas)
        qt_canvas.resize(800, 600)
        self.app.processEvents()
        return canvas, qt_canvas

    def _x_range(self, qt_canvas):
        axis_range = qt_canvas._parser.get_all_plot_limits()[0].axes_ranges[0]
        return axis_range.begin, axis_range.end

    def _y_range(self, qt_canvas):
        axis_range = qt_canvas._parser.get_all_plot_limits()[0].axes_ranges[1]
        return axis_range.begin, axis_range.end

    def _zoom_in(self, qt_canvas, factor: float = 0.25):
        """Apply a zoom that narrows both X and Y, mimicking a user rubber-band."""
        parser = qt_canvas._parser
        current = parser.get_all_plot_limits()
        narrowed = copy.deepcopy(current)
        # deepcopy drops weakrefs; restore them from the originals.
        for src, dst in zip(current, narrowed):
            dst.plot_ref = src.plot_ref
            for s_src, s_dst in zip(src.signals_ranges, dst.signals_ranges):
                s_dst.signal_ref = s_src.signal_ref
        for axis_idx in (0, 1):
            rng = current[0].axes_ranges[axis_idx]
            span = rng.end - rng.begin
            narrowed[0].axes_ranges[axis_idx].set_limits(rng.begin + span * factor,
                                                         rng.end - span * factor)
        cmd = IplotAxesRangeCmd('Zoom', old_limits=current, new_limits=narrowed, parser=parser)
        parser._hm.done(cmd)
        cmd()
        self.app.processEvents()

    def test_reset_all_views_restores_draw_range(self):
        for backend in ('matplotlib', 'pyqt'):
            with self.subTest(backend=backend):
                _, qt_canvas = self._build(backend)
                original = self._x_range(qt_canvas)
                self._zoom_in(qt_canvas)
                self.assertNotAlmostEqual(self._x_range(qt_canvas)[0], original[0], places=3)

                qt_canvas.reset_all_views()
                self.app.processEvents()

                restored = self._x_range(qt_canvas)
                self.assertAlmostEqual(restored[0], original[0], places=3)
                self.assertAlmostEqual(restored[1], original[1], places=3)

    def test_reset_plot_view_restores_draw_range(self):
        for backend in ('matplotlib', 'pyqt'):
            with self.subTest(backend=backend):
                canvas, qt_canvas = self._build(backend)
                original = self._x_range(qt_canvas)
                self._zoom_in(qt_canvas)

                plot = canvas.plots[0][0]
                impl_plot = qt_canvas._parser._plot_impl_plot_lut[id(plot)][0]
                qt_canvas.reset_plot_view(impl_plot)
                self.app.processEvents()

                restored = self._x_range(qt_canvas)
                self.assertAlmostEqual(restored[0], original[0], places=3)
                self.assertAlmostEqual(restored[1], original[1], places=3)

    def test_home_is_single_undoable_command(self):
        for backend in ('matplotlib', 'pyqt'):
            with self.subTest(backend=backend):
                _, qt_canvas = self._build(backend)
                self._zoom_in(qt_canvas)
                zoomed = self._x_range(qt_canvas)

                qt_canvas.reset_all_views()
                self.app.processEvents()

                self.assertTrue(qt_canvas.can_undo())
                self.assertEqual(qt_canvas.get_next_undo_cmd_name(), 'Home')

                qt_canvas._parser._hm.undo()
                self.app.processEvents()

                reverted = self._x_range(qt_canvas)
                self.assertAlmostEqual(reverted[0], zoomed[0], places=3)
                self.assertAlmostEqual(reverted[1], zoomed[1], places=3)

    def test_reset_restores_draw_time_y_margin(self):
        # The reset must reproduce the Draw view including the Y margin, not the
        # tighter raw-data extent.
        for backend in ('matplotlib', 'pyqt'):
            with self.subTest(backend=backend):
                _, qt_canvas = self._build(backend)
                draw_y = self._y_range(qt_canvas)
                self._zoom_in(qt_canvas)
                self.assertNotAlmostEqual(self._y_range(qt_canvas)[0], draw_y[0], places=3)

                qt_canvas.reset_all_views()
                self.app.processEvents()

                reset_y = self._y_range(qt_canvas)
                self.assertAlmostEqual(reset_y[0], draw_y[0], places=3)
                self.assertAlmostEqual(reset_y[1], draw_y[1], places=3)

    def test_reset_redraws_from_snapshot_without_data_access(self):
        # Home must serve the redraw from the draw-time snapshot: the signal's
        # data-access path must not run while the view is being restored, and the
        # curve must recover its full extent even if a zoom left partial buffers.
        for backend in ('matplotlib', 'pyqt'):
            with self.subTest(backend=backend):
                canvas, qt_canvas = self._build(backend)
                signal = next(iter(canvas.plots[0][0].signals.values()))[0]
                full_len = len(signal.x_data)

                calls = {'get_data': 0}
                original_get_data = signal.get_data

                def spied_get_data():
                    calls['get_data'] += 1
                    return original_get_data()

                signal.get_data = spied_get_data
                self._zoom_in(qt_canvas)

                # Simulate the partial buffers left by a downsampled sub-range refetch.
                signal.x_data = signal.x_data[:20]
                signal.y_data = signal.y_data[:20]
                calls['get_data'] = 0

                qt_canvas.reset_all_views()
                self.app.processEvents()

                self.assertEqual(calls['get_data'], 0)
                self.assertEqual(len(signal.x_data), full_len)
                line = qt_canvas._parser._signal_impl_shape_lut[id(signal)][0]
                line_x = line.get_xdata() if backend == 'matplotlib' else line.getData()[0]
                self.assertEqual(len(line_x), full_len)

    def test_restore_minimap_snapshot_roundtrip(self):
        # The snapshot restore is the inverse of the capture done on first load.
        x = np.linspace(0, 10, 200)
        signal = SignalXY(label="s")
        signal.set_data([x, np.sin(x)])
        signal.x_data = signal.x_data[:20]
        signal.y_data = signal.y_data[:20]

        data = signal.restore_minimap_snapshot()

        self.assertIsNotNone(data)
        self.assertEqual(len(data[0]), 200)
        self.assertEqual(len(signal.x_data), 200)
        np.testing.assert_allclose(np.asarray(signal.y_data), np.sin(x))

    def test_restore_minimap_snapshot_without_data(self):
        signal = SignalXY(label="empty")
        self.assertIsNone(signal.restore_minimap_snapshot())

    def test_home_action_always_enabled(self):
        # Home is always clickable; it is a no-op when there is nothing to reset.
        win = IplotQtMainWindow()
        try:
            qt_canvas = IplotQtCanvasFactory.new('matplotlib', canvas=_make_canvas())
            qt_canvas.set_canvas(qt_canvas.get_canvas())
            win.canvasStack.addWidget(qt_canvas)
            self.app.processEvents()
            self.assertTrue(win.toolBar.homeAction.isEnabled())

            win.check_history(qt_canvas)
            self.assertTrue(win.toolBar.homeAction.isEnabled())
        finally:
            win.close()


if __name__ == '__main__':
    unittest.main()
