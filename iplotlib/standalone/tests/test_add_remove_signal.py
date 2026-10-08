"""Adding a signal to a drawn plot and taking it off again, without redrawing the canvas.

A shifted copy of a signal is drawn this way, and its undo takes it off: the
legend must list it with the drawn font size, and once removed it must leave
no curve behind on the plot, or it would still count for the autoscale.
"""

import unittest

import numpy as np

from iplotlib.core.canvas import Canvas
from iplotlib.core.plot import PlotXY
from iplotlib.core.signal import SignalXY
from iplotlib.qt.gui.iplotQtCanvasFactory import IplotQtCanvasFactory
from iplotlib.qt.testing import ensure_qapp

BACKENDS = ('matplotlib', 'pyqt')
FONT_SIZE = 14


class AddRemoveSignalTest(unittest.TestCase):

    def setUp(self):
        self.app = ensure_qapp()
        self.x = np.linspace(0, 10, 50)

    def _draw(self, backend):
        canvas = Canvas(1, 1, legend=True)
        canvas.font_size = FONT_SIZE
        plot = PlotXY()
        signal = SignalXY(label='A', uid='uid-A')
        signal.set_data([self.x, np.sin(self.x)])
        plot.add_signal(signal)
        canvas.add_plot(plot, 0)
        qt_canvas = IplotQtCanvasFactory.new(backend, canvas=canvas)
        qt_canvas.set_canvas(canvas)
        qt_canvas.resize(800, 600)
        self.app.processEvents()
        return qt_canvas, plot, signal

    @staticmethod
    def _curves(impl_plot):
        if hasattr(impl_plot, 'get_lines'):  # matplotlib Axes
            return len(impl_plot.get_lines())
        return len(impl_plot.listDataItems())  # pyqtgraph PlotItem

    @staticmethod
    def _legend(impl_plot):
        """(text, font size) per legend entry."""
        if hasattr(impl_plot, 'get_legend'):
            return [(text.get_text(), text.get_fontsize()) for text in impl_plot.get_legend().get_texts()]
        return [(label.text, label.opts.get('size')) for _, label in impl_plot.legend.items]

    def test_added_signal_is_drawn_and_removed_without_a_trace(self):
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                qt_canvas, plot, signal = self._draw(backend)
                parser = qt_canvas._parser
                impl_plot = parser._signal_impl_plot_lut.get(signal.uid)
                font = FONT_SIZE if backend == 'matplotlib' else f'{FONT_SIZE}pt'

                copy = SignalXY(label='A copy', uid='uid-copy')
                copy.set_data([self.x, np.sin(self.x) + 1])
                parser.add_signal(impl_plot, plot, copy, 1)
                self.app.processEvents()

                self.assertEqual(self._curves(impl_plot), 2)
                self.assertEqual(self._legend(impl_plot), [('A', font), ('A copy', font)])

                parser.remove_signal(copy)
                self.app.processEvents()

                self.assertEqual(self._curves(impl_plot), 1)
                self.assertEqual(self._legend(impl_plot), [('A', font)])
                self.assertEqual([s is signal for s in plot.signals[1]], [True])


if __name__ == '__main__':
    unittest.main()
