from iplotlib.core.canvas import Canvas
import numpy as np
import os
import unittest
from iplotlib.core.plot import PlotXY
from iplotlib.core.signal import ArraySignal
from iplotlib.impl.vtk.vtkCanvas import VTKCanvas
from iplotlib.impl.vtk.utils import regression_test
from iplotlib.impl.vtk.tests.QAppTestAdapter import QAppTestAdapter
from iplotlib.impl.vtk.tests.vtk_hints import vtk_is_headless
from qtpy.QtCore import QPoint
from qtpy import QtTest


class VTKCanvasTesting(QAppTestAdapter):

    def setUp(self):

        # A 2col x 3row canvas
        self.vtk_canvas = VTKCanvas(3, 2, title = os.path.basename(__file__))

        plot11 = PlotXY(col_span=2)
        signal11 = ArraySignal(title="Signal_a_1.1")
        signal11.set_data([np.array([0., 1., 2., 3.]), np.array([0., 1., 2., 3.])])
        plot11.add_signal(signal11)
        signal11 = ArraySignal(title="Signal_b_1.1")
        signal11.set_data([np.array([0., 1., 2., 3.]), np.array([1., 2., 3., 4.])])
        plot11.add_signal(signal11)
        signal11 = ArraySignal(title="Signal_c_1.1")
        signal11.set_data([np.array([0., 1., 2., 3.]), np.array([2., 3., 4., 5.])])
        plot11.add_signal(signal11)
        self.vtk_canvas.add_plot(plot11, 0)
        self.vtk_canvas.add_plot(None, 1)

        plot12 = PlotXY()
        signal121 = ArraySignal(title="Signal1.2.1")
        signal121.set_data([np.array([0., 1., 2., 3.]), np.array([0., 1., 2., 3.])])
        plot12.add_signal(signal121)
        signal122 = ArraySignal(title="Signal1.2.2")
        signal122.set_data([np.array([0., 1., 2., 3.]), np.array([0., 1., 2., 3.])])
        plot12.add_signal(signal122, stack=2)
        self.vtk_canvas.add_plot(plot12, 0)

        plot13 = PlotXY()
        signal13 = ArraySignal(title="Signal1.3")
        signal13.set_data([np.array([0., 1., 2., 3.]), np.array([0., 1., 2., 3.])])
        plot13.add_signal(signal13)
        self.vtk_canvas.add_plot(plot13, 0)

        plot22 = PlotXY(row_span=2)
        signal22 = ArraySignal(title="Signal2.2")
        signal22.set_data([np.array([0., 1., 2., 3.]), np.array([0., 1., 2., 3.])])
        plot22.add_signal(signal22)
        signal22 = ArraySignal(title="Signal2.2")
        signal22.set_data([np.array([0., 1., 2., 3.]), np.array([1., 2., 3., 4.])])
        plot22.add_signal(signal22)
        signal22 = ArraySignal(title="Signal2.2")
        signal22.set_data([np.array([0., 1., 2., 3.]), np.array([2., 3., 4., 5.])])
        plot22.add_signal(signal22)
        signal22 = ArraySignal(title="Signal2.2")
        signal22.set_data([np.array([0., 1., 2., 3.]), np.array([3., 4., 5., 6.])])
        plot22.add_signal(signal22)
        self.vtk_canvas.add_plot(plot22, 1)
        self.vtk_canvas.enable_crosshair(horizontal=True) # by default horizontal is off

        return super().setUp()

    def tearDown(self):
        return super().tearDown()

    def test_refresh(self):
        self.vtk_canvas.refresh()
        
    @unittest.skipIf(vtk_is_headless(), "VTK was built in headless mode.")
    def test_visuals(self):
        self.vtk_canvas.refresh()

        self.canvas.resize(800, 1080)
        self.canvas.set_canvas(self.vtk_canvas)
        self.canvas.show()
        self.canvas.set_mouse_mode(Canvas.MOUSE_MODE_CROSSHAIR)

        self.canvas.get_qvtk_render_widget().Initialize()
        self.canvas.get_qvtk_render_widget().Render()

        QtTest.QTest.mouseMove(self.canvas, QPoint(350, 200), delay=1)
        self.app.processEvents()

        renWin = self.canvas.get_qvtk_render_widget().GetRenderWindow()
        self.assertTrue(regression_test(__file__, renWin))

        # import sys
        # sys.exit(self.app.exec_())

if __name__ == "__main__":
    unittest.main()
