"""Behaviour-level tests for the Qt canvas backends.

Complements the pixel-diff rendering tests with invariants that run on
both backends but do not require visual baselines:

- stats(canvas) computes and fills the stats table.
- autoscale_all_y() adjusts Y ranges without crashing.
- set_mouse_mode() accepts every Canvas.MOUSE_MODE_* constant and updates
  the internal state.
- reset() / refresh() cycle back to a valid canvas.
- enable_crosshair + processEvents round-trips through both backends.

These exercise paths in qtMatplotlibCanvas.py / qtPyQtGraphCanvas.py that
the static rendering tests don't reach.
"""

import os
import unittest

import numpy as np
from PySide6.QtCore import Qt

from iplotlib.core.canvas import Canvas
from iplotlib.core.plot import PlotXY
from iplotlib.core.signal import SignalXY
from iplotlib.qt.gui.iplotQtCanvasFactory import IplotQtCanvasFactory
from iplotlib.qt.testing import ensure_qapp

BACKENDS = ('matplotlib', 'pyqt')

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')


def _canvas_with_noisy_signal() -> Canvas:
    """Canvas with a single plot whose Y range is non-trivial so autoscale
    / stats have something to work on."""
    core = Canvas(1, 1, title="backend_behaviour")
    x = np.linspace(0, 10, 200)
    plot = PlotXY()
    sig = SignalXY(label="noisy")
    sig.set_data([x, np.sin(x) + 0.3 * np.cos(7 * x)])
    plot.add_signal(sig)
    core.add_plot(plot, 0)
    return core


def _stacked_canvas(rows: int) -> Canvas:
    core = Canvas(rows, 1, title="stacked")
    x = np.linspace(0, 10, 200)
    for i in range(rows):
        plot = PlotXY()
        sig = SignalXY(label=f"sig{i}")
        sig.set_data([x, np.sin(x + i)])
        plot.add_signal(sig)
        core.add_plot(plot, 0)
    return core


def _multi_column_canvas() -> Canvas:
    core = Canvas(1, 2, title="multi_col")
    x = np.linspace(0, 10, 200)
    for col in range(2):
        plot = PlotXY()
        sig = SignalXY(label=f"col{col}")
        sig.set_data([x, np.sin(x + col)])
        plot.add_signal(sig)
        core.add_plot(plot, col)
    return core


def _stats_signal_names(qt_canvas) -> list:
    table = qt_canvas._stats_table.table
    return [table.item(r, 0).text() for r in range(table.rowCount()) if table.item(r, 0)]


class StatsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = ensure_qapp()

    def test_stats_does_not_raise_on_empty_canvas(self):
        """Calling stats on an empty canvas must not crash."""
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                empty = Canvas(1, 1, title="empty")
                qt_canvas = IplotQtCanvasFactory.new(backend, canvas=empty)
                qt_canvas.set_canvas(empty)
                qt_canvas.resize(400, 300)
                self.app.processEvents()

                qt_canvas.stats(empty)
                self.app.processEvents()

    def test_stats_on_canvas_with_signals_completes(self):
        """Stats with real signals fills the stats table without raising."""
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                canvas = _canvas_with_noisy_signal()
                qt_canvas = IplotQtCanvasFactory.new(backend, canvas=canvas)
                qt_canvas.set_canvas(canvas)
                qt_canvas.resize(400, 300)
                self.app.processEvents()

                qt_canvas.stats(canvas)
                self.app.processEvents()

    def test_stats_signal_name_uses_stack_only_for_single_column_canvas(self):
        """Stacked plots in a single-column canvas should label each signal
        with just the row index ("Plot 1", "Plot 2", ...) — matching the
        Stack column users see in the variables config."""
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                canvas = _stacked_canvas(rows=2)
                qt_canvas = IplotQtCanvasFactory.new(backend, canvas=canvas)
                qt_canvas.set_canvas(canvas)
                qt_canvas.resize(400, 300)
                self.app.processEvents()

                qt_canvas.stats(canvas)
                self.app.processEvents()

                names = _stats_signal_names(qt_canvas)
                self.assertEqual(len(names), 2)
                self.assertTrue(all(n.endswith(', 1') or n.endswith(', 2') for n in names),
                                f"unexpected stack suffixes: {names}")
                # No ".col" noise must leak through when there is only one column.
                self.assertFalse(any('.' in n.rsplit(', ', 1)[-1] for n in names),
                                 f"single-column canvas leaked a col suffix: {names}")

    def test_stats_signal_name_uses_row_dot_col_for_multi_column_canvas(self):
        """Side-by-side plots must keep the full row.col suffix so the user
        can tell columns apart."""
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                canvas = _multi_column_canvas()
                qt_canvas = IplotQtCanvasFactory.new(backend, canvas=canvas)
                qt_canvas.set_canvas(canvas)
                qt_canvas.resize(400, 300)
                self.app.processEvents()

                qt_canvas.stats(canvas)
                self.app.processEvents()

                names = _stats_signal_names(qt_canvas)
                suffixes = sorted(n.rsplit(', ', 1)[-1] for n in names)
                self.assertEqual(suffixes, ['1.1', '1.2'])


