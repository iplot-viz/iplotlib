"""The wheel zooms the time axis of the plot under the mouse, around the mouse, and of the plots that share it: in
as it turns away from the user, out as it turns back. While it turns, the plots show the data in memory, and where the
view reaches past them, the data first drawn. A turn ends when the wheel rests, or at once on any other input: then the
plots read the window it left once, ahead of it, unless the data in memory show it as finely already, and the turn is
one zoom to undo. While streaming it zooms nothing (mint#211)."""

import unittest
from types import SimpleNamespace

import numpy as np
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from iplotlib.core.axis import LinearAxis
from iplotlib.core.canvas import Canvas
from iplotlib.core.impl_base import BackendParserBase
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
#: The samples and the width of a read made once a turn that zoomed in ends, for those of the window it left; a turn
#: that zoomed out reads its window, with these samples for it.
AHEAD_SAMPLES = BackendParserBase.WHEEL_READ_DENSITY * (1 + 2 * BackendParserBase.WHEEL_READ_MARGIN)
AHEAD_WIDTH = 1 + 2 * BackendParserBase.WHEEL_READ_MARGIN
OUT_SAMPLES = BackendParserBase.WHEEL_READ_DENSITY
_SAMPLE_LIMIT = ('Number of samples in reply exceeds available limit. Reduce request interval, use decimation '
                 'or read data by chunks.')


class _DataAccess:
    """Asks for decimation, as a large archive would, so that a zoom reads the data again, and gives the samples asked
    for."""

    def __init__(self):
        self.reads = []

    def get_data(self, data_s_name, **kwargs):
        if kwargs['nbp'] == -1:
            return SimpleNamespace(errcode=-1, errdesc=_SAMPLE_LIMIT)
        self.reads.append(SimpleNamespace(name=kwargs['varname'], begin=kwargs['tsS'], end=kwargs['tsE'],
                                          samples=kwargs['nbp']))
        x = np.linspace(kwargs['tsS'], kwargs['tsE'], kwargs['nbp']).astype(np.int64)
        return SimpleNamespace(errcode=0, errdesc='', xdata=x, ydata=np.sin(np.arange(float(kwargs['nbp']))),
                               xunit='ns', yunit='A', resolved_pulse=None)

    def get_data_source(self, name):
        return None


