import numpy as np
import os
import unittest

from iplotlib.core.axis import LinearAxis

from iplotlib.core.canvas import Canvas
from iplotlib.core.plot import PlotXY
from iplotlib.core.signal import SignalXY
from iplotlib.impl.matplotlib.qt import QtMatplotlibCanvas
from iplotlib.impl.vtk.qt import QtVTKCanvas
from iplotlib.impl.vtk.utils import regression_test2
from iplotlib.qt.testing import QAppTestAdapter
from iplotlib.impl.vtk.tests.vtk_hints import vtk_is_headless, matplotlib_is_headless


class CanvasTesting(QAppTestAdapter):

    def setUp(self) -> None:
        super().setUp()
        ts = 1_000_000_000
        te = ts + 8_000_000_000_000 * 32
        xs = np.arange(ts, te, 8_000_000_000_000, dtype=np.uint64)
        ys = np.sin(np.linspace(-1, 1, len(xs)))
        # A 2col x 2row canvas
        self.core_canvas = Canvas(2, 2, title=os.path.basename(__file__))

        # A plot in top-left with 1 signal.
        signal11 = SignalXY(label="Signal1.1", hi_precision_data=False)
        signal11.set_data([xs, ys])
        plot11 = PlotXY(plot_title="DateTime=True, HiPrecision=False")
        plot11.axes[0].is_date = True
        plot11.add_signal(signal11)
        self.core_canvas.add_plot(plot11, 0)

        # A plot in bottom-left with 2 stacked signal.
        signal121 = SignalXY(label="Signal1.2.1")
        signal121.set_data([xs, ys])
        plot12 = PlotXY(plot_title="DateTime=True, HiPrecision=False", axes=[LinearAxis(), [LinearAxis(), LinearAxis()]])
        plot12.axes[0].is_date = True
        plot12.add_signal(signal121)
        signal122 = SignalXY(label="Signal1.2.2")
        signal122.set_data([xs, ys + np.sin(xs)])
        plot12.add_signal(signal122, 2)
        self.core_canvas.add_plot(plot12, 0)

        # A plot in top-right with 1 signal.
        signal21 = SignalXY(label="Signal2.1")
        signal21.set_data([xs, ys])
        plot21 = PlotXY(plot_title="DateTime=True, HiPrecision=False")
        plot21.axes[0].is_date = True
        plot21.add_signal(signal21)
        self.core_canvas.add_plot(plot21, 1)

        # A plot in bottom-right with 1 signal.
        signal22 = SignalXY(label="Signal2.2")
        signal22.set_data([xs, ys])
        plot22 = PlotXY(plot_title="DateTime=False, HiPrecision=False")
        plot22.add_signal(signal22)
        self.core_canvas.add_plot(plot22, 1)


    @unittest.skipIf(vtk_is_headless(), "VTK was built in headless mode.")
    def test_08_datetime_tics_simple_visuals_vtk(self):
        self.canvas = QtVTKCanvas()
        self.tst_08_datetime_tics_simple_visuals()

    @unittest.skipIf(matplotlib_is_headless(), "Matplotlib was built in headless mode.")
    def test_08_datetime_tics_simple_visuals_matplotlib(self):
        self.canvas = QtMatplotlibCanvas()
        self.tst_08_datetime_tics_simple_visuals()

    def tst_08_datetime_tics_simple_visuals(self):
        self.canvas.setFixedSize(800, 800)
        self.canvas.set_canvas(self.core_canvas)
        self.canvas.update()
        self.canvas.show()

        test_image_name = f"{self.id().split('.')[-1]}.png"
        test_image_path = os.path.join(os.path.dirname(__file__), "baseline", test_image_name)
        self.canvas._parser.export_image(test_image_path, canvas=self.core_canvas)
        self.assertTrue(regression_test2(test_image_path))


if __name__ == "__main__":
    unittest.main()
