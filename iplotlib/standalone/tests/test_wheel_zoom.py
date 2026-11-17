"""The wheel zooms the time axis of the plot under the mouse, around the mouse, and of the plots that share it: in
as it turns away from the user, out as it turns back. A turn of the wheel is one zoom to undo, and the data of the
new range are read as for any zoom. While streaming it zooms nothing (mint#211)."""

import unittest
from types import SimpleNamespace

import numpy as np
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication

from iplotlib.core.axis import LinearAxis
from iplotlib.core.canvas import Canvas
from iplotlib.core.plot import PlotXY
from iplotlib.core.signal import SignalXY
from iplotlib.interface.iplotSignalAdapter import AccessHelper, ParserHelper
from iplotlib.qt.gui.iplotQtCanvasFactory import IplotQtCanvasFactory
from iplotlib.qt.testing import ensure_qapp

BACKENDS = ('matplotlib', 'pyqt')
T0 = 1_788_873_880_000_000_000
HOUR = 3600 * 10**9
NOTCH = 120
IN = 1.02 ** (-NOTCH / 8)  # what a notch away from the user leaves of the time axis
PIXEL = HOUR / 1000  # about what a pixel of the plot shows: the mouse is where a pixel is
_SAMPLE_LIMIT = ('Number of samples in reply exceeds available limit. Reduce request interval, use decimation '
                 'or read data by chunks.')


class _DataAccess:
    """Asks for decimation, as a large archive would, so that a zoom reads the data again."""

    def __init__(self):
        self.reads = []

    def get_data(self, data_s_name, **kwargs):
        if kwargs['nbp'] == -1:
            return SimpleNamespace(errcode=-1, errdesc=_SAMPLE_LIMIT)
        self.reads.append((kwargs['varname'], kwargs['tsS'], kwargs['tsE']))
        x = np.linspace(kwargs['tsS'], kwargs['tsE'], 50).astype(np.int64)
        return SimpleNamespace(errcode=0, errdesc='', xdata=x, ydata=np.sin(np.arange(50.0)), xunit='ns', yunit='A',
                               resolved_pulse=None)

    def get_data_source(self, name):
        return None


