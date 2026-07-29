"""Reset-to-draw-range on real backends: toolbar Home and per-plot Reset zoom/pan.

After a zoom, both actions must restore the axis range captured at draw time,
reusing the same view-limit plumbing as undo/redo. Home is verified to be a
single undoable command so one undo reverts the whole reset, and to redraw
from the draw-time snapshot without issuing any data-access request.

With a shared X axis the per-plot reset is verified over the whole group.
"""

import copy
import unittest

import numpy as np
from iplotProcessing.core import BufferObject

from iplotlib.core.canvas import Canvas
from iplotlib.core.commands.axes_range import IplotAxesRangeCmd
from iplotlib.core.impl_base import BackendParserBase
from iplotlib.core.plot import PlotXY
from iplotlib.core.signal import SignalXY
from iplotlib.qt.gui.iplotQtCanvasFactory import IplotQtCanvasFactory
from iplotlib.qt.gui.iplotQtMainWindow import IplotQtMainWindow
from iplotlib.qt.testing import ensure_qapp

TS_START = 1_754_463_600_000_000_000
TS_END = 1_754_503_200_000_000_000
SECOND = 1_000_000_000


def _make_canvas() -> Canvas:
    core = Canvas(1, 1, title="reset_view")
    x = np.linspace(0, 10, 200)
    plot = PlotXY()
    signal = SignalXY(label="s")
    signal.set_data([x, np.sin(x)])
    plot.add_signal(signal)
    core.add_plot(plot, 0)
    return core


