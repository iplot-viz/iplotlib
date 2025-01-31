import numpy as np
import os
import unittest

from iplotlib.qt.testing import QAppTestAdapter

from iplotlib.core.axis import LinearAxis
from iplotlib.core.canvas import Canvas
from iplotlib.core.plot import PlotXY
from iplotlib.core.signal import SignalXY
from iplotlib.impl.matplotlib.qt import QtMatplotlibCanvas
from iplotlib.impl.vtk.qt import QtVTKCanvas
from iplotlib.impl.vtk.utils import regression_test2
from iplotlib.impl.vtk.tests.vtk_hints import vtk_is_headless, matplotlib_is_headless


class CanvasTesting(QAppTestAdapter):

    def setUp(self):
        super().setUp()
        # A 2col x 3row canvas
        self.core_canvas = Canvas(rows=3, cols=2, title=os.path.basename(__file__))

        plot11 = PlotXY(col_span=2)
        signal11 = SignalXY(label="Signal_a_1.1")
        signal11.set_data([np.array([0., 1., 2., 3.]),
                           np.array([0., 1., 2., 3.])])
        plot11.add_signal(signal11)
        signal11 = SignalXY(label="Signal_b_1.1")
        signal11.set_data([np.array([0., 1., 2., 3.]),
                           np.array([1., 2., 3., 4.])])
        plot11.add_signal(signal11)
        signal11 = SignalXY(label="Signal_c_1.1")
        signal11.set_data([np.array([0., 1., 2., 3.]),
                           np.array([2., 3., 4., 5.])])
        plot11.add_signal(signal11)
        self.core_canvas.add_plot(plot11, 0)
        self.core_canvas.add_plot(None, 1)

        plot12 = PlotXY(axes=[LinearAxis(), [LinearAxis(), LinearAxis()]])
        signal121 = SignalXY(label="Signal1.2.1")
        signal121.set_data([np.array([0., 1., 2., 3.]),
                            np.array([0., 1., 2., 3.])])
        plot12.add_signal(signal121)
        signal122 = SignalXY(label="Signal1.2.2")
        signal122.set_data([np.array([0., 1., 2., 3.]),
                            np.array([0., 1., 2., 3.])])
        plot12.add_signal(signal122, stack=2)
        self.core_canvas.add_plot(plot12, 0)

        plot13 = PlotXY()
        signal13 = SignalXY(label="Signal1.3")
        signal13.set_data([np.array([0., 1., 2., 3.]),
                           np.array([0., 1., 2., 3.])])
        plot13.add_signal(signal13)
        self.core_canvas.add_plot(plot13, 0)

        plot22 = PlotXY(row_span=2)
        signal22 = SignalXY(label="Signal2.2")
        signal22.set_data([np.array([0., 1., 2., 3.]),
                           np.array([0., 1., 2., 3.])])
        plot22.add_signal(signal22)
        signal22 = SignalXY(label="Signal2.2")
        signal22.set_data([np.array([0., 1., 2., 3.]),
                           np.array([1., 2., 3., 4.])])
        plot22.add_signal(signal22)
        signal22 = SignalXY(label="Signal2.2")
        signal22.set_data([np.array([0., 1., 2., 3.]),
                           np.array([2., 3., 4., 5.])])
        plot22.add_signal(signal22)
        signal22 = SignalXY(label="Signal2.2")
        signal22.set_data([np.array([0., 1., 2., 3.]),
                           np.array([3., 4., 5., 6.])])
        plot22.add_signal(signal22)
        self.core_canvas.add_plot(plot22, 1)

        
    @unittest.skipIf(vtk_is_headless(), "VTK was built in headless mode.")
    def test_06_canvas_complex_refresh_vtk(self):
        self.canvas = QtVTKCanvas()
        self.canvas.set_canvas(self.core_canvas)
        size = self.canvas._parser.matrix.GetSize()
        self.assertEqual(size[0], 2)
        self.assertEqual(size[1], 3)

    @unittest.skipIf(matplotlib_is_headless(), "Matplotlib was built in headless mode.")
    def test_06_canvas_complex_refresh_matplotlib(self):
        self.canvas = QtMatplotlibCanvas()
        self.canvas.set_canvas(self.core_canvas)
        size = self.canvas._parser._layout
        self.assertEqual(size.nrows, 3)
        self.assertEqual(size.ncols, 2)

    @unittest.skipIf(vtk_is_headless(), "VTK was built in headless mode.")
    def test_06_canvas_complex_visuals_vtk(self):
        self.canvas = QtVTKCanvas()
        self.tst_06_canvas_complex_visuals()

    @unittest.skipIf(matplotlib_is_headless(), "Matplotlib was built in headless mode.")
    def test_06_canvas_complex_visuals_matplotlib(self):
        self.canvas = QtMatplotlibCanvas()
        self.tst_06_canvas_complex_visuals()

    def tst_06_canvas_complex_visuals(self):
        self.canvas.set_canvas(self.core_canvas)
        self.canvas.update()
        self.canvas.show()
        valid_image_name = f"{self.id().split('.')[-1]}.png"
        valid_image_path = os.path.join(os.path.dirname(__file__), "baseline", valid_image_name)
        self.canvas._parser.export_image(valid_image_path, canvas=self.core_canvas)
        self.assertTrue(regression_test2(valid_image_path))



if __name__ == "__main__":
    unittest.main()