class WheelZoomTest(unittest.TestCase):
    def setUp(self):
        self.app = ensure_qapp()
        ParserHelper.env.clear()
        self.addCleanup(ParserHelper.env.clear)
        for name in ('da', 'pool', 'num_samples'):
            self.addCleanup(setattr, AccessHelper, name, getattr(AccessHelper, name))
        AccessHelper.da = self.da = _DataAccess()
        AccessHelper.pool = None
        AccessHelper.num_samples = 1000

    def _show(self, backend, plots=1, rest_ms=60_000):
        """A canvas of `plots` plots, one under the other, sharing their time axis, over an hour, whose wheel rests
        after `rest_ms`: long enough by default that only the test ends a turn."""
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
        qt_canvas._wheel_rest.setInterval(rest_ms)
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
    def _at(qt_canvas, impl_plot, x):
        """The widget that takes the mouse over a plot, and where view time `x` of the plot is on it, half way up."""
        if hasattr(impl_plot, 'transData'):
            widget = qt_canvas._mpl_renderer
            px, py = impl_plot.transData.transform((x, np.mean(impl_plot.get_ylim())))
            ratio = widget.device_pixel_ratio
            return widget, QPointF(px / ratio, widget.height() - py / ratio)
        view = impl_plot.getViewBox()
        figure = qt_canvas._parser.figure
        return figure.viewport(), QPointF(figure.mapFromScene(view.mapViewToScene(
            QPointF(x, np.mean(view.viewRange()[1])))))

    def _wheel(self, qt_canvas, impl_plot, x, angle):
        """Turn the wheel by `angle` with the mouse at view time `x` of a plot, as Qt gives it."""
        widget, at = self._at(qt_canvas, impl_plot, x)
        event = QWheelEvent(at, QPointF(widget.mapToGlobal(at.toPoint())), QPoint(), QPoint(0, angle),
                            Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase,
                            False)
        QApplication.sendEvent(widget, event)
        QApplication.processEvents()

    def _turn(self, qt_canvas, parser, impl_plot, notches):
        """Turn the wheel by `notches` notches with the mouse at the middle of a plot: away from the user if more than
        0, back if less."""
        for _ in range(abs(notches)):
            self._wheel(qt_canvas, impl_plot, sum(parser.get_impl_x_axis_limits(impl_plot)) / 2,
                        NOTCH if notches > 0 else -NOTCH)

    @staticmethod
    def _drawn_samples(parser, impl_plot) -> int:
        lines, _, _ = parser.get_impl_lines(impl_plot)
        return len(parser.get_impl_data(lines[0])[0])

    def _read_samples_shown(self, parser, impl_plot) -> int:
        """How many of the samples the signal of a plot read are in the window it shows."""
        signal = next(iter(parser._impl_plot_cache_table.get_cache_item(impl_plot).plot().signals.values()))[0]
        begin, end = self._times(parser, impl_plot)
        x = np.asarray(signal.x_data, dtype=float)
        return int(np.searchsorted(x, end, 'right') - np.searchsorted(x, begin, 'left'))

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
                self._turn(qt_canvas, parser, impl_plot, 3)
                qt_canvas.end_wheel_turn()
                self.assertEqual(parser._hm.get_next_undo_cmd_name(), 'Zoom')
                qt_canvas.undo()
                self.app.processEvents()
                np.testing.assert_allclose(self._times(parser, impl_plot), times, rtol=0, atol=1e-6 * HOUR)
                self.assertFalse(parser._hm.can_undo())

    def test_while_the_wheel_turns_nothing_is_read_and_once_it_rests_the_plots_read_ahead(self):
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                qt_canvas, parser, (first, second) = self._show(backend, plots=2)
                self.da.reads.clear()
                self._turn(qt_canvas, parser, first, 3)
                self.assertEqual(self.da.reads, [])
                np.testing.assert_allclose(self._times(parser, second), self._times(parser, first),
                                           rtol=0, atol=1e-6 * HOUR)

                # The wheel rests: a shorter rest, set while the turn waits for it, restarts it.
                qt_canvas._wheel_rest.setInterval(50)
                QTest.qWait(500)

                self.assertEqual(sorted(read.name for read in self.da.reads), ['VAR0', 'VAR1'])
                for read in self.da.reads:
                    self.assertAlmostEqual((read.end - read.begin) / HOUR, IN ** 3 * AHEAD_WIDTH, places=3)
                    self.assertEqual(read.samples, AccessHelper.num_samples * AHEAD_SAMPLES)

    def test_any_other_input_ends_the_turn_at_once(self):
        def press(qt_canvas, impl_plot):
            widget, at = self._at(qt_canvas, impl_plot, sum(qt_canvas._parser.get_impl_x_axis_limits(impl_plot)) / 2)
            QTest.mousePress(widget, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, at.toPoint())
            QTest.mouseRelease(widget, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, at.toPoint())

        inputs = {'a press': press,
                  'the mouse leaving': lambda qt_canvas, _: QApplication.sendEvent(qt_canvas, QEvent(QEvent.Type.Leave)),
                  'another mouse mode': lambda qt_canvas, _: qt_canvas.set_mouse_mode(qt_canvas._mmode)}
        for backend in BACKENDS:
            for name, given in inputs.items():
                with self.subTest(backend=backend, input=name):
                    qt_canvas, parser, (impl_plot,) = self._show(backend)
                    self.da.reads.clear()
                    self._turn(qt_canvas, parser, impl_plot, 2)
                    given(qt_canvas, impl_plot)
                    self.assertEqual([read.name for read in self.da.reads], ['VAR0'])
                    self.assertEqual(parser._hm.get_next_undo_cmd_name(), 'Zoom')

    def test_a_turn_the_data_read_ahead_show_finely_reads_nothing(self):
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                qt_canvas, parser, (impl_plot,) = self._show(backend)
                self._turn(qt_canvas, parser, impl_plot, 1)
                qt_canvas.end_wheel_turn()
                self.da.reads.clear()

                # Back to the hour first drawn, then in by two notches: within what was read ahead, finely enough.
                for notches in (-1, 2):
                    self._turn(qt_canvas, parser, impl_plot, notches)
                    qt_canvas.end_wheel_turn()
                self.assertEqual(self.da.reads, [])

                # Further in, the samples read ahead are fewer than the pixels.
                self._turn(qt_canvas, parser, impl_plot, 3)
                qt_canvas.end_wheel_turn()
                self.assertEqual([read.name for read in self.da.reads], ['VAR0'])

    def test_a_turn_past_the_data_read_shows_the_data_first_drawn_there_until_it_reads(self):
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                qt_canvas, parser, (impl_plot,) = self._show(backend)
                self._turn(qt_canvas, parser, impl_plot, 6)
                qt_canvas.end_wheel_turn()

                self._turn(qt_canvas, parser, impl_plot, -8)
                self.assertGreater(self._drawn_samples(parser, impl_plot),
                                   self._read_samples_shown(parser, impl_plot) + AccessHelper.num_samples / 2)

                self.da.reads.clear()
                qt_canvas.end_wheel_turn()
                self.assertLessEqual(abs(self._drawn_samples(parser, impl_plot)
                                         - self._read_samples_shown(parser, impl_plot)), 2)
                # A zoom out reads what it shows, finely, and no more.
                (read,) = self.da.reads
                np.testing.assert_allclose((read.begin, read.end), self._times(parser, impl_plot), rtol=0, atol=PIXEL)
                self.assertEqual(read.samples, AccessHelper.num_samples * OUT_SAMPLES)

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
