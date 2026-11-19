"""The log scale is chosen per plot: the canvas has none of its own, and a workspace saved with one on its canvas opens
with it on the plots that left it to the canvas."""

import dataclasses
import os
import unittest

import numpy as np

from iplotlib.core.canvas import Canvas
from iplotlib.core.layout import _adopt
from iplotlib.core.plot import PlotXY
from iplotlib.core.property_manager import PropertyManager
from iplotlib.core.signal import SignalXY
from iplotlib.qt.gui.forms.plotting.canvasForm import CanvasForm
from iplotlib.qt.gui.forms.plotting.plotForm import PlotXYForm
from iplotlib.qt.gui.iplotQtCanvasFactory import IplotQtCanvasFactory
from iplotlib.qt.testing import ensure_qapp

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')


def _saved(canvas_log, plot_logs) -> dict:
    """A workspace canvas as saved before, with the log scale of the canvas and those of its plots, one each."""
    canvas = Canvas(len(plot_logs), 1, title='log scale')
    x = np.linspace(1.0, 10.0, 20)
    for log in plot_logs:
        plot = PlotXY(log_scale=log)
        signal = SignalXY(label='s')
        signal.set_data([x, x * 10.0])
        plot.add_signal(signal)
        canvas.add_plot(plot, 0)
    saved = canvas.to_dict()
    saved['log_scale'] = canvas_log
    return saved


def _opened(saved: dict) -> Canvas:
    """The canvas of a saved workspace, with its plots, their axes and their signals tied to it as when MINT imports
    one."""
    canvas = Canvas.from_dict(saved)
    for column in canvas.plots:
        for plot in column:
            _adopt(canvas, plot)
    return canvas


class LogScalePerPlotTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.app = ensure_qapp()

    def test_the_canvas_has_no_log_scale(self):
        self.assertNotIn('log_scale', [f.name for f in dataclasses.fields(Canvas)])
        self.assertNotIn('log_scale', Canvas().to_dict())

    def test_only_the_preferences_of_a_plot_offer_it(self):
        canvas_form, plot_form = CanvasForm(), PlotXYForm()
        self.addCleanup(canvas_form.deleteLater)
        self.addCleanup(plot_form.deleteLater)
        self.assertNotIn('log_scale', [field['property'] for field in canvas_form.fields])
        self.assertIn('log_scale', [field['property'] for field in plot_form.fields])

    def test_a_workspace_saved_with_it_on_the_canvas_opens_with_it_on_the_plots_that_left_it_to_the_canvas(self):
        canvas = _opened(_saved(True, [None, False, True]))

        self.assertFalse(hasattr(canvas, 'log_scale'))
        self.assertEqual([plot.log_scale for plot in canvas.plots[0]], [True, False, True])
        pm = PropertyManager()
        self.assertEqual([pm.get_value(plot, 'log_scale') for plot in canvas.plots[0]], [True, False, True])

    def test_a_workspace_saved_without_it_on_the_canvas_opens_as_it_was(self):
        for canvas_log in (False, None):
            with self.subTest(canvas_log=canvas_log):
                canvas = _opened(_saved(canvas_log, [None, True]))

                self.assertEqual([plot.log_scale for plot in canvas.plots[0]], [None, True])

    def test_it_draws_on_a_log_scale_the_plots_that_left_it_to_the_canvas(self):
        for backend in ('matplotlib', 'pyqt'):
            with self.subTest(backend=backend):
                canvas = _opened(_saved(True, [None]))
                qt_canvas = IplotQtCanvasFactory.new(backend, canvas=canvas)
                self.addCleanup(qt_canvas.deleteLater)
                qt_canvas.set_canvas(canvas)
                self.app.processEvents()
                parser = qt_canvas._parser
                impl_plot = parser._plot_impl_plot_lut[id(canvas.plots[0][0])][0]

                if backend == 'pyqt':
                    self.assertTrue(impl_plot.getAxis('left').logMode)
                else:
                    self.assertEqual(impl_plot.get_yscale(), 'log')


if __name__ == '__main__':
    unittest.main()
