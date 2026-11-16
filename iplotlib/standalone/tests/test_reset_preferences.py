"""Reset in the preferences must not recolor the curves.

A signal gets its color from the palette of its plot when it is added. Reset used to clear it to None, which
resolves to the configured default color: every curve was drawn in that one color until the next draw.
"""

import unittest

import numpy as np
from matplotlib.colors import to_hex
from PySide6.QtCore import QModelIndex

from iplotlib.core.canvas import Canvas
from iplotlib.core.plot import PlotXY
from iplotlib.core.signal import SignalXY
from iplotlib.qt.gui.forms.plotting.canvasForm import CanvasForm
from iplotlib.qt.gui.iplotQtCanvasFactory import IplotQtCanvasFactory
from iplotlib.qt.models.beanItemModel import BeanItemModel
from iplotlib.qt.testing import ensure_qapp


def _canvas_with_three_signals():
    core = Canvas(1, 1, title="reset")
    x = np.linspace(0.0, 10.0, 200)
    plot = PlotXY()
    for shift in range(3):
        signal = SignalXY(label=f"s{shift}")
        signal.set_data([x, np.sin(x + shift)])
        plot.add_signal(signal)
    core.add_plot(plot, 0)
    return core, plot


class ResetKeepsTheColorsOfTheSignalsTest(unittest.TestCase):
    def setUp(self) -> None:
        super().setUp()
        self.app = ensure_qapp()

    @staticmethod
    def _drawn_colors(backend, qt_canvas, plot):
        impl = qt_canvas._parser._plot_impl_plot_lut[id(plot)][0]
        if backend == 'pyqt':
            return [item.opts['pen'].color().name() for item in impl.listDataItems()]
        return [to_hex(line.get_color()) for line in impl.get_lines()]

    def test_reset_of_the_canvas_keeps_the_color_of_each_curve(self):
        for backend in ('pyqt', 'matplotlib'):
            core, plot = _canvas_with_three_signals()
            qt_canvas = IplotQtCanvasFactory.new(backend, canvas=core)
            qt_canvas.set_canvas(core)
            before = self._drawn_colors(backend, qt_canvas, plot)
            self.assertEqual(len(set(before)), 3, backend)

            form = CanvasForm()
            form.widgetModel.setData(QModelIndex(), core, BeanItemModel.PyObjectRole)
            form.widgetMapper.toFirst()
            form.reset_prefs()  # what the Reset button runs
            qt_canvas.refresh()
            self.app.processEvents()

            self.assertEqual(self._drawn_colors(backend, qt_canvas, plot), before, backend)
            qt_canvas.deleteLater()


if __name__ == "__main__":
    unittest.main()