class StatsVerticalZoomTest(unittest.TestCase):
    """Regression: a tight vertical zoom must not collapse the sample count.

    A near-flat signal zoomed in Y below its own amplitude used to report 0
    samples, because the stats mask gated the count on the Y view. The count
    must reflect the visible time (X) window only and stay independent of the
    vertical zoom.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.app = ensure_qapp()

    @staticmethod
    def _flat_signal_canvas():
        """Single near-flat signal around a small non-zero mean (the
        GY_APS_I_MEAS / MiniMapIssue.json scenario)."""
        core = Canvas(1, 1, title="flat")
        x = np.linspace(0.0, 10.0, 200)
        y = 0.00275 + 1e-4 * np.sin(x)
        plot = PlotXY()
        sig = SignalXY(label="flat")
        sig.set_data([x, y])
        plot.add_signal(sig)
        core.add_plot(plot, 0)
        return core, sig, x

    def _set_view(self, impl_plot, backend, x, y_lo, y_hi):
        if backend == 'pyqt':
            vb = impl_plot.getViewBox()
            vb.setXRange(float(x.min()), float(x.max()), padding=0)
            vb.setYRange(y_lo, y_hi, padding=0)
        else:
            impl_plot.set_xlim(float(x.min()), float(x.max()))
            impl_plot.set_ylim(y_lo, y_hi)
        self.app.processEvents()

    def _samples(self, qt_canvas, canvas):
        qt_canvas.stats(canvas)
        self.app.processEvents()
        table = qt_canvas._stats_table.table
        self.assertEqual(table.rowCount(), 1)
        return table.item(0, 6).data(Qt.ItemDataRole.UserRole)

    def test_narrow_y_view_keeps_samples_and_is_y_independent(self):
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                canvas, sig, x = self._flat_signal_canvas()
                qt_canvas = IplotQtCanvasFactory.new(backend, canvas=canvas)
                qt_canvas.set_canvas(canvas)
                qt_canvas.resize(400, 300)
                self.app.processEvents()

                impl_plot = qt_canvas._parser._signal_impl_plot_lut.get(sig.uid)
                self.assertIsNotNone(impl_plot)

                # Y view that covers none of the samples (a deep vertical zoom
                # off the flat signal); X spans the full time range.
                self._set_view(impl_plot, backend, x, 0.0030, 0.0031)
                narrow = self._samples(qt_canvas, canvas)
                self.assertGreater(narrow, 0)

                # A wide Y view containing all the data yields the same count.
                self._set_view(impl_plot, backend, x, -1.0, 1.0)
                wide = self._samples(qt_canvas, canvas)
                self.assertEqual(narrow, wide)


class AutoscaleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = ensure_qapp()

    def test_autoscale_all_y_runs_without_error(self):
        """autoscale_all_y must traverse every PlotXY in the figure cleanly."""
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                canvas = _canvas_with_noisy_signal()
                qt_canvas = IplotQtCanvasFactory.new(backend, canvas=canvas)
                qt_canvas.set_canvas(canvas)
                qt_canvas.resize(400, 300)
                self.app.processEvents()

                qt_canvas.autoscale_all_y()
                self.app.processEvents()


class MouseModeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = ensure_qapp()

    def test_set_mouse_mode_accepts_every_mode(self):
        """All Canvas.MOUSE_MODE_* constants must be accepted by set_mouse_mode."""
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                canvas = _canvas_with_noisy_signal()
                qt_canvas = IplotQtCanvasFactory.new(backend, canvas=canvas)
                qt_canvas.set_canvas(canvas)
                qt_canvas.resize(400, 300)
                self.app.processEvents()

                for mode in (Canvas.MOUSE_MODE_SELECT, Canvas.MOUSE_MODE_CROSSHAIR,
                             Canvas.MOUSE_MODE_PAN, Canvas.MOUSE_MODE_ZOOM,
                             Canvas.MOUSE_MODE_DIST, Canvas.MOUSE_MODE_MARKER):
                    qt_canvas.set_mouse_mode(mode)
                    self.app.processEvents()
                    self.assertEqual(qt_canvas._mmode, mode)


class RefreshAndResetTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = ensure_qapp()

    def test_refresh_preserves_canvas(self):
        """refresh() redraws the same canvas without dropping it."""
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                canvas = _canvas_with_noisy_signal()
                qt_canvas = IplotQtCanvasFactory.new(backend, canvas=canvas)
                qt_canvas.set_canvas(canvas)
                qt_canvas.resize(400, 300)
                self.app.processEvents()

                qt_canvas.refresh()
                self.app.processEvents()
                self.assertIs(qt_canvas.get_canvas(), canvas)

    def test_reset_clears_canvas(self):
        """reset() removes the canvas from the widget (set_canvas(None))."""
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                canvas = _canvas_with_noisy_signal()
                qt_canvas = IplotQtCanvasFactory.new(backend, canvas=canvas)
                qt_canvas.set_canvas(canvas)
                qt_canvas.resize(400, 300)
                self.app.processEvents()

                qt_canvas.reset()
                self.app.processEvents()
                self.assertIsNone(qt_canvas.get_canvas())


class CrosshairEnabledRenderTest(unittest.TestCase):
    """Enabling the crosshair must not break the render path on either backend."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.app = ensure_qapp()

    def test_enable_crosshair_and_grab(self):
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                canvas = _canvas_with_noisy_signal()
                canvas.enable_crosshair(color="#d62728", linewidth=1,
                                        horizontal=True, vertical=True)
                qt_canvas = IplotQtCanvasFactory.new(backend, canvas=canvas)
                qt_canvas.set_canvas(canvas)
                qt_canvas.resize(400, 300)
                self.app.processEvents()

                self.assertTrue(canvas.crosshair_enabled)
                pm = qt_canvas.grab()
                self.assertFalse(pm.isNull())


