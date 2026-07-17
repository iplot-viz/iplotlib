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
from iplotlib.core.impl_base import BackendParserBase
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

                impl_plot = qt_canvas._parser._signal_impl_plot_lut.get(
                    qt_canvas._parser.signal_lut_key(sig))
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

    def _build_time_and_xy_plots(self, backend: str, with_ech: bool = False):
        """Two time-vs-data plots plus one X-versus-Y plot whose X is data (not time),
        with shared_x_axis enabled. With ``with_ech`` a fourth plot is added whose X
        expression yields times inside the shared window (ECH-style)."""
        canvas = Canvas(4 if with_ech else 3, 1, title="shared_x_with_xy", shared_x_axis=True)
        ts_start = 1_754_463_600_000_000_000
        ts_end = 1_754_503_200_000_000_000
        time = np.linspace(ts_start, ts_end, 200).astype(np.int64)
        time_plots = []
        for i in range(2):
            plot = PlotXY()
            sig = SignalXY(label=f"t{i}")  # x_expr defaults to '${self}.time'
            # Matching ts groups the two time plots via the ts path (avoids max_diff=None fallback).
            sig.ts_start = ts_start
            sig.ts_end = ts_end
            sig.set_data([time, np.sin(np.linspace(0, 6, 200) + i)])
            plot.add_signal(sig)
            canvas.add_plot(plot, 0)
            time_plots.append(plot)
        # X-versus-Y: X is data from another signal, ranging well below the time scale.
        xy_plot = PlotXY()
        xy_sig = SignalXY(label="xy", x_expr="${T}.data")
        xy_sig.processing_enabled = False  # keep the directly-set data (no alias to evaluate)
        xy_sig.set_data([np.linspace(5, 295, 150), np.linspace(0, 50, 150)])
        xy_plot.add_signal(xy_sig)
        canvas.add_plot(xy_plot, 0)

        ech_plot = None
        if with_ech:
            # X expression whose samples are times: first sample inside the shared window.
            ech_plot = PlotXY()
            ech_sig = SignalXY(label="ech", x_expr="${T}.time")
            ech_sig.processing_enabled = False
            ech_x = np.linspace(ts_start + 600_000_000_000, ts_end - 600_000_000_000, 150).astype(np.int64)
            ech_sig.set_data([ech_x, np.linspace(0, 50, 150)])
            ech_plot.add_signal(ech_sig)
            canvas.add_plot(ech_plot, 0)

        qt_canvas = IplotQtCanvasFactory.new(backend, canvas=canvas)
        qt_canvas.set_canvas(canvas)
        qt_canvas.resize(600, 400)
        self.app.processEvents()
        return canvas, qt_canvas, time_plots, xy_plot, ech_plot

    def test_non_time_xy_plot_keeps_own_x_range_under_shared_time(self):
        """An X-versus-Y plot must keep its data-derived X range (~5..295) rather than be
        forced onto the shared time range (~1e6) when shared_x_axis is enabled."""
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                _, qt_canvas, _, xy_plot, _ = self._build_time_and_xy_plots(backend)
                limits = qt_canvas._parser.get_all_plot_limits()
                xy_limits = next(lim for lim in limits if lim.plot_ref() is xy_plot)
                x_begin = xy_limits.axes_ranges[0].begin
                x_end = xy_limits.axes_ranges[0].end
                # The time plots span epoch timestamps; the XY plot's X must stay in
                # temperature territory.
                self.assertLess(x_begin, 10_000.0)
                self.assertLess(x_end, 10_000.0)

    def test_non_time_xy_plot_joins_group_as_reprocess_follower(self):
        """The X-versus-Y plot joins the group led by a time plot (it follows the
        shared-time zoom by reprocessing, mint#120), but zooming on the XY plot
        itself must not drive the group: it only syncs its own stacked sub-plots."""
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                _, qt_canvas, _, xy_plot, _ = self._build_time_and_xy_plots(backend)
                parser = qt_canvas._parser

                def logical(impl_plot):
                    return parser._impl_plot_cache_table.get_cache_item(impl_plot).plot()

                plots = parser.get_canvas_plots()
                xy_impl = next(p for p in plots if logical(p) is xy_plot)
                time_impl = next(p for p in plots if logical(p) is not xy_plot)

                # XY plot syncs only its own stacked sub-plots (behaves as shared_x_axis off).
                self.assertEqual(len(parser._get_all_shared_axes(xy_impl)),
                                 len(parser._plot_impl_plot_lut.get(id(xy_plot))))
                # The group led by a time plot contains the two time plots and the
                # X-versus-Y plot, which follows by reprocessing over the time window.
                shared_logical = [logical(p) for p in parser._get_all_shared_axes(time_impl)]
                self.assertEqual(len(shared_logical), 3)
                self.assertTrue(any(p is xy_plot for p in shared_logical))

    def test_ech_time_expression_plot_follows_shared_group(self):
        """A plot whose X expression yields times with its first sample inside the
        shared window joins the group led by a time plot, so it follows the
        shared-time zoom. The plain X-versus-Y plot stays out."""
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                _, qt_canvas, _, _, ech_plot = self._build_time_and_xy_plots(backend, with_ech=True)
                parser = qt_canvas._parser

                def logical(impl_plot):
                    return parser._impl_plot_cache_table.get_cache_item(impl_plot).plot()

                plots = parser.get_canvas_plots()
                time_impl = next(p for p in plots if parser._plot_x_is_time(logical(p)))
                shared_logical = [logical(p) for p in parser._get_all_shared_axes(time_impl)]
                self.assertTrue(any(p is ech_plot for p in shared_logical))
                # Two time plots + the ECH plot + the data-valued XY plot, which
                # follows the zoom by reprocessing instead of sharing axis limits.
                self.assertEqual(len(shared_logical), 4)

    def test_data_expression_plot_never_takes_the_time_window_on_its_axis(self):
        """A '${T}.data' plot may follow the shared-time zoom, but only by
        reprocessing: its X axis must never be set to the time window itself, even
        when its X samples numerically fall inside the shared window (GUI smoke test
        found the first-point check alone stretched the X-versus-Y plot's axis)."""
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                canvas = Canvas(2, 1, title="shared_x_data_expr", shared_x_axis=True)
                ts_start = 1_754_463_600_000_000_000
                ts_end = 1_754_503_200_000_000_000
                time = np.linspace(ts_start, ts_end, 100).astype(np.int64)
                time_plot = PlotXY()
                sig = SignalXY(label="t")
                sig.ts_start = ts_start
                sig.ts_end = ts_end
                sig.set_data([time, np.sin(np.linspace(0, 6, 100))])
                time_plot.add_signal(sig)
                canvas.add_plot(time_plot, 0)
                xy_plot = PlotXY()
                xy_sig = SignalXY(label="xy", x_expr="${T}.data")
                xy_sig.processing_enabled = False
                # X samples in temperature territory, far below the time scale.
                xy_x = np.linspace(5, 295, 100)
                xy_sig.set_data([xy_x, np.linspace(0, 50, 100)])
                xy_plot.add_signal(xy_sig)
                canvas.add_plot(xy_plot, 0)
                qt_canvas = IplotQtCanvasFactory.new(backend, canvas=canvas)
                qt_canvas.set_canvas(canvas)
                qt_canvas.resize(600, 400)
                self.app.processEvents()
                parser = qt_canvas._parser

                def logical(impl_plot):
                    return parser._impl_plot_cache_table.get_cache_item(impl_plot).plot()

                plots = parser.get_canvas_plots()
                time_impl = next(p for p in plots if logical(p) is time_plot)
                xy_impl = next(p for p in plots if logical(p) is xy_plot)

                # Simulate a zoom on the time plot and run the propagation.
                new_start = ts_start + 4_000_000_000_000
                new_end = ts_end - 4_000_000_000_000
                parser.set_oaw_axis_limits(time_impl, 0, (new_start, new_end))
                BackendParserBase._x_axis_update_callback(parser, time_impl)
                self.app.processEvents()

                # The XY plot's axis must stay in data territory, never the epoch window.
                x_begin, x_end = parser.get_oaw_axis_limits(xy_impl, 0)
                self.assertLess(x_begin, 10_000.0)
                self.assertLess(x_end, 10_000.0)

    def test_shared_time_zoom_reprocesses_xy_plot_over_time_window(self):
        """Zooming a time plot propagates the *time window* to the X-versus-Y plot's
        signals (so their X column is refetched/reprocessed over it) and rescales the
        XY axis to the reprocessed data (mint#120)."""
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                _, qt_canvas, time_plots, xy_plot, _ = self._build_time_and_xy_plots(backend)
                parser = qt_canvas._parser

                def logical(impl_plot):
                    return parser._impl_plot_cache_table.get_cache_item(impl_plot).plot()

                plots = parser.get_canvas_plots()
                time_impl = next(p for p in plots if logical(p) is time_plots[0])
                xy_impl = next(p for p in plots if logical(p) is xy_plot)
                xy_sig = xy_plot.signals[1][0]

                ts_start = 1_754_463_600_000_000_000
                ts_end = 1_754_503_200_000_000_000
                new_start = ts_start + 4_000_000_000_000
                new_end = ts_end - 4_000_000_000_000

                parser.set_oaw_axis_limits(time_impl, 0, (new_start, new_end))
                BackendParserBase._x_axis_update_callback(parser, time_impl)
                self.app.processEvents()

                # The time window was propagated to the XY signal's data request...
                self.assertAlmostEqual(xy_sig.ts_start, new_start, delta=1e9)
                self.assertAlmostEqual(xy_sig.ts_end, new_end, delta=1e9)
                # ...and its axis follows the (re)processed X data, not the window.
                x_begin, x_end = parser.get_oaw_axis_limits(xy_impl, 0)
                self.assertLess(x_begin, 10_000.0)
                self.assertLess(x_end, 10_000.0)
                # The time plots did take the window on their axes.
                t_begin, t_end = parser.get_oaw_axis_limits(time_impl, 0)
                self.assertAlmostEqual(t_begin, new_start, delta=1e9)
                self.assertAlmostEqual(t_end, new_end, delta=1e9)

    def _build_test34_canvas(self, backend, tag=""):
        """Canvas mirroring the Test34 MINT workspace: two time plots displaying
        alias signals A and B, plus an expression-only X-versus-Y plot (empty
        name, x_expr='${A}.data', y_expr='${B}.data'). A's data are large
        relative-time counters (~1.7e15, DI_RELTIME) so the axis-offset path
        (create_offset) is exercised."""
        ts_start = 1_754_463_600_000_000_000
        ts_end = 1_754_503_200_000_000_000
        alias_a = f"m120_{backend}{tag}_a"
        alias_b = f"m120_{backend}{tag}_b"
        canvas = Canvas(3, 1, title="shared_x_expr_xy", shared_x_axis=True)
        time = np.linspace(ts_start, ts_end, 100).astype(np.int64)
        reltime = np.linspace(1_781_184_330_000_126, 1_781_184_935_952_126, 100)
        current = np.linspace(0.0026, 0.0029, 100)
        dep_sigs = []
        for alias, ydata in ((alias_a, reltime), (alias_b, current)):
            plot = PlotXY()
            sig = SignalXY(label=alias, alias=alias)
            sig.data_access_enabled = False
            sig.ts_start = ts_start
            sig.ts_end = ts_end
            sig.set_data([time, ydata])
            plot.add_signal(sig)
            canvas.add_plot(plot, 0)
            dep_sigs.append(sig)
        tot_plot = PlotXY()
        tot_sig = SignalXY(label="Tot", name="",
                           x_expr="${%s}.data" % alias_a,
                           y_expr="${%s}.data" % alias_b)
        tot_sig.ts_start = ts_start
        tot_sig.ts_end = ts_end
        tot_plot.add_signal(tot_sig)
        canvas.add_plot(tot_plot, 0)

        qt_canvas = IplotQtCanvasFactory.new(backend, canvas=canvas)
        qt_canvas.set_canvas(canvas)
        qt_canvas.resize(600, 400)
        self.app.processEvents()
        return qt_canvas, canvas, dep_sigs, tot_sig, tot_plot, (ts_start, ts_end)

    @staticmethod
    def _line_impl_xdata(backend, parser, signal):
        """X coordinates of the drawn line, in implementation (offset) space."""
        shape = parser._signal_impl_shape_lut.get(id(signal))
        line = shape[0] if isinstance(shape, (list, tuple)) else shape
        if backend == 'matplotlib':
            return np.asarray(line.get_xdata(), dtype=float)
        return np.asarray(line.getData()[0], dtype=float)

    def test_expression_xy_plot_reprocesses_from_dependencies(self):
        """A shared-time zoom must re-evaluate the expression plot's X/Y over the
        dependencies' refreshed buffers, rescale its axis to the re-derived data,
        and keep the drawn line inside the view (drawn coordinates and axis limits
        must share the same offset frame, mint#120)."""
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                qt_canvas, _, dep_sigs, tot_sig, tot_plot, (ts_start, ts_end) = \
                    self._build_test34_canvas(backend)
                parser = qt_canvas._parser

                # Initial processing derived Tot's X from A's data.
                self.assertAlmostEqual(float(np.asarray(tot_sig.x_data, dtype=float).min()),
                                       1_781_184_330_000_126, delta=1e6)

                def logical(impl_plot):
                    return parser._impl_plot_cache_table.get_cache_item(impl_plot).plot()

                plots = parser.get_canvas_plots()
                time_impl = next(p for p in plots
                                 if logical(p).signals[1][0] is dep_sigs[0])
                tot_impl = next(p for p in plots if logical(p) is tot_plot)
                ci = parser._impl_plot_cache_table.get_cache_item(tot_impl)
                offset_before = ci.offsets[0]

                new_start = ts_start + 4_000_000_000_000
                new_end = ts_end - 4_000_000_000_000
                # Emulate what a refetch over the new window would give the
                # dependencies (data access is stubbed out in this test): samples
                # restricted to the window, like a real UDA fetch.
                narrowed = np.linspace(new_start, new_end, 25).astype(np.int64)
                new_reltime = np.linspace(1_781_184_500_000_126, 1_781_184_700_000_126, 25)
                dep_sigs[0].set_data([narrowed, new_reltime])
                dep_sigs[1].set_data([narrowed, np.linspace(0.0027, 0.0028, 25)])

                parser.set_oaw_axis_limits(time_impl, 0, (new_start, new_end))
                BackendParserBase._x_axis_update_callback(parser, time_impl)
                self.app.processEvents()

                # Tot was reprocessed and the ts window propagated.
                np.testing.assert_allclose(np.asarray(tot_sig.x_data), new_reltime)
                self.assertAlmostEqual(tot_sig.ts_start, new_start, delta=1e9)
                self.assertAlmostEqual(tot_sig.ts_end, new_end, delta=1e9)
                # The axis follows the re-derived data range (offset-aware).
                x_begin, x_end = parser.get_oaw_axis_limits(tot_impl, 0)
                self.assertAlmostEqual(x_begin, new_reltime[0], delta=1e6)
                self.assertAlmostEqual(x_end, new_reltime[-1], delta=1e6)
                # The axis offset must be preserved across the zoom: DI_RELTIME
                # values are epoch timestamps in microseconds (~1.7e15), so the
                # ticks show implementation coordinates (value - offset).
                # Recomputing the offset from the zoomed range would re-center
                # the displayed numbers on the window midpoint (+/- half-window
                # around zero) instead of keeping them comparable with the
                # initial view (mint#120, 'the third plot X centered on zero').
                self.assertEqual(ci.offsets[0], offset_before)
                impl_begin, impl_end = parser.get_impl_x_axis_limits(tot_impl)
                self.assertAlmostEqual(impl_begin, new_reltime[0] - offset_before, delta=1e6)
                self.assertAlmostEqual(impl_end, new_reltime[-1] - offset_before, delta=1e6)
                self.assertNotAlmostEqual(float(impl_begin) + float(impl_end), 0.0,
                                          delta=1e6)
                # The drawn line and the view live in the same offset frame: the
                # line's implementation coordinates fall inside the visible window.
                line_x = self._line_impl_xdata(backend, parser, tot_sig)
                self.assertGreaterEqual(float(line_x.min()), impl_begin - 1e6)
                self.assertLessEqual(float(line_x.max()), impl_end + 1e6)

    def test_undo_restores_all_plots_of_the_shared_group(self):
        """Undoing a shared-time zoom must restore every plot of the group, not
        only the plot the zoom was made on: the time plots take back the old
        window and the X-versus-Y follower is reprocessed over it (mint#120)."""
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                qt_canvas, _, dep_sigs, tot_sig, tot_plot, (ts_start, ts_end) = \
                    self._build_test34_canvas(backend, tag="_undo")
                parser = qt_canvas._parser
                qt_canvas._mmode = 'MMZoom'

                def logical(impl_plot):
                    return parser._impl_plot_cache_table.get_cache_item(impl_plot).plot()

                plots = parser.get_canvas_plots()
                time_impl = next(p for p in plots
                                 if logical(p).signals[1][0] is dep_sigs[0])
                other_impl = next(p for p in plots
                                  if logical(p).signals[1][0] is dep_sigs[1])

                new_start = ts_start + 4_000_000_000_000
                new_end = ts_end - 4_000_000_000_000

                # Zoom the first time plot through the command pipeline.
                qt_canvas.stage_view_lim_cmd(time_impl)
                parser.set_oaw_axis_limits(time_impl, 0, (new_start, new_end))
                BackendParserBase._x_axis_update_callback(parser, time_impl)
                self.app.processEvents()
                qt_canvas.commit_view_lim_cmd(time_impl)
                qt_canvas.push_view_lim_cmd()

                # Sanity: the whole group is zoomed.
                o_begin, o_end = parser.get_oaw_axis_limits(other_impl, 0)
                self.assertAlmostEqual(o_begin, new_start, delta=1e9)
                self.assertAlmostEqual(tot_sig.ts_start, new_start, delta=1e9)

                parser._hm.undo()
                self.app.processEvents()

                # The other time plot is restored...
                o_begin, o_end = parser.get_oaw_axis_limits(other_impl, 0)
                self.assertAlmostEqual(o_begin, ts_start, delta=1e9)
                self.assertAlmostEqual(o_end, ts_end, delta=1e9)
                # ...and the X-versus-Y follower was reprocessed over the old window.
                self.assertAlmostEqual(tot_sig.ts_start, ts_start, delta=1e9)
                self.assertAlmostEqual(tot_sig.ts_end, ts_end, delta=1e9)

    def test_deeper_zoom_follows_when_dependencies_are_not_refetched(self):
        """Second, deeper zoom where the dependencies' buffers already cover the
        window (raw data below the downsampling threshold is not refetched): the
        X-versus-Y axis must follow the window-restricted data, not the whole
        buffer (mint#120, 'x axis not refreshed when zooming more than once')."""
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                qt_canvas, _, dep_sigs, tot_sig, tot_plot, (ts_start, ts_end) = \
                    self._build_test34_canvas(backend, tag="_deep")
                parser = qt_canvas._parser

                def logical(impl_plot):
                    return parser._impl_plot_cache_table.get_cache_item(impl_plot).plot()

                plots = parser.get_canvas_plots()
                time_impl = next(p for p in plots
                                 if logical(p).signals[1][0] is dep_sigs[0])
                tot_impl = next(p for p in plots if logical(p) is tot_plot)

                span = ts_end - ts_start
                time = np.linspace(ts_start, ts_end, 100).astype(np.int64)
                reltime = np.linspace(1_781_184_330_000_126, 1_781_184_935_952_126, 100)

                def zoom(f0, f1, reslice):
                    ns, ne = ts_start + int(f0 * span), ts_start + int(f1 * span)
                    if reslice:  # emulate a refetch over the window
                        m = (time >= ns) & (time <= ne)
                        dep_sigs[0].set_data([time[m], reltime[m]])
                        dep_sigs[1].set_data([time[m], np.linspace(0.0027, 0.0028, int(m.sum()))])
                    parser.set_oaw_axis_limits(time_impl, 0, (ns, ne))
                    BackendParserBase._x_axis_update_callback(parser, time_impl)
                    self.app.processEvents()
                    return ns, ne

                # First zoom refetches the dependencies over [10%, 50%].
                zoom(0.10, 0.50, reslice=True)
                # Deeper zoom [20%, 30%]: buffers already cover it, no refetch.
                zoom(0.20, 0.30, reslice=False)

                lo = 1_781_184_330_000_126 + 0.20 * (1_781_184_935_952_126 - 1_781_184_330_000_126)
                hi = 1_781_184_330_000_126 + 0.30 * (1_781_184_935_952_126 - 1_781_184_330_000_126)
                # The reprocessed X data is restricted to the deeper window...
                x = np.asarray(tot_sig.x_data, dtype=float)
                self.assertGreaterEqual(x.min(), lo - 1e7)
                self.assertLessEqual(x.max(), hi + 1e7)
                # ...and the axis follows it instead of the whole superset buffer.
                x_begin, x_end = parser.get_oaw_axis_limits(tot_impl, 0)
                self.assertAlmostEqual(x_begin, x.min(), delta=1e6)
                self.assertAlmostEqual(x_end, x.max(), delta=1e6)
                self.assertLess(x_end - x_begin, 0.15 * (1_781_184_935_952_126
                                                         - 1_781_184_330_000_126))

    def test_reverse_zoom_on_xy_plot_drives_the_group_when_invertible(self):
        """Zooming ON the X-versus-Y plot with a strictly increasing X derived
        from data maps the selected X range back to a time window and drives the
        shared group: the time plots take the mapped window and the X-versus-Y
        plot itself is reprocessed over it (mint#120 reverse direction)."""
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                qt_canvas, _, dep_sigs, tot_sig, tot_plot, (ts_start, ts_end) = \
                    self._build_test34_canvas(backend, tag="_rev")
                parser = qt_canvas._parser

                def logical(impl_plot):
                    return parser._impl_plot_cache_table.get_cache_item(impl_plot).plot()

                plots = parser.get_canvas_plots()
                time_impl = next(p for p in plots
                                 if logical(p).signals[1][0] is dep_sigs[0])
                tot_impl = next(p for p in plots if logical(p) is tot_plot)

                # Select the middle fifth of the (strictly increasing) X column.
                x = np.asarray(tot_sig.x_data, dtype=float)
                x0 = float(np.quantile(x, 0.40))
                x1 = float(np.quantile(x, 0.60))
                parser.set_oaw_axis_limits(tot_impl, 0, (x0, x1))
                BackendParserBase._x_axis_update_callback(parser, tot_impl)
                self.app.processEvents()

                span = ts_end - ts_start
                t_begin, t_end = parser.get_oaw_axis_limits(time_impl, 0)
                # The time plot took (approximately) the mapped window.
                self.assertAlmostEqual(t_begin, ts_start + 0.40 * span, delta=0.02 * span)
                self.assertAlmostEqual(t_end, ts_start + 0.60 * span, delta=0.02 * span)
                # The X-versus-Y plot itself was reprocessed over it.
                self.assertAlmostEqual(tot_sig.ts_start, ts_start + 0.40 * span,
                                       delta=0.02 * span)
                self.assertAlmostEqual(tot_sig.ts_end, ts_start + 0.60 * span,
                                       delta=0.02 * span)

                # Zooming far out on the XY plot: the edge-extrapolated window
                # must be clamped to the originally requested time range so the
                # propagation never requests data beyond it (UDA reply limits).
                x_span = float(x.max() - x.min())
                parser.set_oaw_axis_limits(
                    tot_impl, 0, (float(x.min()) - 10 * x_span,
                                  float(x.max()) + 10 * x_span))
                BackendParserBase._x_axis_update_callback(parser, tot_impl)
                self.app.processEvents()
                t_begin, t_end = parser.get_oaw_axis_limits(time_impl, 0)
                self.assertGreaterEqual(t_begin, ts_start - 1e9)
                self.assertLessEqual(t_end, ts_end + 1e9)

    def test_reverse_zoom_stays_local_when_x_is_not_invertible(self):
        """Zooming ON an X-versus-Y plot whose X column is not a bijection (here
        a sine of time) must stay local: the time plots keep their window."""
        ts_start = 1_754_463_600_000_000_000
        ts_end = 1_754_503_200_000_000_000
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                alias = f"m120_{backend}_nm"
                canvas = Canvas(2, 1, title="reverse_nonmono", shared_x_axis=True)
                time = np.linspace(ts_start, ts_end, 200).astype(np.int64)
                time_plot = PlotXY()
                sig = SignalXY(label=alias, alias=alias)
                sig.data_access_enabled = False
                sig.ts_start = ts_start
                sig.ts_end = ts_end
                sig.set_data([time, np.sin(np.linspace(0, 12, 200))])  # non-monotonic
                time_plot.add_signal(sig)
                canvas.add_plot(time_plot, 0)
                xy_plot = PlotXY()
                xy_sig = SignalXY(label="Tot", name="",
                                  x_expr="${%s}.data" % alias,
                                  y_expr="${%s}.data" % alias)
                xy_sig.ts_start = ts_start
                xy_sig.ts_end = ts_end
                xy_plot.add_signal(xy_sig)
                canvas.add_plot(xy_plot, 0)
                qt_canvas = IplotQtCanvasFactory.new(backend, canvas=canvas)
                qt_canvas.set_canvas(canvas)
                qt_canvas.resize(600, 400)
                self.app.processEvents()
                parser = qt_canvas._parser

                def logical(impl_plot):
                    return parser._impl_plot_cache_table.get_cache_item(impl_plot).plot()

                plots = parser.get_canvas_plots()
                time_impl = next(p for p in plots if logical(p) is time_plot)
                xy_impl = next(p for p in plots if logical(p) is xy_plot)

                parser.set_oaw_axis_limits(xy_impl, 0, (-0.5, 0.5))
                BackendParserBase._x_axis_update_callback(parser, xy_impl)
                self.app.processEvents()

                # Time plot untouched...
                t_begin, t_end = parser.get_oaw_axis_limits(time_impl, 0)
                self.assertAlmostEqual(t_begin, ts_start, delta=1e9)
                self.assertAlmostEqual(t_end, ts_end, delta=1e9)
                # ...and the zoom stayed local on the X-versus-Y plot: its axis
                # holds the selected X range, and no time window was derived
                # (the legacy local path stores the raw X values in ts, which is
                # pre-existing behaviour outside the scope of the reverse zoom).
                x_begin, x_end = parser.get_oaw_axis_limits(xy_impl, 0)
                self.assertAlmostEqual(x_begin, -0.5, delta=0.01)
                self.assertAlmostEqual(x_end, 0.5, delta=0.01)
                # No time window was derived: ts is not a strict sub-interval
                # of the originally requested range.
                self.assertFalse(xy_sig.ts_start > ts_start
                                 and xy_sig.ts_end < ts_end)

    def test_xy_plot_with_different_ts_stays_out_of_shared_group(self):
        """An X-versus-Y plot requested over a *different* time range than the base
        plot does not share its time base and must stay out of the group."""
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                canvas = Canvas(2, 1, title="shared_x_xy_other_ts", shared_x_axis=True)
                ts_start = 1_754_463_600_000_000_000
                ts_end = 1_754_503_200_000_000_000
                time = np.linspace(ts_start, ts_end, 100).astype(np.int64)
                time_plot = PlotXY()
                sig = SignalXY(label="t")
                sig.ts_start = ts_start
                sig.ts_end = ts_end
                sig.set_data([time, np.sin(np.linspace(0, 6, 100))])
                time_plot.add_signal(sig)
                canvas.add_plot(time_plot, 0)
                xy_plot = PlotXY()
                xy_sig = SignalXY(label="xy", x_expr="${T}.data")
                xy_sig.processing_enabled = False
                # Requested over a disjoint time range: no common time base.
                xy_sig.ts_start = ts_start - 500_000_000_000_000
                xy_sig.ts_end = ts_start - 400_000_000_000_000
                xy_sig.set_data([np.linspace(5, 295, 100), np.linspace(0, 50, 100)])
                xy_plot.add_signal(xy_sig)
                canvas.add_plot(xy_plot, 0)
                qt_canvas = IplotQtCanvasFactory.new(backend, canvas=canvas)
                qt_canvas.set_canvas(canvas)
                qt_canvas.resize(600, 400)
                self.app.processEvents()
                parser = qt_canvas._parser

                def logical(impl_plot):
                    return parser._impl_plot_cache_table.get_cache_item(impl_plot).plot()

                plots = parser.get_canvas_plots()
                time_impl = next(p for p in plots if logical(p) is time_plot)
                self.assertEqual(len(parser._get_all_shared_axes(time_impl)), 1)

    def test_zoom_on_ech_plot_stays_local(self):
        """Zooming on the ECH-style plot must not drive the shared group: it only
        syncs its own stacked sub-plots."""
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                _, qt_canvas, _, _, ech_plot = self._build_time_and_xy_plots(backend, with_ech=True)
                parser = qt_canvas._parser

                def logical(impl_plot):
                    return parser._impl_plot_cache_table.get_cache_item(impl_plot).plot()

                plots = parser.get_canvas_plots()
                ech_impl = next(p for p in plots if logical(p) is ech_plot)
                self.assertEqual(len(parser._get_all_shared_axes(ech_impl)),
                                 len(parser._plot_impl_plot_lut.get(id(ech_plot))))


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
