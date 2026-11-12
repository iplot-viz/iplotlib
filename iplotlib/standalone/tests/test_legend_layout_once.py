"""With matplotlib, a legend of many names is laid out once: the number of columns that
fits is found without building the legend again for each, and the figure is drawn once,
the legend already clear of its eye. The columns, the place and the names of each legend
are those that building it for every number of columns gives."""

import time
import unittest
from types import SimpleNamespace
from unittest import mock

import numpy as np
from matplotlib.axes import Axes
from matplotlib.backends.backend_agg import FigureCanvasAgg

from iplotlib.core.canvas import Canvas
from iplotlib.core.plot import PlotXY
from iplotlib.core.signal import SignalXY
from iplotlib.impl.matplotlib.matplotlibCanvas import MatplotlibParser
from iplotlib.interface.iplotSignalAdapter import AccessHelper
from iplotlib.qt.gui.iplotQtCanvasFactory import IplotQtCanvasFactory
from iplotlib.qt.testing import ensure_qapp

T0 = 1_788_873_880_000_000_000
HOUR = 3600 * 10 ** 9
WORDS = ['MAG', 'MCTB', 'SUP', 'DT', 'COIL', 'TEMPERATURE', 'CURRENT', 'PRESSURE', 'VACUUM', 'FLOW']


class _DataAccess:
    def get_data(self, data_s_name, **kwargs):
        x = np.linspace(kwargs['tsS'], kwargs['tsE'], 100).astype(np.int64)
        return SimpleNamespace(errcode=0, errdesc='', xdata=x, ydata=np.sin(np.linspace(0, 6, 100)), xunit='ns',
                               yunit='A', resolved_pulse=None)

    def get_data_source(self, name):
        return None


def _names(count):
    """Names of many lengths, so that the columns of a legend are not all as wide."""
    return [':'.join(WORDS[(i * 7 + j) % len(WORDS)] for j in range(1 + i % 4)) + f'_{i}' for i in range(count)]


class LegendLaidOutOnceTest(unittest.TestCase):
    def setUp(self):
        self.app = ensure_qapp()
        for name in ('da', 'pool'):
            self.addCleanup(setattr, AccessHelper, name, getattr(AccessHelper, name))
        AccessHelper.da = _DataAccess()
        AccessHelper.pool = None

    def _canvas(self, signals, layout, plots=2):
        core = Canvas(plots, 1, title="legends", shared_x_axis=True, legend=True, legend_layout=layout)
        names = _names(signals * plots)
        for p in range(plots):
            plot = PlotXY()
            for name in names[p * signals:(p + 1) * signals]:
                plot.add_signal(SignalXY(name=name, label=name, data_source='uda', ts_start=T0, ts_end=T0 + HOUR))
            plot.axes[0].is_date = True
            core.add_plot(plot, 0)
        return core

    def _draw(self, core, size=(900, 600)):
        qt_canvas = IplotQtCanvasFactory.new('matplotlib')
        self.addCleanup(qt_canvas.deleteLater)
        qt_canvas.resize(*size)
        qt_canvas.show()
        self.app.processEvents()
        qt_canvas.set_canvas(core)
        self._settle()
        return qt_canvas

    def _settle(self, seconds=0.3):
        deadline = time.perf_counter() + seconds
        while time.perf_counter() < deadline:
            self.app.processEvents()
            time.sleep(0.01)

    @staticmethod
    def _legends(qt_canvas, core):
        """Columns, place and names of each legend of the canvas."""
        parser = qt_canvas._parser
        legends = []
        for plot in core.plots[0]:
            for impl in parser._plot_impl_plot_lut.get(id(plot), []):
                leg = impl.get_legend()
                legends.append((parser._legend_columns.get(impl), np.round(leg.get_window_extent().bounds, 3),
                                [text.get_text() for text in leg.get_texts()]))
        return legends

    def assertSameLegends(self, expected, found):
        self.assertEqual(len(expected), len(found))
        for (columns, box, names), (found_columns, found_box, found_names) in zip(expected, found):
            self.assertEqual(columns, found_columns)
            np.testing.assert_allclose(box, found_box, atol=1e-3)
            self.assertEqual(names, found_names)

    def test_matplotlib_builds_a_legend_once_more_at_most_whatever_its_columns(self):
        built = []
        legend = Axes.legend

        def counted(axes, *args, **kwargs):
            built.append(axes)
            return legend(axes, *args, **kwargs)

        with mock.patch.object(Axes, 'legend', counted):
            self._draw(self._canvas(30, 'horizontal'))

        self.assertEqual(len(set(built)), 2)
        self.assertLessEqual(len(built), 4)

    def test_matplotlib_finds_the_columns_that_building_the_legend_for_each_finds(self):
        for layout in ('vertical', 'horizontal'):
            for signals, size in ((3, (900, 600)), (13, (900, 600)), (30, (1600, 1000)), (30, (500, 380))):
                with self.subTest(layout=layout, signals=signals, size=size):
                    found = self._legends(*self._drawn(signals, layout, size))
                    with mock.patch.object(MatplotlibParser, '_columns_that_fit', return_value=None):
                        tried = self._legends(*self._drawn(signals, layout, size))
                    self.assertSameLegends(tried, found)

    def test_matplotlib_draws_a_canvas_with_legends_once(self):
        core = self._canvas(13, 'vertical')
        qt_canvas = IplotQtCanvasFactory.new('matplotlib')
        self.addCleanup(qt_canvas.deleteLater)
        qt_canvas.resize(900, 600)
        qt_canvas.show()
        self.app.processEvents()
        figure = qt_canvas._parser.figure
        drawn = []
        draw = FigureCanvasAgg.draw

        def counted(canvas, *args, **kwargs):
            if canvas is figure.canvas:
                drawn.append(canvas)
            return draw(canvas, *args, **kwargs)

        with mock.patch.object(FigureCanvasAgg, 'draw', counted):
            qt_canvas.set_canvas(core)
            self._settle()

        self.assertEqual(len(drawn), 1)

    def _drawn(self, signals, layout, size):
        core = self._canvas(signals, layout)
        return self._draw(core, size), core


if __name__ == "__main__":
    unittest.main()