class SharedXAxisTest(unittest.TestCase):
    """When ``shared_x_axis=True`` on a multi-plot canvas, zooming one plot
    must propagate the X range to every other plot. This path is glue
    between the parser and the history-command pipeline and has historically
    regressed silently (plots going out of sync on undo)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.app = ensure_qapp()

    def _build_two_stacked_plots(self, backend: str):
        canvas = Canvas(2, 1, title="shared_x", shared_x_axis=True)
        x = np.linspace(0, 10, 200)
        for i in range(2):
            plot = PlotXY()
            sig = SignalXY(label=f"s{i}")
            sig.set_data([x, np.sin(x + i)])
            plot.add_signal(sig)
            canvas.add_plot(plot, 0)
        qt_canvas = IplotQtCanvasFactory.new(backend, canvas=canvas)
        qt_canvas.set_canvas(canvas)
        qt_canvas.resize(600, 400)
        self.app.processEvents()
        return canvas, qt_canvas

    def test_shared_x_axis_flag_is_read_by_parser(self):
        """Canvas flag must propagate through set_canvas to the parser's view."""
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                canvas, qt_canvas = self._build_two_stacked_plots(backend)
                self.assertTrue(qt_canvas.get_canvas().shared_x_axis)

    def test_all_plot_limits_share_the_same_x_range_on_initial_build(self):
        """When ``shared_x_axis=True`` the parser reports identical X ranges
        for every plot on the first draw — no post-interaction required."""
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                canvas, qt_canvas = self._build_two_stacked_plots(backend)
                limits = qt_canvas._parser.get_all_plot_limits()
                self.assertEqual(len(limits), 2)
                x0 = (limits[0].axes_ranges[0].begin,
                      limits[0].axes_ranges[0].end)
                x1 = (limits[1].axes_ranges[0].begin,
                      limits[1].axes_ranges[0].end)
                self.assertAlmostEqual(x0[0], x1[0], places=3)
                self.assertAlmostEqual(x0[1], x1[1], places=3)

    def _build_two_plots_with_drifting_originals(self, backend: str):
        canvas = Canvas(2, 1, title="shared_x_drift", shared_x_axis=True)
        ts_start = 1_754_463_600_000_000_000
        ts_end = 1_754_503_200_000_000_000
        # Plot 1 fills the window; plot 2 ends 3s short, mimicking partial UDA coverage.
        for i, axis_offset_end_ns in enumerate([0, -3_000_000_000]):
            plot = PlotXY()
            sig = SignalXY(label=f"s{i}")
            sig.ts_start = ts_start
            sig.ts_end = ts_end
            time = np.linspace(ts_start, ts_end + axis_offset_end_ns, 50).astype(np.int64)
            sig.set_data([time, np.sin(time * 1e-18 + i)])
            plot.add_signal(sig)
            canvas.add_plot(plot, 0)
        qt_canvas = IplotQtCanvasFactory.new(backend, canvas=canvas)
        qt_canvas.set_canvas(canvas)
        qt_canvas.resize(600, 400)
        self.app.processEvents()
        return canvas, qt_canvas

    def test_shared_axes_groups_plots_with_same_signal_ts_despite_axis_drift(self):
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                canvas, qt_canvas = self._build_two_plots_with_drifting_originals(backend)
                parser = qt_canvas._parser
                plots = parser.get_canvas_plots()
                self.assertEqual(len(plots), 2)
                shared = parser._get_all_shared_axes(plots[0])
                self.assertEqual(len(shared), 2)

    def test_shared_axes_excludes_plots_with_different_signal_ts(self):
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                canvas = Canvas(2, 1, title="shared_x_distinct", shared_x_axis=True)
                for ts_start in (1_000_000_000_000_000_000, 2_000_000_000_000_000_000):
                    plot = PlotXY()
                    sig = SignalXY(label=f"s_{ts_start}")
                    sig.ts_start = ts_start
                    sig.ts_end = ts_start + 1_000_000_000
                    time = np.linspace(sig.ts_start, sig.ts_end, 10).astype(np.int64)
                    sig.set_data([time, np.ones_like(time, dtype=float)])
                    plot.add_signal(sig)
                    canvas.add_plot(plot, 0)
                qt_canvas = IplotQtCanvasFactory.new(backend, canvas=canvas)
                qt_canvas.set_canvas(canvas)
                qt_canvas.resize(600, 400)
                self.app.processEvents()
                plots = qt_canvas._parser.get_canvas_plots()
                shared = qt_canvas._parser._get_all_shared_axes(plots[0])
                self.assertEqual(len(shared), 1)


