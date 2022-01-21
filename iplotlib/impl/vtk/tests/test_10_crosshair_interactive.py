import numpy as np
import os
import unittest
from iplotlib.core.canvas import Canvas
from iplotlib.core.plot import PlotXY
from iplotlib.core.signal import SimpleSignal
from iplotlib.impl.vtk.utils import regression_test
from iplotlib.impl.vtk.tests.qVTKAppTestAdapter import QVTKAppTestAdapter
from iplotlib.impl.vtk.tests.vtk_hints import vtk_is_headless
from PySide2.QtCore import QPoint
from PySide2.QtTest import QTest


class VTKCanvasTesting(QVTKAppTestAdapter):

    def setUp(self):

        super().setUp()

        # A 2col x 3row canvas
        self.core_canvas = Canvas(3, 2, title=os.path.basename(__file__))

        plot11 = PlotXY(col_span=2)
        signal11 = SimpleSignal(label="Signal_a_1.1")
        signal11.set_data([np.array([0., 1., 2., 3.]),
                          np.array([0., 1., 2., 3.])])
        plot11.add_signal(signal11)
        signal11 = SimpleSignal(label="Signal_b_1.1")
        signal11.set_data([np.array([0., 1., 2., 3.]),
                          np.array([1., 2., 3., 4.])])
        plot11.add_signal(signal11)
        signal11 = SimpleSignal(label="Signal_c_1.1")
        signal11.set_data([np.array([0., 1., 2., 3.]),
                          np.array([2., 3., 4., 5.])])
        plot11.add_signal(signal11)
        self.core_canvas.add_plot(plot11, 0)
        self.core_canvas.add_plot(None, 1)

        plot12 = PlotXY()
        signal121 = SimpleSignal(label="Signal1.2.1")
        signal121.set_data([np.array([0., 1., 2., 3.]),
                           np.array([0., 1., 2., 3.])])
        plot12.add_signal(signal121)
        signal122 = SimpleSignal(label="Signal1.2.2")
        signal122.set_data([np.array([0., 1., 2., 3.]),
                           np.array([0., 1., 2., 3.])])
        plot12.add_signal(signal122, stack=2)
        self.core_canvas.add_plot(plot12, 0)

        plot13 = PlotXY()
        signal13 = SimpleSignal(label="Signal1.3")
        signal13.set_data([np.array([0., 1., 2., 3.]),
                          np.array([0., 1., 2., 3.])])
        plot13.add_signal(signal13)
        self.core_canvas.add_plot(plot13, 0)

        plot22 = PlotXY(row_span=2)
        signal22 = SimpleSignal(label="Signal2.2")
        signal22.set_data([np.array([0., 1., 2., 3.]),
                          np.array([0., 1., 2., 3.])])
        plot22.add_signal(signal22)
        signal22 = SimpleSignal(label="Signal2.2")
        signal22.set_data([np.array([0., 1., 2., 3.]),
                          np.array([1., 2., 3., 4.])])
        plot22.add_signal(signal22)
        signal22 = SimpleSignal(label="Signal2.2")
        signal22.set_data([np.array([0., 1., 2., 3.]),
                          np.array([2., 3., 4., 5.])])
        plot22.add_signal(signal22)
        signal22 = SimpleSignal(label="Signal2.2")
        signal22.set_data([np.array([0., 1., 2., 3.]),
                          np.array([3., 4., 5., 6.])])
        plot22.add_signal(signal22)
        self.core_canvas.add_plot(plot22, 1)
        # by default horizontal is off
        self.core_canvas.enable_crosshair(horizontal=True)


    def tearDown(self):
        return super().tearDown()

    @unittest.skipIf(vtk_is_headless(), "VTK was built in headless mode.")
    def test_10_crosshair_refresh(self):
        self.canvas.set_canvas(self.core_canvas)

    @unittest.skipIf(vtk_is_headless(), "VTK was built in headless mode.")
    def test_10_crosshair_visuals(self):

        self.canvas.set_canvas(self.core_canvas)
        self.canvas.set_mouse_mode(Canvas.MOUSE_MODE_CROSSHAIR)
        self.canvas.show()

        QTest.mouseMove(self.canvas.get_vtk_renderer(), QPoint(400, 150), delay=1)
        self.app.processEvents()

        renWin = self.canvas.get_vtk_renderer().GetRenderWindow()
        valid_image_name = os.path.basename(__file__).replace(
            "test", "valid").replace(".py", ".png")
        valid_image_path = os.path.join(os.path.join(
            os.path.dirname(__file__), "baseline"), valid_image_name)
        self.assertTrue(regression_test(valid_image_path, renWin))

        # import sys
        # sys.exit(self.app.exec_())


if __name__ == "__main__":
    unittest.main()
