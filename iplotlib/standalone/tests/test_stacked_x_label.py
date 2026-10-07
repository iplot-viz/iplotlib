"""The stacks of a plot share one X axis, drawn with its label under the bottom
stack. Reprocessing the signals (zoom, undo) must not label the others."""

import unittest

import numpy as np

from iplotlib.core.axis import LinearAxis
from iplotlib.core.canvas import Canvas
from iplotlib.core.plot import PlotXY
from iplotlib.core.signal import SignalXY
from iplotlib.qt.gui.iplotQtCanvasFactory import IplotQtCanvasFactory
from iplotlib.qt.testing import ensure_qapp


class StackedXLabelTest(unittest.TestCase):
    STACKS = 3

    def setUp(self) -> None:
        super().setUp()
        self.app = ensure_qapp()

    def _draw(self, backend):
        core = Canvas(1, 1, title="stacked_x_label")
        plot = PlotXY(axes=[LinearAxis(label="Time"), [LinearAxis() for _ in range(self.STACKS)]])
        x = np.linspace(0.0, 1.0, 200)
        for stack in range(1, self.STACKS + 1):
            signal = SignalXY(label=f"s{stack}")
            signal.set_data([x, np.sin(stack * x)])
            plot.add_signal(signal, stack=stack)
        core.add_plot(plot, 0)
        qt_canvas = IplotQtCanvasFactory.new(backend, canvas=core)
        qt_canvas.set_canvas(core)
        qt_canvas.resize(900, 700)
        self.app.processEvents()
        self.addCleanup(qt_canvas.deleteLater)
        return qt_canvas, qt_canvas._parser._plot_impl_plot_lut.get(id(plot))

    @staticmethod
    def _labelled(backend, stacks):
        if backend == 'pyqt':
            return [impl.getAxis('bottom').label.isVisible() for impl in stacks]
        return [impl.xaxis.label.get_visible() for impl in stacks]

    def test_zoom_and_undo_keep_the_label_under_the_bottom_stack(self):
        for backend in ('pyqt', 'matplotlib'):
            with self.subTest(backend=backend):
                qt_canvas, stacks = self._draw(backend)
                self.assertEqual(len(stacks), self.STACKS)
                drawn = self._labelled(backend, stacks)
                self.assertEqual(drawn.count(True), 1)

                parser = qt_canvas._parser
                top = stacks[0]
                qt_canvas.stage_view_lim_cmd(top)
                parser.set_oaw_axis_limits(top, 0, (0.2, 0.4))
                self.app.processEvents()
                qt_canvas.commit_view_lim_cmd(top)
                qt_canvas.push_view_lim_cmd()
                self.assertEqual(self._labelled(backend, stacks), drawn, 'zoom')

                parser.undo()
                self.app.processEvents()
                self.assertEqual(self._labelled(backend, stacks), drawn, 'undo')


if __name__ == '__main__':
    unittest.main()