class CrosshairMouseMotionTest(unittest.TestCase):
    """Drive the crosshair drawing path by invoking the mouse-motion handlers.

    Using the backend-native event APIs bypasses Qt's offscreen hit-testing
    (unreliable) while still exercising every line the real mouse handler
    would execute. Matplotlib has ``FigureCanvasBase.motion_notify_event``
    which dispatches to every ``mpl_connect('motion_notify_event', ...)``
    callback; pyqtgraph exposes ``scene.sigMouseMoved`` which is what
    ``IplotCrosshairWidget.on_move`` listens on.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.app = ensure_qapp()

    def _build_with_crosshair(self, backend: str):
        canvas = _canvas_with_noisy_signal()
        canvas.enable_crosshair(color="#d62728", linewidth=1,
                                horizontal=True, vertical=True)
        qt_canvas = IplotQtCanvasFactory.new(backend, canvas=canvas)
        qt_canvas.set_canvas(canvas)
        qt_canvas.resize(600, 400)
        self.app.processEvents()
        qt_canvas.set_mouse_mode(Canvas.MOUSE_MODE_CROSSHAIR)
        self.app.processEvents()
        return canvas, qt_canvas

    def test_matplotlib_motion_notify_reaches_multicursor(self):
        from matplotlib.backend_bases import MouseEvent

        canvas, qt_canvas = self._build_with_crosshair('matplotlib')
        parser = qt_canvas._parser

        self.assertGreaterEqual(len(parser._cursors), 1,
                                "crosshair mode must install at least one cursor")

        # Build a synthetic motion event in the pixel center of the first
        # axes and dispatch it through the figure's callback registry.
        # This is the same path real mouse motion takes in matplotlib.
        fig = parser.figure
        ax = fig.axes[0]
        bbox = ax.get_position()
        fw = fig.get_figwidth() * fig.dpi
        fh = fig.get_figheight() * fig.dpi
        x_pixel = (bbox.x0 + bbox.width / 2) * fw
        y_pixel = (bbox.y0 + bbox.height / 2) * fh

        event = MouseEvent('motion_notify_event', fig.canvas, x_pixel, y_pixel)
        fig.canvas.callbacks.process('motion_notify_event', event)
        self.app.processEvents()

        # The MultiCursor flips need_clear to True after a valid motion.
        self.assertTrue(parser._cursors[0].need_clear)

    def test_pyqtgraph_sigmousemoved_reaches_crosshair(self):
        from PySide6.QtCore import QPointF

        canvas, qt_canvas = self._build_with_crosshair('pyqt')
        parser = qt_canvas._parser

        self.assertTrue(parser._cursor_active,
                        "crosshair mode must activate the pyqtgraph cursor")
        self.assertGreaterEqual(len(parser._cursors), 1)

        figure = parser.figure
        scene = figure.scene()
        # Centre of the first plot item's scene bounding rect guarantees
        # the crosshair's hit-test inside the plot succeeds.
        plot_impl = parser._plot_impl_plot_lut[id(canvas.plots[0][0])][0]
        rect = plot_impl.sceneBoundingRect()
        pos = QPointF(rect.center().x(), rect.center().y())
        scene.sigMouseMoved.emit(pos)
        self.app.processEvents()

        # After a valid motion the cursor caches the last-seen X value.
        self.assertIsNotNone(parser._cursors[0]._last_x)


class MarkerSizeSinglePointTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.app = ensure_qapp()

    def test_matplotlib_single_point_honours_configured_size(self):
        from matplotlib.lines import Line2D
        from iplotlib.impl.matplotlib.matplotlibCanvas import MatplotlibParser

        line = Line2D([0.0], [0.0])
        MatplotlibParser._update_marker_by_point_count(line, [0.0], {'markersize': 12})
        self.assertEqual(line.get_markersize(), 12)

        line_default = Line2D([0.0], [0.0])
        MatplotlibParser._update_marker_by_point_count(line_default, [0.0], {})
        self.assertEqual(line_default.get_markersize(), 5)

    def test_pyqtgraph_single_point_honours_configured_size(self):
        import pyqtgraph as pg
        from iplotlib.impl.pyqtgraph.pyQtGraphCanvas import PyQtGraphParser

        item = pg.PlotDataItem([0.0], [0.0])
        PyQtGraphParser._update_marker_by_point_count(item, [0.0], {'symbolSize': 12})
        self.assertEqual(item.opts['symbolSize'], 12)

        item_default = pg.PlotDataItem([0.0], [0.0])
        PyQtGraphParser._update_marker_by_point_count(item_default, [0.0], {})
        self.assertEqual(item_default.opts['symbolSize'], 5)


class CrosshairYLabelFormatTest(unittest.TestCase):
    """The pyqtgraph crosshair Y label must follow the left axis tick
    formatting instead of a raw ``:.6g``, which rendered scientific notation
    even when the Y ticks did not (mint #94)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.app = ensure_qapp()

    def test_y_label_follows_left_axis_tick_strings(self):
        import pyqtgraph as pg
        from iplotlib.impl.pyqtgraph.pyQtCrosshair import pyQtCrosshair

        plot = pg.PlotItem()
        axis = plot.getAxis('left')
        ymin, ymax, y = 1e7, 2e7, 1.5e7
        axis.autoSIPrefixScale = 1e-6

        got = pyQtCrosshair._format_left_axis_value(axis, y, ymin, ymax)

        self.assertNotIn('e', got.lower())
        self.assertNotEqual(got, f"{y:.6g}")

        size = axis.geometry().height() or 800
        spacing = axis.tickValues(ymin, ymax, size)[0][0]
        scale = axis.autoSIPrefixScale * axis.scale
        expected = axis.tickStrings([y], scale, spacing)[0]
        self.assertEqual(got, expected)


class CrosshairMatplotlibYLabelFormatTest(unittest.TestCase):
    """The matplotlib crosshair Y label must follow the Y tick formatter
    instead of ``format_ydata`` (``format_data_short``), which renders
    scientific notation even when the Y ticks do not (mint #94)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.app = ensure_qapp()

    def test_matplotlib_y_label_matches_tick_formatter(self):
        from matplotlib.backend_bases import MouseEvent

        core = Canvas(1, 1, title="mpl_y_fmt")
        x = np.linspace(0, 10, 200)
        plot = PlotXY()
        sig = SignalXY(label="big")
        sig.set_data([x, np.linspace(-30000.0, 30000.0, 200)])
        plot.add_signal(sig)
        core.add_plot(plot, 0)
        core.enable_crosshair(color="#d62728", linewidth=1,
                              horizontal=True, vertical=True)
        qt_canvas = IplotQtCanvasFactory.new('matplotlib', canvas=core)
        qt_canvas.set_canvas(core)
        qt_canvas.resize(600, 400)
        self.app.processEvents()
        qt_canvas.set_mouse_mode(Canvas.MOUSE_MODE_CROSSHAIR)
        self.app.processEvents()

        parser = qt_canvas._parser
        fig = parser.figure
        ax = fig.axes[0]
        bbox = ax.get_position()
        fw = fig.get_figwidth() * fig.dpi
        fh = fig.get_figheight() * fig.dpi
        x_pixel = (bbox.x0 + bbox.width / 2) * fw
        # Off-centre so the cursor Y is a mid-magnitude value where the old
        # format_ydata path produced scientific notation.
        y_pixel = (bbox.y0 + bbox.height * 0.7) * fh

        event = MouseEvent('motion_notify_event', fig.canvas, x_pixel, y_pixel)
        fig.canvas.callbacks.process('motion_notify_event', event)
        self.app.processEvents()

        arrow = parser._cursors[0].y_arrows[0]
        y = arrow.get_position()[1]
        self.assertIn('e', ax.format_ydata(y).lower())
        self.assertEqual(arrow.get_text(), ax.yaxis.get_major_formatter()(y))
        self.assertNotIn('e', arrow.get_text().lower())


if __name__ == '__main__':
    unittest.main()
