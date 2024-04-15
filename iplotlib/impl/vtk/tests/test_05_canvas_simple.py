import numpy as np
import os
import unittest
from iplotlib.core.canvas import Canvas
from iplotlib.core.plot import PlotXY
from iplotlib.core.signal import SimpleSignal
from iplotlib.impl.vtk.utils import regression_test
from iplotlib.impl.vtk.tests.qVTKAppTestAdapter import QVTKAppTestAdapter
from iplotlib.impl.vtk.tests.vtk_hints import vtk_is_headless


class VTKCanvasTesting(QVTKAppTestAdapter):

    def setUp(self) -> None:
        # A 2col x 2row canvas
        self.core_canvas = Canvas(2, 2, title=os.path.basename(__file__))

        # A plot in top-left with 1 signal.
        signal11 = SimpleSignal(label="Signal1.1")
        signal11.set_data([np.array([0., 1., 2., 3.]),
                           np.array([0., 1., 2., 3.])])
        plot11 = PlotXY()
        plot11.add_signal(signal11)
        self.core_canvas.add_plot(plot11, 0)

        # A plot in bottom-left with 1 signal.
        signal12 = SimpleSignal(label="Signal1.2")
        signal12.set_data([np.array([0., 1., 2., 3.]),
                           np.array([0., 1., 2., 3.])])
        plot12 = PlotXY()
        plot12.add_signal(signal12)
        self.core_canvas.add_plot(plot12, 0)

        # A plot in top-right with 1 signal.
        signal21 = SimpleSignal(label="Signal2.1")
        signal21.set_data([np.array([0., 1., 2., 3.]),
                           np.array([0., 1., 2., 3.])])
        plot21 = PlotXY()
        plot21.add_signal(signal21)
        self.core_canvas.add_plot(plot21, 1)

        # A plot in bottom-right with 1 signal.
        signal22 = SimpleSignal(label="Signal2.2")
        signal22.set_data([np.array([0., 1., 2., 3.]),
                           np.array([0., 1., 2., 3.])])
        plot22 = PlotXY()
        plot22.add_signal(signal22)
        self.core_canvas.add_plot(plot22, 1)

        return super().setUp()

    def tearDown(self):
        return super().tearDown()

    @unittest.skipIf(vtk_is_headless(), "VTK was built in headless mode.")
    def test_05_canvas_simple_refresh(self):
        self.canvas.set_canvas(self.core_canvas)
        size = self.canvas._parser.matrix.GetSize()
        self.assertEqual(size[0], 2)
        self.assertEqual(size[1], 2)

    @unittest.skipIf(vtk_is_headless(), "VTK was built in headless mode.")
    def test_05_canvas_simple_visuals(self):
        self.canvas.set_canvas(self.core_canvas)
        self.canvas.update()
        self.canvas.show()
        self.canvas.get_vtk_renderer().Initialize()
        self.canvas.get_vtk_renderer().Render()

        renWin = self.canvas.get_vtk_renderer().GetRenderWindow()
        valid_image_name = os.path.basename(__file__).replace(
            "test", "valid").replace(".py", ".png")
        valid_image_path = os.path.join(os.path.join(
            os.path.dirname(__file__), "baseline"), valid_image_name)
        self.assertTrue(regression_test(valid_image_path, renWin))


if __name__ == "__main__":
    unittest.main()

    # Uncomment below to run as an application
    # from qtpy.QtWidgets import QApplication
    # from iplotlib.impl.vtk.qt.qtVTKCanvas import QtVTKCanvas
    # app = QApplication([])

    # # A 2col x 2row canvas

    # canvas = VTKCanvas(2, 2, title=str(__name__))

    # # A plot in top-left with 1 signal.
    # signal11 = SimpleSignal(label="Signal1.1")
    # signal11.set_data([np.array([0., 1., 2., 3.]),
    #                     np.array([0., 1., 2., 3.])])
    # plot11 = PlotXY()
    # plot11.add_signal(signal11)
    # canvas.add_plot(plot11, 0)

    # # A plot in bottom-left with 1 signal.
    # signal12 = SimpleSignal(label="Signal1.2")
    # signal12.set_data([np.array([0., 1., 2., 3.]),
    #                     np.array([0., 1., 2., 3.])])
    # plot12 = PlotXY()
    # plot12.add_signal(signal12)
    # canvas.add_plot(plot12, 0)

    # # A plot in top-right with 1 signal.
    # signal21 = SimpleSignal(label="Signal2.1")
    # signal21.set_data([np.array([0., 1., 2., 3.]),
    #                     np.array([0., 1., 2., 3.])])
    # plot21 = PlotXY()
    # plot21.add_signal(signal21)
    # canvas.add_plot(plot21, 1)

    # # A plot in bottom-right with 1 signal.
    # signal22 = SimpleSignal(label="Signal2.2")
    # signal22.set_data([np.array([0., 1., 2., 3.]),
    #                     np.array([0., 1., 2., 3.])])
    # plot22 = PlotXY()
    # plot22.add_signal(signal22)
    # canvas.add_plot(plot22, 1)
    # vtk_canvas = QtVTKCanvas()
    # vtk_canvas.set_canvas(canvas)
    # vtk_canvas.show()
    # vtk_canvas.get_vtk_renderer().Initialize()
    # vtk_canvas.get_vtk_renderer().Render()
    # import sys
    # sys.exit(app.exec_())
