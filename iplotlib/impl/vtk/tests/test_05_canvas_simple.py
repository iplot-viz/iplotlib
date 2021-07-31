import numpy as np
import os
import unittest
from iplotlib.core.plot import Plot
from iplotlib.core.signal import ArraySignal
from iplotlib.impl.vtk.vtkCanvas import VTKCanvas
from iplotlib.impl.vtk.utils import regression_test
from iplotlib.impl.vtk.tests.QAppTestAdapter import QAppTestAdapter

class VTKCanvasTesting(QAppTestAdapter):

    def setUp(self) -> None:

        # A 2col x 2row canvas
        self.vtk_canvas = VTKCanvas(2, 2, title = os.path.basename(__file__))

        # A plot in top-left with 1 signal.
        signal11 = ArraySignal(title="Signal1.1")
        signal11.set_data([np.array([0., 1., 2., 3.]),
                          np.array([0., 1., 2., 3.])])
        plot11 = Plot()
        plot11.add_signal(signal11)
        self.vtk_canvas.add_plot(plot11, 0)

        # A plot in bottom-left with 1 signal.
        signal12 = ArraySignal(title="Signal1.2")
        signal12.set_data([np.array([0., 1., 2., 3.]),
                          np.array([0., 1., 2., 3.])])
        plot12 = Plot()
        plot12.add_signal(signal12)
        self.vtk_canvas.add_plot(plot12, 0)

        # A plot in top-right with 1 signal.
        signal21 = ArraySignal(title="Signal2.1")
        signal21.set_data([np.array([0., 1., 2., 3.]),
                          np.array([0., 1., 2., 3.])])
        plot21 = Plot()
        plot21.add_signal(signal21)
        self.vtk_canvas.add_plot(plot21, 1)

        # A plot in bottom-right with 1 signal.
        signal22 = ArraySignal(title="Signal2.2")
        signal22.set_data([np.array([0., 1., 2., 3.]),
                          np.array([0., 1., 2., 3.])])
        plot22 = Plot()
        plot22.add_signal(signal22)
        self.vtk_canvas.add_plot(plot22, 1)

        return super().setUp()

    def tearDown(self):
        return super().tearDown()

    def test_refresh(self):

        self.assertEqual(self.vtk_canvas.cols, 2)
        self.assertEqual(self.vtk_canvas.rows, 2)

        self.vtk_canvas.refresh()

        size = self.vtk_canvas.matrix.GetSize()
        self.assertEqual(size[0], 2)
        self.assertEqual(size[1], 2)

        self.canvas.set_canvas(self.vtk_canvas)
        self.canvas.show()
        self.canvas.get_qvtk_render_widget().Initialize()
        self.canvas.get_qvtk_render_widget().Render()

        renWin = self.canvas.get_qvtk_render_widget().GetRenderWindow()
        self.assertTrue(regression_test(__file__, renWin))


if __name__ == "__main__":
    unittest.main()
    
    # Uncomment below to run as an application
    # from qtpy.QtWidgets import QApplication
    # from iplotlib.impl.vtk.qt.qtVTKCanvas import QtVTKCanvas
    # app = QApplication([])

    # # A 2col x 2row canvas

    # vtk_canvas = VTKCanvas(2, 2, title=str(__name__))

    # # A plot in top-left with 1 signal.
    # signal11 = ArraySignal(title="Signal1.1")
    # signal11.set_data([np.array([0., 1., 2., 3.]),
    #                     np.array([0., 1., 2., 3.])])
    # plot11 = Plot()
    # plot11.add_signal(signal11)
    # vtk_canvas.add_plot(plot11, 0)

    # # A plot in bottom-left with 1 signal.
    # signal12 = ArraySignal(title="Signal1.2")
    # signal12.set_data([np.array([0., 1., 2., 3.]),
    #                     np.array([0., 1., 2., 3.])])
    # plot12 = Plot()
    # plot12.add_signal(signal12)
    # vtk_canvas.add_plot(plot12, 0)

    # # A plot in top-right with 1 signal.
    # signal21 = ArraySignal(title="Signal2.1")
    # signal21.set_data([np.array([0., 1., 2., 3.]),
    #                     np.array([0., 1., 2., 3.])])
    # plot21 = Plot()
    # plot21.add_signal(signal21)
    # vtk_canvas.add_plot(plot21, 1)

    # # A plot in bottom-right with 1 signal.
    # signal22 = ArraySignal(title="Signal2.2")
    # signal22.set_data([np.array([0., 1., 2., 3.]),
    #                     np.array([0., 1., 2., 3.])])
    # plot22 = Plot()
    # plot22.add_signal(signal22)
    # vtk_canvas.add_plot(plot22, 1)
    # vtk_canvas.refresh()
    # canvas = QtVTKCanvas()
    # canvas.set_canvas(vtk_canvas)
    # canvas.show()
    # canvas.get_qvtk_render_widget().Initialize()
    # canvas.get_qvtk_render_widget().Render()
    # import sys
    # sys.exit(app.exec_())
