"""A line of many more samples in the view than a plot has pixels across draws only those that draw each pixel, in
both backends, while what reads its values takes all of them: the rulers and the crosshair, the statistics and the
fit of Y. A line whose markers, steps or log scale need each sample, or not limited to the view, draws them all."""

import unittest
from types import SimpleNamespace

import numpy as np

from iplotlib.core.axis import LinearAxis
from iplotlib.core.canvas import Canvas
from iplotlib.core.impl_base import line_samples
from iplotlib.core.plot import PlotXY
from iplotlib.core.signal import SignalXY
from iplotlib.interface.iplotSignalAdapter import AccessHelper, ParserHelper
from iplotlib.qt.gui.IplotQtStatistics import _line_source_data
from iplotlib.qt.gui.iplotQtCanvasFactory import IplotQtCanvasFactory
from iplotlib.qt.testing import ensure_qapp

BACKENDS = ('matplotlib', 'pyqt')
T0 = 1_788_873_880_000_000_000
HOUR = 3600 * 10 ** 9
SAMPLES = 50_000


class _DataAccess:
    """Noise on a slow wave, so that the sample nearest to a time is seldom the first, the lowest, the highest or the
    last of its bucket; a variable of a range of elements ('[0:3]') has a column per element."""

    def get_data(self, data_s_name, **kwargs):
        x = np.linspace(kwargs['tsS'], kwargs['tsE'], SAMPLES).astype(np.int64)
        rng = np.random.default_rng(len(kwargs['varname']))
        columns = 3 if '[' in kwargs['varname'] else 1
        y = np.sin(np.linspace(0, 20, SAMPLES))[:, None] + rng.standard_normal((SAMPLES, columns))
        return SimpleNamespace(errcode=0, errdesc='', xdata=x, ydata=y[:, 0] if columns == 1 else y, xunit='ns',
                               yunit='A', resolved_pulse=None)

    def get_data_source(self, name):
        return None


def _canvas(name='DENSE', log_scale=False, **signal) -> Canvas:
    canvas = Canvas(1, 1, title="dense lines")
    plot = PlotXY(axes=[LinearAxis(is_date=True), [LinearAxis()]], log_scale=log_scale)
    plot.add_signal(SignalXY(name=name, label=name, data_source='uda', ts_start=T0, ts_end=T0 + HOUR, **signal))
    canvas.add_plot(plot, 0)
    return canvas


class DenseLinesTest(unittest.TestCase):
    def setUp(self):
        self.app = ensure_qapp()
        ParserHelper.env.clear()
        self.addCleanup(ParserHelper.env.clear)
        for name in ('da', 'pool'):
            self.addCleanup(setattr, AccessHelper, name, getattr(AccessHelper, name))
        AccessHelper.da = _DataAccess()
        AccessHelper.pool = None

    def _drawn(self, backend, canvas: Canvas):
        qt_canvas = IplotQtCanvasFactory.new(backend)
        self.addCleanup(qt_canvas.deleteLater)
        qt_canvas.resize(1200, 800)
        qt_canvas.set_canvas(canvas)
        self.app.processEvents()
        signal = canvas.plots[0][0].signals[1][0]
        return qt_canvas._parser, signal, signal.lines

    @staticmethod
    def _points(line) -> int:
        """The samples a line draws."""
        return len(line.get_xdata() if hasattr(line, 'get_xdata') else line.getData()[0])

    def test_a_dense_line_draws_fewer_samples_than_it_stands_for(self):
        for backend in BACKENDS:
            for name, lines in (('DENSE', 1), ('DENSE[0:3]', 3)):
                with self.subTest(backend=backend, signal=name):
                    parser, signal, drawn = self._drawn(backend, _canvas(name))

                    self.assertEqual(len(drawn), lines)
                    for column, line in enumerate(drawn):
                        x, y = line_samples(line)
                        self.assertLess(self._points(line), SAMPLES // 2)
                        self.assertEqual(len(x), SAMPLES)
                        expected = signal.y_data if lines == 1 else signal.y_data[:, column]
                        np.testing.assert_array_equal(y, expected)
                        # The statistics read the samples; the fit of Y reads the line, as low and high as they.
                        self.assertEqual(len(_line_source_data(line)[1]), SAMPLES)
                        self.assertEqual(parser.get_bottom_top(line, x[0], x[-1]), (expected.min(), expected.max()))

    def test_the_rulers_read_the_value_of_the_nearest_sample(self):
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                parser, signal, drawn = self._drawn(backend, _canvas())
                x, y = line_samples(drawn[0])
                impl_plot = parser._signal_impl_plot_lut.get(parser.signal_lut_key(signal))

                for index in (1234, 23456, SAMPLES - 789):
                    values = parser._ruler_signal_values(impl_plot, float(x[index]))
                    self.assertEqual(values['DENSE'], float(y[index]))

    def test_a_line_whose_samples_show_draws_them_all(self):
        for backend in BACKENDS:
            for kind, canvas in (('marker', _canvas(marker='o')), ('steps', _canvas(step='post')),
                                 ('log scale', _canvas(log_scale=True)),
                                 ('not limited to the view', _canvas(extremities=True))):
                with self.subTest(backend=backend, kind=kind):
                    _, _, drawn = self._drawn(backend, canvas)

                    self.assertEqual(self._points(drawn[0]), SAMPLES)
                    self.assertIsNone(line_samples(drawn[0]))


if __name__ == "__main__":
    unittest.main()
