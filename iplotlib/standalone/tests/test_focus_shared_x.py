"""Focus mode against a shared X axis.

A zoom made in focus must leave the canvas as if it had been made without entering
focus: once unfocused, every plot of the shared group sits in the zoomed window. The
signal ts matters as much as the axis range, since the group is formed by comparing
it, so a plot left behind drops out and no later group action reaches it.
"""

import unittest

import numpy as np

from iplotlib.core.canvas import Canvas
from iplotlib.core.impl_base import BackendParserBase
from iplotlib.core.plot import PlotXY
from iplotlib.core.signal import SignalXY
from iplotlib.qt.gui.iplotQtCanvasFactory import IplotQtCanvasFactory
from iplotlib.qt.testing import ensure_qapp

BACKENDS = ('matplotlib', 'pyqt')
TS_START = 1_754_463_600_000_000_000
TS_END = 1_754_503_200_000_000_000
SECOND = 1_000_000_000


class FocusSharedXTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = ensure_qapp()

    def _build(self, backend: str):
        canvas = Canvas(2, 1, title="focus_shared_x", shared_x_axis=True)
        time = np.linspace(TS_START, TS_END, 200).astype(np.int64)
        for i in range(2):
            plot = PlotXY()
            sig = SignalXY(label=f"s{i}")
            sig.ts_start = TS_START
            sig.ts_end = TS_END
            sig.set_data([time, np.sin(time * 1e-18 + i)])
            plot.add_signal(sig)
            canvas.add_plot(plot, 0)
        qt_canvas = IplotQtCanvasFactory.new(backend, canvas=canvas)
        qt_canvas.set_canvas(canvas)
        qt_canvas.resize(600, 400)
        self.app.processEvents()
        return canvas, qt_canvas

    def _impl_of(self, qt_canvas, plot):
        """Current implementation plot of *plot*, re-resolved after every rebuild."""
        return qt_canvas._parser._plot_impl_plot_lut[id(plot)][0]

    def _zoom(self, qt_canvas, plot, window):
        parser = qt_canvas._parser
        impl_plot = self._impl_of(qt_canvas, plot)
        parser.set_oaw_axis_limits(impl_plot, 0, window)
        BackendParserBase._x_axis_update_callback(parser, impl_plot)
        self.app.processEvents()

    @staticmethod
    def _x_window(plot):
        return plot.axes[0].get_limits('current')

    @staticmethod
    def _y_window(plot):
        return plot.axes[1][0].get_limits('current')

    @staticmethod
    def _ts_window(plot):
        signal = next(iter(plot.signals.values()))[0]
        return signal.ts_start, signal.ts_end

    def _assert_window(self, plot, window, msg):
        begin, end = self._x_window(plot)
        self.assertAlmostEqual(begin, window[0], delta=SECOND, msg=f"{msg}: X begin")
        self.assertAlmostEqual(end, window[1], delta=SECOND, msg=f"{msg}: X end")

    def test_zoom_without_focus_moves_the_whole_group(self):
        """Baseline the focus cases are compared against."""
        window = (TS_START + 10 * SECOND, TS_END - 10 * SECOND)
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                canvas, qt_canvas = self._build(backend)
                self._zoom(qt_canvas, canvas.plots[0][0], window)

                for i, plot in enumerate(canvas.plots[0]):
                    self._assert_window(plot, window, f"plot {i}")

    def test_zoom_in_focus_moves_the_whole_group_on_unfocus(self):
        window = (TS_START + 10 * SECOND, TS_END - 10 * SECOND)
        zoom_in_focus = (TS_START + 100 * SECOND, TS_START + 200 * SECOND)
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                canvas, qt_canvas = self._build(backend)
                focused, sibling = canvas.plots[0][1], canvas.plots[0][0]
                self._zoom(qt_canvas, sibling, window)

                qt_canvas._full_screen_mode_on(self._impl_of(qt_canvas, focused))
                self.app.processEvents()
                self._zoom(qt_canvas, focused, zoom_in_focus)
                qt_canvas._full_screen_mode_off()
                self.app.processEvents()

                self._assert_window(focused, zoom_in_focus, "focused plot")
                self._assert_window(sibling, zoom_in_focus, "sibling plot")

    def test_zoom_in_focus_keeps_the_group_together_for_later_actions(self):
        """The sibling's signal ts must follow, or it drops out of the group."""
        zoom_in_focus = (TS_START + 100 * SECOND, TS_START + 200 * SECOND)
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                canvas, qt_canvas = self._build(backend)
                focused, sibling = canvas.plots[0][1], canvas.plots[0][0]

                qt_canvas._full_screen_mode_on(self._impl_of(qt_canvas, focused))
                self.app.processEvents()
                self._zoom(qt_canvas, focused, zoom_in_focus)
                qt_canvas._full_screen_mode_off()
                self.app.processEvents()

                parser = qt_canvas._parser
                self.assertEqual(self._ts_window(sibling), self._ts_window(focused))
                shared = parser._get_all_shared_axes(self._impl_of(qt_canvas, focused))
                self.assertEqual(len(shared), 2, "sibling dropped out of the shared group")


    def test_reset_after_unfocus_restores_the_whole_group(self):
        """mint#153: the reset following a zoom made in focus must reach the group."""
        zoom_in_focus = (TS_START + 100 * SECOND, TS_START + 200 * SECOND)
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                canvas, qt_canvas = self._build(backend)
                focused, sibling = canvas.plots[0][1], canvas.plots[0][0]
                drawn = self._x_window(sibling)

                qt_canvas._full_screen_mode_on(self._impl_of(qt_canvas, focused))
                self.app.processEvents()
                self._zoom(qt_canvas, focused, zoom_in_focus)
                qt_canvas._full_screen_mode_off()
                self.app.processEvents()

                qt_canvas.reset_plot_view(self._impl_of(qt_canvas, focused))
                self.app.processEvents()

                self._assert_window(focused, drawn, "focused plot")
                self._assert_window(sibling, drawn, "sibling plot")

    def test_undo_after_unfocus_keeps_the_group_together(self):
        """One undo after unfocus must not split the group."""
        window = (TS_START + 10 * SECOND, TS_END - 10 * SECOND)
        zoom_in_focus = (TS_START + 100 * SECOND, TS_START + 200 * SECOND)
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                canvas, qt_canvas = self._build(backend)
                focused, sibling = canvas.plots[0][1], canvas.plots[0][0]
                self._zoom(qt_canvas, sibling, window)

                qt_canvas._full_screen_mode_on(self._impl_of(qt_canvas, focused))
                self.app.processEvents()
                self._zoom_with_history(qt_canvas, focused, zoom_in_focus)
                qt_canvas._full_screen_mode_off()
                self.app.processEvents()

                qt_canvas._parser._hm.undo()
                self.app.processEvents()

                self.assertEqual(self._x_window(sibling), self._x_window(focused))

    def test_undo_inside_focus_leaves_the_hidden_plots_to_the_rebuild(self):
        """An undo inside focus reaches plots with no implementation plot: it must not
        raise, and their window is settled on unfocus."""
        window = (TS_START + 10 * SECOND, TS_END - 10 * SECOND)
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                canvas, qt_canvas = self._build(backend)
                focused, sibling = canvas.plots[0][1], canvas.plots[0][0]
                drawn = self._x_window(focused)
                self._zoom_with_history(qt_canvas, sibling, window)

                qt_canvas._full_screen_mode_on(self._impl_of(qt_canvas, focused))
                self.app.processEvents()
                qt_canvas._parser._hm.undo()
                self.app.processEvents()

                # Only the focused plot is built, so only it reverts here.
                self._assert_window(focused, drawn, "focused plot")

                qt_canvas._full_screen_mode_off()
                self.app.processEvents()

                self._assert_window(sibling, drawn, "sibling plot")

    def test_undo_inside_focus_restores_the_hidden_plots_y_range(self):
        """The hidden plots take the recorded Y range back too, or they return from
        focus showing the full window inside the zoomed Y range."""
        window = (TS_START + 10 * SECOND, TS_END - 10 * SECOND)
        zoomed_y = (-5.0, 5.0)
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                canvas, qt_canvas = self._build(backend)
                parser = qt_canvas._parser
                focused, sibling = canvas.plots[0][1], canvas.plots[0][0]
                drawn_y = self._y_window(sibling)
                self._zoom_with_history(qt_canvas, sibling, window)
                parser.set_oaw_axis_limits(self._impl_of(qt_canvas, sibling), 1, zoomed_y)
                self.app.processEvents()

                qt_canvas._full_screen_mode_on(self._impl_of(qt_canvas, focused))
                self.app.processEvents()
                qt_canvas._parser._hm.undo()
                self.app.processEvents()
                qt_canvas._full_screen_mode_off()
                self.app.processEvents()

                restored_y = self._y_window(sibling)
                self.assertAlmostEqual(restored_y[0], drawn_y[0], places=3)
                self.assertAlmostEqual(restored_y[1], drawn_y[1], places=3)

    def _zoom_with_history(self, qt_canvas, plot, window):
        """Zoom through the staging/commit/push flow a mouse release goes through."""
        impl_plot = self._impl_of(qt_canvas, plot)
        qt_canvas.stage_view_lim_cmd(impl_plot, name='Zoom')
        self._zoom(qt_canvas, plot, window)
        while len(qt_canvas._staging_cmds):
            qt_canvas.commit_view_lim_cmd(impl_plot)
        while len(qt_canvas._commitd_cmds):
            qt_canvas.push_view_lim_cmd()


if __name__ == '__main__':
    unittest.main()
