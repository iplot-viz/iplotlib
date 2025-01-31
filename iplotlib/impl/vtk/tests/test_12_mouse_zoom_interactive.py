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
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest


class CanvasTesting(QAppTestAdapter):

    def setUp(self):
        super().setUp()
        # A 2col x 3row canvas
        self.core_canvas = Canvas(3, 2, title=os.path.basename(__file__))

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
        # by default horizontal is off
        self.core_canvas.enable_crosshair(horizontal=True)

    def tst_12_mouse_zoom_interactive_visuals(self):
        self.canvas.setFixedSize(800, 800)
        self.canvas.set_canvas(self.core_canvas)
        self.canvas.set_mouse_mode(Canvas.MOUSE_MODE_ZOOM)
        self.canvas.show()

        # zoom simple
        QTest.mousePress(self.canvas.get_renderer(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                         QPoint(150, 150))
        for y in range(150, 250):
            QTest.mouseMove(self.canvas.get_renderer(), QPoint(y + 300, y), delay=10)
        QTest.mouseRelease(self.canvas.get_renderer(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                           QPoint(550, 250))
        test_image_name = f"{self.id().split('.')[-1]}_1.png"
        test_image_path = os.path.join(os.path.dirname(__file__), "baseline", test_image_name)
        self.canvas._parser.export_image(test_image_path, canvas=self.core_canvas)
        self.assertTrue(regression_test2(test_image_path))

        # zoom inside a stacked plot
        QTest.mousePress(self.canvas.get_renderer(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                         QPoint(150, 350))
        for y in range(350, 400):
            QTest.mouseMove(self.canvas.get_renderer(), QPoint(y, y), delay=10)
        QTest.mouseRelease(self.canvas.get_renderer(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                           QPoint(400, 400))

        test_image_name = f"{self.id().split('.')[-1]}_2.png"
        test_image_path = os.path.join(os.path.dirname(__file__), "baseline", test_image_name)
        self.canvas._parser.export_image(test_image_path, canvas=self.core_canvas)
        self.assertTrue(regression_test2(test_image_path))

    @unittest.skipIf(matplotlib_is_headless(), "Matplotlib was built in headless mode.")
    def test_12_mouse_zoom_interactive_visuals_matplotlib(self):
        self.canvas = QtMatplotlibCanvas()
        self.tst_12_mouse_zoom_interactive_visuals()

    @unittest.skipIf(vtk_is_headless(), "VTK was built in headless mode.")
    def test_12_mouse_zoom_interactive_visuals_vtk(self):
        self.canvas = QtVTKCanvas()
        self.tst_12_mouse_zoom_interactive_visuals()


if __name__ == "__main__":
    unittest.main()
