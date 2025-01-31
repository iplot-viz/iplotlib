import numpy as np
import os
import unittest

from iplotlib.qt.testing import QAppTestAdapter

from iplotlib.core.canvas import Canvas
from iplotlib.core.plot import PlotXY
from iplotlib.core.signal import SignalXY
from iplotlib.impl.matplotlib.qt import QtMatplotlibCanvas
from iplotlib.impl.vtk.qt import QtVTKCanvas
from iplotlib.impl.vtk.utils import regression_test2
from iplotlib.impl.vtk.tests.vtk_hints import vtk_is_headless, matplotlib_is_headless


class CanvasTesting(QAppTestAdapter):

    def setUp(self) -> None:
        # A 2col x 2row canvas
        self.core_canvas = Canvas(2, 2, title=os.path.basename(__file__))

        for i, label in enumerate(["Signal1.1", "Signal1.2", "Signal2.1", "Signal2.2"]):
            col = i % 2
            signal = SignalXY(label=label)
            signal.set_data([np.array([0., 1., 2., 3.]),
                             np.array([0., 1., 2., 3.])])
            plot = PlotXY()
            plot.add_signal(signal)
            self.core_canvas.add_plot(plot, col)

        return super().setUp()

    def tearDown(self):
        return super().tearDown()

    @unittest.skipIf(vtk_is_headless(), "VTK was built in headless mode.")
    def test_05_canvas_simple_refresh_vtk(self):
        self.canvas = QtVTKCanvas()
        self.canvas.set_canvas(self.core_canvas)
        size = self.canvas._parser.matrix.GetSize()
        self.assertEqual(size[0], 2)
        self.assertEqual(size[1], 2)

    @unittest.skipIf(matplotlib_is_headless(), "Matplotlib was built in headless mode.")
    def test_05_canvas_simple_refresh_matplotlib(self):
        self.canvas = QtMatplotlibCanvas()
        self.canvas.set_canvas(self.core_canvas)
        size = self.canvas._parser._layout
        self.assertEqual(size.nrows, 2)
        self.assertEqual(size.ncols, 2)

    @unittest.skipIf(vtk_is_headless(), "VTK was built in headless mode.")
    def test_05_canvas_simple_visuals_vtk(self):
        self.canvas = QtVTKCanvas()
        self.tst_05_canvas_simple_visuals()

    @unittest.skipIf(matplotlib_is_headless(), "Matplotlib was built in headless mode.")
    def test_05_canvas_simple_visuals_matplotlib(self):
        self.canvas = QtMatplotlibCanvas()
        self.tst_05_canvas_simple_visuals()

    def tst_05_canvas_simple_visuals(self):
        self.canvas.setFixedSize(800, 800)
        self.canvas.set_canvas(self.core_canvas)
        self.canvas.update()
        self.canvas.show()
        valid_image_name = f"{self.id().split('.')[-1]}.png"
        valid_image_path = os.path.join(os.path.dirname(__file__), "baseline", valid_image_name)
        self.canvas._parser.export_image(valid_image_path, canvas=self.core_canvas)
        self.assertTrue(regression_test2(valid_image_path))


if __name__ == "__main__":
    unittest.main()