def _make_shared_time_canvas(shared: bool = True) -> Canvas:
    """Two time plots, the smallest canvas a shared time group can be formed on."""
    core = Canvas(2, 1, title="reset_view_shared", shared_x_axis=shared)
    time = np.linspace(TS_START, TS_END, 200).astype(np.int64)
    for i in range(2):
        plot = PlotXY()
        signal = SignalXY(label=f"s{i}")
        signal.ts_start = TS_START
        signal.ts_end = TS_END
        signal.set_data([time, np.sin(np.linspace(0, 6, 200) + i)])
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

    def _build_shared(self, backend: str, shared: bool = True):
        canvas = _make_shared_time_canvas(shared)
        qt_canvas = IplotQtCanvasFactory.new(backend, canvas=canvas)
        qt_canvas.set_canvas(canvas)
        qt_canvas.resize(600, 400)
        self.app.processEvents()
        return canvas, qt_canvas

    @staticmethod
    def _impl_plots(canvas, qt_canvas):
        """Implementation plots in canvas order, re-resolved after every redraw."""
        lut = qt_canvas._parser._plot_impl_plot_lut
        return [lut[id(plot)][0] for plot in canvas.plots[0]]

    def _shared_zoom(self, qt_canvas, impl_plot, window):
        """Zoom the way a mouse gesture does, so the shared-x propagation runs."""
        parser = qt_canvas._parser
        parser.set_oaw_axis_limits(impl_plot, 0, window)
        BackendParserBase._x_axis_update_callback(parser, impl_plot)
        self.app.processEvents()

    def test_reset_plot_view_restores_the_whole_shared_group(self):
        window = (TS_START + 100 * SECOND, TS_END - 100 * SECOND)
        for backend in ('matplotlib', 'pyqt'):
            with self.subTest(backend=backend):
                canvas, qt_canvas = self._build_shared(backend)
                parser = qt_canvas._parser
                impl_plots = self._impl_plots(canvas, qt_canvas)
                drawn = [parser.get_oaw_axis_limits(impl, 0) for impl in impl_plots]

                self._shared_zoom(qt_canvas, impl_plots[0], window)
                for impl in impl_plots:
                    self.assertAlmostEqual(parser.get_oaw_axis_limits(impl, 0)[0],
                                           window[0], delta=SECOND)

                # Invoked on the plot the zoom was not made on: the whole group follows.
                qt_canvas.reset_plot_view(impl_plots[1])
                self.app.processEvents()

                for impl, (begin, end) in zip(self._impl_plots(canvas, qt_canvas), drawn):
                    restored = parser.get_oaw_axis_limits(impl, 0)
                    self.assertAlmostEqual(restored[0], begin, delta=SECOND)
                    self.assertAlmostEqual(restored[1], end, delta=SECOND)

    def test_reset_plot_view_restores_the_group_without_data_access(self):
        # Same contract as Home: the restore is served from the draw-time snapshots.
        window = (TS_START + 100 * SECOND, TS_END - 100 * SECOND)
        for backend in ('matplotlib', 'pyqt'):
            with self.subTest(backend=backend):
                canvas, qt_canvas = self._build_shared(backend)
                impl_plots = self._impl_plots(canvas, qt_canvas)
                other_signal = next(iter(canvas.plots[0][0].signals.values()))[0]
                full_len = len(other_signal.x_data)
                self._shared_zoom(qt_canvas, impl_plots[0], window)

                calls = {'get_data': 0}
                original_get_data = other_signal.get_data

                def spied_get_data():
                    calls['get_data'] += 1
                    return original_get_data()

                other_signal.get_data = spied_get_data

                qt_canvas.reset_plot_view(impl_plots[1])
                self.app.processEvents()

                self.assertEqual(calls['get_data'], 0)
                self.assertEqual(len(other_signal.x_data), full_len)

    def test_reset_plot_view_keeps_the_other_plots_y_range(self):
        # Only the plot the action was invoked on gets its Y reset.
        window = (TS_START + 100 * SECOND, TS_END - 100 * SECOND)
        other_y = (-5.0, 5.0)
        for backend in ('matplotlib', 'pyqt'):
            with self.subTest(backend=backend):
                canvas, qt_canvas = self._build_shared(backend)
                parser = qt_canvas._parser
                impl_plots = self._impl_plots(canvas, qt_canvas)
                self._shared_zoom(qt_canvas, impl_plots[0], window)
                parser.set_oaw_axis_limits(impl_plots[0], 1, other_y)
                self.app.processEvents()

                qt_canvas.reset_plot_view(impl_plots[1])
                self.app.processEvents()

                kept = parser.get_oaw_axis_limits(self._impl_plots(canvas, qt_canvas)[0], 1)
                self.assertAlmostEqual(kept[0], other_y[0], places=3)
                self.assertAlmostEqual(kept[1], other_y[1], places=3)

    def test_reset_plot_view_leaves_the_others_alone_without_shared_x(self):
        # Without a shared X axis the action stays limited to one plot.
        window = (TS_START + 100 * SECOND, TS_END - 100 * SECOND)
        for backend in ('matplotlib', 'pyqt'):
            with self.subTest(backend=backend):
                canvas, qt_canvas = self._build_shared(backend, shared=False)
                parser = qt_canvas._parser
                impl_plots = self._impl_plots(canvas, qt_canvas)
                self._shared_zoom(qt_canvas, impl_plots[0], window)
                zoomed = parser.get_oaw_axis_limits(impl_plots[0], 0)

                qt_canvas.reset_plot_view(impl_plots[1])
                self.app.processEvents()

                kept = parser.get_oaw_axis_limits(self._impl_plots(canvas, qt_canvas)[0], 0)
                self.assertAlmostEqual(kept[0], zoomed[0], delta=SECOND)
                self.assertAlmostEqual(kept[1], zoomed[1], delta=SECOND)

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

    def test_restore_minimap_snapshot_realigns_envelope_store(self):
        # A zoom refetch of another size must not leave the raw envelope store
        # misaligned with the displayed data (statistics index it by mask).
        x = np.linspace(0, 10, 200)
        signal = SignalXY(label="e", envelope=True)
        # The avg slot only exists after an envelope fetch; emulate its layout.
        while len(signal.data_store) < 4:
            signal.data_store.append(BufferObject())
        signal.data_store[3] = BufferObject(np.sin(x))
        signal.set_data([x, np.sin(x) - 1, np.sin(x) + 1])

        signal.x_data = signal.x_data[:50]
        signal.y_data = signal.y_data[:50]
        signal.z_data = signal.z_data[:50]
        for i in range(4):
            signal.data_store[i] = signal.data_store[i][:53]

        data = signal.restore_minimap_snapshot()

        self.assertEqual(len(data), 4)
        self.assertEqual(len(signal.x_data), 200)
        for i in range(4):
            self.assertEqual(len(signal.data_store[i]), 200)

    def test_restore_minimap_snapshot_restores_downsampled_state(self):
        # A deep zoom can refetch raw data and clear the downsampled flag. The
        # restore must bring back the draw-time state, so the next zoom fetches
        # finer data again instead of serving the coarse full-range buffers.
        x = np.linspace(0, 10, 200)
        signal = SignalXY(label="s", isDownsampled=True)
        signal.set_data([x, np.sin(x)])
        signal.isDownsampled = False
        signal.x_data = signal.x_data[:20]
        signal.y_data = signal.y_data[:20]

        signal.restore_minimap_snapshot()

        self.assertTrue(signal.isDownsampled)
        self.assertEqual(len(signal.x_data), 200)

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
