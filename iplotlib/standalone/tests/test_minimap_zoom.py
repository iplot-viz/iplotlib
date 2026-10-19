"""A left drag across the mini-map zooms the plot above to the span it covers, as one
undoable zoom that reads the data of the new range. The mini-map keeps showing the
range drawn; a click or a drag with another button changes nothing."""

import unittest
from types import SimpleNamespace

import numpy as np
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from iplotlib.core.canvas import Canvas
from iplotlib.core.plot import PlotXY
from iplotlib.core.signal import SignalXY
from iplotlib.interface.iplotSignalAdapter import AccessHelper, ParserHelper
from iplotlib.qt.gui.iplotQtCanvasFactory import IplotQtCanvasFactory
from iplotlib.qt.testing import ensure_qapp

BACKENDS = ('matplotlib', 'pyqt')
T0 = 1_788_873_880_000_000_000
HOUR = 3600 * 10**9
_SAMPLE_LIMIT = ('Number of samples in reply exceeds available limit. Reduce request interval, use decimation '
                 'or read data by chunks.')


class _DataAccess:
    """Asks for decimation, as a large archive would, so that a zoom reads the data again, and answers
    with the width of the requested range in seconds: what is drawn tells which range was read."""

    def __init__(self):
        self.reads = []

    def get_data(self, data_s_name, **kwargs):
        if kwargs['nbp'] == -1:
            return SimpleNamespace(errcode=-1, errdesc=_SAMPLE_LIMIT)
        self.reads.append((kwargs['varname'], kwargs['tsS'], kwargs['tsE']))
        x = np.linspace(kwargs['tsS'], kwargs['tsE'], 50).astype(np.int64)
        return SimpleNamespace(errcode=0, errdesc='', xdata=x, ydata=np.full(50, (kwargs['tsE'] - kwargs['tsS']) / 1e9),
                               xunit='ns', yunit='A', resolved_pulse=None)

    def get_data_source(self, name):
        return None


class _PendingFetch:
    def __init__(self, requests, on_done):
        self.requests = list(requests)
        self.on_done = on_done

    def cancel(self):
        pass


class _Pool:
    """Reads in this process the requests given to read in the background, when the test says they arrive."""

    def __init__(self):
        self.fetches = []

    def fetch(self, requests, progress=None):
        return {}

    def fetch_later(self, requests, on_done):
        self.fetches.append(_PendingFetch(requests, on_done))
        return self.fetches[-1]

    def arrive(self):
        for fetch in self.fetches:
            fetch.on_done({AccessHelper.request_key(params): AccessHelper._request_data(**dict(params))
                           for params in fetch.requests})


