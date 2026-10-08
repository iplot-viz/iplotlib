"""Legend tests for shifting a signal and undoing the shift.

A shift rebuilds the legend of its plot, since the signal may get a new label.
The rebuilt legend must be the one the draw builds: same entries, font size,
hidden signals and click handling. The undo must leave it as it was drawn.
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


class ShiftLegendTest(unittest.TestCase):

    def setUp(self):
        self.app = ensure_qapp()

    def _draw(self, backend):
        canvas = Canvas(1, 1, legend=True)
        canvas.font_size = FONT_SIZE
        plot = PlotXY()
        x = np.linspace(0, 10, 50)
        for i, label in enumerate(('A', 'B')):
            signal = SignalXY(label=label, uid=f'uid-{label}')
            signal.set_data([x, np.sin(x) + 3 * i])
            plot.add_signal(signal)
        canvas.add_plot(plot, 0)
        qt_canvas = IplotQtCanvasFactory.new(backend, canvas=canvas)
        qt_canvas.set_canvas(canvas)
        qt_canvas.resize(800, 600)
        self.app.processEvents()
        a, b = plot.signals[1]
        return qt_canvas, plot, a, b

    @staticmethod
    def _impl_plot(qt_canvas, signal):
        parser = qt_canvas._parser
        return parser._signal_impl_plot_lut.get(parser.signal_lut_key(signal))

    @classmethod
    def _legend(cls, qt_canvas, signal):
        """(text, font size, signal shown, uid of the signal it opens on right click) per entry."""
        parser = qt_canvas._parser
        impl_plot = cls._impl_plot(qt_canvas, signal)
        if hasattr(impl_plot, 'get_legend'):  # matplotlib Axes
            legend = impl_plot.get_legend()
            return [(text.get_text(), text.get_fontsize(), line.get_alpha() == 1,
                     getattr(parser._legend_signal_lut.get(line), 'uid', None))
                    for line, text in zip(legend.get_lines(), legend.get_texts())]
        return [(label.text, label.opts.get('size'), sample.item.isVisible(),  # pyqtgraph PlotItem
                 getattr(parser._legend_signal_lut.get(id(sample)), 'uid', None))
                for sample, label in impl_plot.legend.items]

    def _shift(self, qt_canvas, signal, dy):
        qt_canvas._start_drag_shift(self._impl_plot(qt_canvas, signal), signal, 0.0)
        qt_canvas._end_drag_shift(dy)
        self.app.processEvents()

    @classmethod
    def _hide_from_legend(cls, qt_canvas, signal):
        """Hide `signal` the way a click on its legend entry does."""
        if hasattr(qt_canvas, '_toggle_legend_line'):  # matplotlib
            parser = qt_canvas._parser
            legend = cls._impl_plot(qt_canvas, signal).get_legend()
            legend_line = next(line for line in legend.get_lines()
                               if parser._legend_signal_lut.get(line) is signal)
            qt_canvas._toggle_legend_line(legend_line, parser.map_legend_to_ax[legend_line])
        else:
            signal.lines[0].setVisible(False)

    def test_shift_and_undo_keep_the_drawn_legend(self):
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                qt_canvas, _, a, b = self._draw(backend)
                drawn = self._legend(qt_canvas, a)
                self.assertEqual([entry[0] for entry in drawn], ['A', 'B'])
                self.assertIn(drawn[0][1], (FONT_SIZE, f'{FONT_SIZE}pt'))

                self._shift(qt_canvas, a, 2.5)
                self.assertEqual(self._legend(qt_canvas, a), drawn)

                qt_canvas.undo()
                self.app.processEvents()
                self.assertEqual(self._legend(qt_canvas, a), drawn)

    def test_hidden_signal_stays_in_the_legend_after_a_shift(self):
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                qt_canvas, _, a, b = self._draw(backend)
                self._hide_from_legend(qt_canvas, b)
                hidden = self._legend(qt_canvas, a)
                self.assertEqual([entry[2] for entry in hidden], [True, False])

                self._shift(qt_canvas, a, 2.5)

                self.assertEqual(self._legend(qt_canvas, a), hidden)

    def test_rebuilt_legend_shows_the_new_label(self):
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                qt_canvas, plot, a, b = self._draw(backend)

                a.label = 'A shifted'
                qt_canvas._parser.rebuild_legend(self._impl_plot(qt_canvas, a), plot)
                self.app.processEvents()

                legend = self._legend(qt_canvas, a)
                self.assertEqual([entry[0] for entry in legend], ['A shifted', 'B'])
                self.assertEqual([entry[3] for entry in legend], [a.uid, b.uid])
                self.assertIn(legend[0][1], (FONT_SIZE, f'{FONT_SIZE}pt'))


if __name__ == '__main__':
    unittest.main()
