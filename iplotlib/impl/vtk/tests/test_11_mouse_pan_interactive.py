import numpy as np
import os
import unittest
from iplotlib.core.canvas import Canvas
from iplotlib.core.plot import PlotXY
from iplotlib.core.signal import SimpleSignal
from iplotlib.impl import CanvasFactory
from iplotlib.impl.vtk.utils import regression_test
from iplotlib.impl.vtk.tests.QAppTestAdapter import QAppTestAdapter
from iplotlib.impl.vtk.tests.vtk_hints import vtk_is_headless
from PySide2.QtCore import QPoint, Qt
from PySide2.QtTest import QTest


class VTKCanvasTesting(QAppTestAdapter):

    def setUp(self):
        
        super().setUp()

        # A 2col x 3row canvas
        self.vtk_canvas = CanvasFactory.new(
            "vtk", 3, 2, title=os.path.basename(__file__))

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
        self.vtk_canvas.add_plot(plot11, 0)
        self.vtk_canvas.add_plot(None, 1)

        plot12 = PlotXY()
        signal121 = SimpleSignal(label="Signal1.2.1")
        signal121.set_data([np.array([0., 1., 2., 3.]),
                           np.array([0., 1., 2., 3.])])
        plot12.add_signal(signal121)
        signal122 = SimpleSignal(label="Signal1.2.2")
        signal122.set_data([np.array([0., 1., 2., 3.]),
                           np.array([0., 1., 2., 3.])])
        plot12.add_signal(signal122, stack=2)
        self.vtk_canvas.add_plot(plot12, 0)

        plot13 = PlotXY()
        signal13 = SimpleSignal(label="Signal1.3")
        signal13.set_data([np.array([0., 1., 2., 3.]),
                          np.array([0., 1., 2., 3.])])
        plot13.add_signal(signal13)
        self.vtk_canvas.add_plot(plot13, 0)

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
        self.vtk_canvas.add_plot(plot22, 1)
        # by default horizontal is off
        self.vtk_canvas.enable_crosshair(horizontal=True)


    def tearDown(self):
        return super().tearDown()

    def test_11_mouse_pan_interactive_refresh(self):
        self.vtk_canvas.refresh()

    @unittest.skipIf(vtk_is_headless(), "VTK was built in headless mode.")
    def test_11_mouse_pan_interactive_visuals(self):

        self.canvas.set_canvas(self.vtk_canvas)
        self.canvas.set_mouse_mode(Canvas.MOUSE_MODE_PAN)
        self.canvas.update()
        self.canvas.show()
        self.canvas.get_render_widget().Initialize()
        self.canvas.get_render_widget().Render()

        # pan simple
        QTest.mouseMove(self.canvas.get_render_widget(), QPoint(200, 150))
        QTest.mousePress(self.canvas.get_render_widget(), Qt.MouseButton.LeftButton,
                         Qt.KeyboardModifier.NoModifier, QPoint(200, 150))
        for i in range(200, 0, -1):
            QTest.mouseMove(self.canvas.get_render_widget(),
                            QPoint(i, 150 + i * 0.1), delay=1)
        QTest.mouseRelease(self.canvas.get_render_widget(), Qt.MouseButton.LeftButton,
                           Qt.KeyboardModifier.NoModifier, QPoint(0, 150))

        renWin = self.canvas.get_render_widget().GetRenderWindow()
        valid_image_name = os.path.basename(__file__).replace(
            "test", "valid").replace(".py", ".1.png")
        valid_image_path = os.path.join(os.path.join(
            os.path.dirname(__file__), "baseline"), valid_image_name)
        self.assertTrue(regression_test(valid_image_path, renWin))

        # pan inside a stacked plot
        QTest.mouseMove(self.canvas.get_render_widget(), QPoint(200, 350))
        QTest.mousePress(self.canvas.get_render_widget(), Qt.MouseButton.LeftButton,
                         Qt.KeyboardModifier.NoModifier, QPoint(200, 350))
        for i in range(200, 0, -1):
            QTest.mouseMove(self.canvas.get_render_widget(),
                            QPoint(i, 350 + i * 0.1), delay=1)
        QTest.mouseRelease(self.canvas.get_render_widget(), Qt.MouseButton.LeftButton,
                           Qt.KeyboardModifier.NoModifier, QPoint(0, 350))

        renWin = self.canvas.get_render_widget().GetRenderWindow()
        valid_image_name = os.path.basename(__file__).replace(
            "test", "valid").replace(".py", ".2.png")
        valid_image_path = os.path.join(os.path.join(
            os.path.dirname(__file__), "baseline"), valid_image_name)
        self.assertTrue(regression_test(valid_image_path, renWin))

        # import sys
        # sys.exit(self.app.exec_())


if __name__ == "__main__":
    unittest.main()