class MinimapZoomTest(unittest.TestCase):
    def setUp(self):
        self.app = ensure_qapp()
        ParserHelper.env.clear()
        self.addCleanup(ParserHelper.env.clear)
        for name in ('da', 'pool'):
            self.addCleanup(setattr, AccessHelper, name, getattr(AccessHelper, name))
        AccessHelper.da = self.da = _DataAccess()
        AccessHelper.pool = None

    def _show(self, backend, plot, autoscale=False):
        core = Canvas(1, 1, title="mini-map zoom", autoscale=autoscale)
        core.add_plot(plot, 0)
        qt_canvas = IplotQtCanvasFactory.new(backend, canvas=core)
        self.addCleanup(qt_canvas.deleteLater)
        self.addCleanup(qt_canvas.close)
        qt_canvas.set_canvas(core)
        qt_canvas.resize(1200, 800)
        qt_canvas.show()
        self.app.processEvents()
        qt_canvas.set_minimap(True)
        self.app.processEvents()
        parser = qt_canvas._parser
        return qt_canvas, parser, parser._plot_impl_plot_lut.get(id(plot))[0]

    def _draw(self, backend, autoscale=False):
        plot = PlotXY()
        plot.add_signal(SignalXY(name='VAR', label='VAR', data_source='uda', ts_start=T0, ts_end=T0 + HOUR))
        plot.axes[0].is_date = True
        return self._show(backend, plot, autoscale)

    @staticmethod
    def _minimap_point(qt_canvas, x):
        """The widget that takes the mouse events of the mini-map, and where in it time `x` is, half way up."""
        if hasattr(qt_canvas, '_minimap_axes'):
            ax, renderer = qt_canvas._minimap_axes, qt_canvas._minimap_renderer
            px, py = ax.transData.transform((x, np.mean(ax.get_ylim())))
            ratio = renderer.device_pixel_ratio
            return renderer, QPointF(px / ratio, renderer.height() - py / ratio)
        widget, view = qt_canvas._minimap_widget, qt_canvas._minimap_plot.getViewBox()
        scene_point = view.mapViewToScene(QPointF(x - qt_canvas._minimap_offset, np.mean(view.viewRange()[1])))
        return widget.viewport(), QPointF(widget.mapFromScene(scene_point))

    @staticmethod
    def _minimap_width(qt_canvas):
        """Width of the plotting area of the mini-map, in pixels."""
        if hasattr(qt_canvas, '_minimap_axes'):
            return qt_canvas._minimap_axes.get_window_extent().width / qt_canvas._minimap_renderer.device_pixel_ratio
        return qt_canvas._minimap_plot.getViewBox().width()

    def _send(self, widget, kind, point, button, buttons):
        QApplication.sendEvent(widget, QMouseEvent(kind, point, QPointF(widget.mapToGlobal(point.toPoint())),
                                                   button, buttons, Qt.KeyboardModifier.NoModifier))
        self.app.processEvents()

    def _drag(self, qt_canvas, begin, end, button=Qt.MouseButton.LeftButton, past=0):
        """Drag across the mini-map from time `begin` to time `end`, and then `past` pixels further right."""
        widget, start = self._minimap_point(qt_canvas, begin)
        _, stop = self._minimap_point(qt_canvas, end)
        stop += QPointF(past, 0)
        self._send(widget, QEvent.Type.MouseButtonPress, start, button, button)
        for k in range(1, 7):
            QTest.qWait(20)  # pyqtgraph drops the moves closer than 10 ms
            self._send(widget, QEvent.Type.MouseMove, start + (stop - start) * (k / 6), Qt.MouseButton.NoButton, button)
        self._send(widget, QEvent.Type.MouseButtonRelease, stop, button, Qt.MouseButton.NoButton)

    @staticmethod
    def _drawn(parser, impl):
        lines, _, _ = parser.get_impl_lines(impl)
        return [np.unique(np.asarray(parser.get_impl_data(line)[1])).tolist() for line in lines]

    @staticmethod
    def _minimap_range(qt_canvas):
        if hasattr(qt_canvas, '_minimap_axes'):
            return tuple(qt_canvas._minimap_axes.get_xlim())
        low, high = qt_canvas._minimap_plot.getViewBox().viewRange()[0]
        return low + qt_canvas._minimap_offset, high + qt_canvas._minimap_offset

    def test_a_drag_zooms_the_plot_above_and_reads_the_new_range(self):
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                qt_canvas, parser, impl = self._draw(backend)
                self.assertEqual(qt_canvas.get_canvas().get_minimap_baseline(), (T0, T0 + HOUR))
                minimap_range = self._minimap_range(qt_canvas)
                self.da.reads.clear()

                self._drag(qt_canvas, T0 + HOUR // 4, T0 + HOUR // 2)

                begin, end = parser.get_oaw_axis_limits(impl, 0)
                pixel = HOUR / self._minimap_width(qt_canvas)
                self.assertAlmostEqual(begin, T0 + HOUR // 4, delta=2 * pixel)
                self.assertAlmostEqual(end, T0 + HOUR // 2, delta=2 * pixel)
                self.assertIsInstance(begin, (int, np.integer))
                self.assertEqual(self.da.reads, [('VAR', begin, end)])
                self.assertEqual(self._drawn(parser, impl), [[(end - begin) / 1e9]])
                # The mini-map still shows the range drawn, and where the plot above is in it.
                self.assertEqual(qt_canvas.get_canvas().get_minimap_baseline(), (T0, T0 + HOUR))
                np.testing.assert_allclose(self._minimap_range(qt_canvas), minimap_range)
                self.assertEqual(parser._hm.get_next_undo_cmd_name(), 'Zoom')

                parser._hm.undo()
                self.app.processEvents()

                self.assertEqual(tuple(parser.get_oaw_axis_limits(impl, 0)), (T0, T0 + HOUR))
                self.assertFalse(parser._hm.can_undo())

    def test_a_drag_zooms_in_every_mouse_mode_and_from_the_span_shown(self):
        modes = (Canvas.MOUSE_MODE_SELECT, Canvas.MOUSE_MODE_CROSSHAIR, Canvas.MOUSE_MODE_PAN, Canvas.MOUSE_MODE_ZOOM,
                 Canvas.MOUSE_MODE_DIST, Canvas.MOUSE_MODE_MARKER, Canvas.MOUSE_MODE_RULER)
        for backend in BACKENDS:
            for mode in modes:
                with self.subTest(backend=backend, mode=mode):
                    qt_canvas, parser, impl = self._draw(backend)
                    qt_canvas.set_mouse_mode(mode)
                    self.app.processEvents()
                    pixel = HOUR / self._minimap_width(qt_canvas)

                    self._drag(qt_canvas, T0 + HOUR // 4, T0 + HOUR // 2)
                    # From inside the span the plot above shows, drawn on the mini-map, to its right.
                    self._drag(qt_canvas, T0 + HOUR * 3 // 8, T0 + HOUR * 7 // 8)

                    begin, end = parser.get_oaw_axis_limits(impl, 0)
                    self.assertAlmostEqual(begin, T0 + HOUR * 3 // 8, delta=2 * pixel)
                    self.assertAlmostEqual(end, T0 + HOUR * 7 // 8, delta=2 * pixel)
                    parser._hm.undo()
                    parser._hm.undo()
                    self.app.processEvents()
                    self.assertEqual(tuple(parser.get_oaw_axis_limits(impl, 0)), (T0, T0 + HOUR))

    def test_a_drag_past_the_edge_stops_at_the_range_drawn(self):
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                qt_canvas, parser, impl = self._draw(backend)

                self._drag(qt_canvas, T0 + HOUR // 2, T0 + HOUR, past=150)

                begin, end = parser.get_oaw_axis_limits(impl, 0)
                self.assertAlmostEqual(begin, T0 + HOUR // 2, delta=2 * HOUR / self._minimap_width(qt_canvas))
                self.assertEqual(end, T0 + HOUR)

    def test_a_click_or_a_drag_with_another_button_changes_nothing(self):
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                qt_canvas, parser, impl = self._draw(backend)
                # A selection first: the next click in the matplotlib mini-map reports an empty span.
                self._drag(qt_canvas, T0 + HOUR // 4, T0 + HOUR // 2)
                limits = tuple(parser.get_oaw_axis_limits(impl, 0))
                minimap_range = self._minimap_range(qt_canvas)
                self.da.reads.clear()

                widget, point = self._minimap_point(qt_canvas, T0 + HOUR * 3 // 4)
                self._send(widget, QEvent.Type.MouseButtonPress, point, Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton)
                self._send(widget, QEvent.Type.MouseButtonRelease, point, Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton)
                for button in (Qt.MouseButton.RightButton, Qt.MouseButton.MiddleButton):
                    self._drag(qt_canvas, T0 + HOUR // 10, T0 + HOUR * 9 // 10, button=button)
                # Less than MINIMAP_ZOOM_MIN_PX across.
                self._drag(qt_canvas, T0 + HOUR * 3 // 4, T0 + HOUR * 3 // 4 + 3 * HOUR // int(self._minimap_width(qt_canvas)))

                self.assertEqual(tuple(parser.get_oaw_axis_limits(impl, 0)), limits)
                np.testing.assert_allclose(self._minimap_range(qt_canvas), minimap_range)
                self.assertEqual(self.da.reads, [])
                parser._hm.undo()
                self.assertFalse(parser._hm.can_undo())

    def test_with_worker_processes_the_new_range_is_read_in_the_background(self):
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                qt_canvas, parser, impl = self._draw(backend)
                AccessHelper.pool = pool = _Pool()
                self.da.reads.clear()

                self._drag(qt_canvas, T0 + HOUR // 4, T0 + HOUR // 2)

                begin, end = parser.get_oaw_axis_limits(impl, 0)
                self.assertEqual(self.da.reads, [])
                self.assertEqual([(params['varname'], params['tsS'], params['tsE'])
                                  for fetch in pool.fetches for params in fetch.requests], [('VAR', begin, end)])
                # Until they arrive, the plot shows the data it has.
                self.assertEqual(self._drawn(parser, impl), [[3600.0]])

    def test_a_canvas_that_autoscales_fits_the_y_axis_to_the_data_of_the_new_range(self):
        for backend in BACKENDS:
            for workers in (False, True):
                with self.subTest(backend=backend, workers=workers):
                    qt_canvas, parser, impl = self._draw(backend, autoscale=True)
                    AccessHelper.pool = pool = _Pool() if workers else None

                    self._drag(qt_canvas, T0 + HOUR // 4, T0 + HOUR // 2)
                    if pool is not None:
                        pool.arrive()
                        self.app.processEvents()

                    begin, end = parser.get_oaw_axis_limits(impl, 0)
                    self.assertEqual(self._drawn(parser, impl), [[(end - begin) / 1e9]])
                    low, high = parser.get_oaw_axis_limits(impl, 1)
                    self.assertLess(low, (end - begin) / 1e9)
                    self.assertGreater(high, (end - begin) / 1e9)
                    self.assertGreater(low, 0)

    def test_a_relative_time_axis_keeps_fractions_of_a_second(self):
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                plot = PlotXY()
                signal = SignalXY(label='relative')
                signal.set_data([np.linspace(0.0, 10.0, 1001), np.sin(np.linspace(0, 6, 1001))])
                plot.add_signal(signal)
                qt_canvas, parser, impl = self._show(backend, plot)
                baseline = qt_canvas.get_canvas().get_minimap_baseline()
                self.assertIsNotNone(baseline)
                span = baseline[1] - baseline[0]

                self._drag(qt_canvas, baseline[0] + span * 0.25, baseline[0] + span * 0.5)

                begin, end = parser.get_oaw_axis_limits(impl, 0)
                pixel = span / self._minimap_width(qt_canvas)
                self.assertAlmostEqual(begin, baseline[0] + span * 0.25, delta=2 * pixel)
                self.assertAlmostEqual(end, baseline[0] + span * 0.5, delta=2 * pixel)
                self.assertNotEqual(begin, round(begin))


if __name__ == '__main__':
    unittest.main()