class WheelZoomTest(unittest.TestCase):
    def setUp(self):
        self.app = ensure_qapp()
        ParserHelper.env.clear()
        self.addCleanup(ParserHelper.env.clear)
        for name in ('da', 'pool'):
            self.addCleanup(setattr, AccessHelper, name, getattr(AccessHelper, name))
        AccessHelper.da = self.da = _DataAccess()
        AccessHelper.pool = None

    def _show(self, backend, plots=1):
        """A canvas of `plots` plots, one under the other, sharing their time axis, over an hour."""
        core = Canvas(plots, 1, title="wheel zoom", shared_x_axis=True)
        for k in range(plots):
            plot = PlotXY(axes=[LinearAxis(), [LinearAxis()]])
            plot.add_signal(SignalXY(name=f'VAR{k}', label=f'VAR{k}', data_source='uda', ts_start=T0,
                                     ts_end=T0 + HOUR))
            plot.axes[0].is_date = True
            core.add_plot(plot, 0)
        qt_canvas = IplotQtCanvasFactory.new(backend, canvas=core)
        self.addCleanup(qt_canvas.deleteLater)
        self.addCleanup(qt_canvas.close)
        qt_canvas.set_canvas(core)
        qt_canvas.resize(1200, 800)
        qt_canvas.show()
        self.app.processEvents()
        parser = qt_canvas._parser
        return qt_canvas, parser, [parser._plot_impl_plot_lut.get(id(plot))[0] for plot in core.plots[0]]

    @staticmethod
    def _times(parser, impl_plot):
        """The time range a plot shows, in ns: a zoom moves the offset its view counts from."""
        return np.array([parser.transform_value(impl_plot, 0, value) for value in
                         parser.get_impl_x_axis_limits(impl_plot)], dtype=float)

    @staticmethod
    def _wheel(qt_canvas, impl_plot, x, angle):
        """Turn the wheel by `angle` with the mouse at view time `x` of a plot, half way up, as Qt gives it."""
        if hasattr(impl_plot, 'transData'):
            widget = qt_canvas._mpl_renderer
            px, py = impl_plot.transData.transform((x, np.mean(impl_plot.get_ylim())))
            ratio = widget.device_pixel_ratio
            at = QPointF(px / ratio, widget.height() - py / ratio)
        else:
            view = impl_plot.getViewBox()
            figure = qt_canvas._parser.figure
            widget = figure.viewport()
            at = QPointF(figure.mapFromScene(view.mapViewToScene(QPointF(x, np.mean(view.viewRange()[1])))))
        event = QWheelEvent(at, QPointF(widget.mapToGlobal(at.toPoint())), QPoint(), QPoint(0, angle),
                            Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase,
                            False)
        QApplication.sendEvent(widget, event)
        QApplication.processEvents()

    def test_a_notch_zooms_in_around_the_mouse_and_turning_back_zooms_out(self):
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                qt_canvas, parser, (impl_plot,) = self._show(backend)
                lo, hi = self._times(parser, impl_plot)
                view_lo, view_hi = parser.get_impl_x_axis_limits(impl_plot)
                self._wheel(qt_canvas, impl_plot, view_lo + (view_hi - view_lo) / 4, NOTCH)
                at = lo + (hi - lo) / 4
                np.testing.assert_allclose(self._times(parser, impl_plot), (at - (at - lo) * IN, at + (hi - at) * IN),
                                           rtol=0, atol=PIXEL)
                view_lo, view_hi = parser.get_impl_x_axis_limits(impl_plot)
                self._wheel(qt_canvas, impl_plot, view_lo + (view_hi - view_lo) / 4, -NOTCH)
                np.testing.assert_allclose(self._times(parser, impl_plot), (lo, hi), rtol=0, atol=PIXEL)

    def test_a_turn_of_the_wheel_is_one_zoom_to_undo(self):
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                qt_canvas, parser, (impl_plot,) = self._show(backend)
                times = self._times(parser, impl_plot)
                for _ in range(3):
                    self._wheel(qt_canvas, impl_plot, sum(parser.get_impl_x_axis_limits(impl_plot)) / 2, NOTCH)
                self.assertEqual(parser._hm.get_next_undo_cmd_name(), 'Zoom')
                parser.undo()
                self.app.processEvents()
                np.testing.assert_allclose(self._times(parser, impl_plot), times, rtol=0, atol=1e-6 * HOUR)
                self.assertFalse(parser._hm.can_undo())

    def test_the_plots_sharing_the_time_axis_follow_and_read_the_new_range(self):
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                qt_canvas, parser, (first, second) = self._show(backend, plots=2)
                self.da.reads.clear()
                self._wheel(qt_canvas, first, sum(parser.get_impl_x_axis_limits(first)) / 2, NOTCH)
                np.testing.assert_allclose(self._times(parser, second), self._times(parser, first),
                                           rtol=0, atol=1e-6 * HOUR)
                read = {name: (begin, end) for name, begin, end in self.da.reads}
                self.assertEqual(set(read), {'VAR0', 'VAR1'})
                for begin, end in read.values():
                    self.assertAlmostEqual((end - begin) / HOUR, IN, places=3)

    def test_while_streaming_the_wheel_zooms_nothing(self):
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                qt_canvas, parser, (impl_plot,) = self._show(backend)
                times = self._times(parser, impl_plot)
                qt_canvas.get_canvas().streaming = True
                self.addCleanup(setattr, qt_canvas.get_canvas(), 'streaming', False)
                self._wheel(qt_canvas, impl_plot, sum(parser.get_impl_x_axis_limits(impl_plot)) / 2, NOTCH)
                np.testing.assert_allclose(self._times(parser, impl_plot), times)


if __name__ == '__main__':
    unittest.main()
