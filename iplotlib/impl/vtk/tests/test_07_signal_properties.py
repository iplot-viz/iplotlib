import numpy as np
import os
import unittest
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
        # A 1col x 6row canvas
        self.core_canvas = Canvas(6, 1, title=os.path.basename(__file__), legend=True, grid=True)

        n_samples = 10
        x_lo_prec = np.linspace(0, 2 * np.pi, n_samples, dtype=np.float32)
        y_lo_prec = np.sin(x_lo_prec)

        # A plot with 5 signals for color testing
        colors = ["blue", "red", "orange", "yellow", "green"]
        plot = PlotXY(plot_title="Color")
        for i in range(5):
            signal = SignalXY(
                label=f"{colors[i]}",
                color=colors[i],
                hi_precision_data=False
            )
            signal.set_data([x_lo_prec, y_lo_prec + np.array([i] * n_samples)])
            plot.add_signal(signal)
        self.core_canvas.add_plot(plot)

        # A plot with 3 signals for line style testing
        line_styles = ["solid", "dashed", "dotted"]
        plot = PlotXY(plot_title="LineStyle")
        for i in range(3):
            signal = SignalXY(
                label=f"{line_styles[i]}",
                color=colors[i],
                line_style=line_styles[i],
                hi_precision_data=False
            )
            signal.set_data([x_lo_prec, y_lo_prec + np.array([i] * n_samples)])
            plot.add_signal(signal)
        self.core_canvas.add_plot(plot)

        # A plot with 3 signals for line size testing
        line_sizes = [2, 3, 4]
        plot = PlotXY(plot_title="LineSize")
        for i in range(3):
            signal = SignalXY(
                label=f"LineSize-{line_sizes[i]}",
                color=colors[i],
                line_size=line_sizes[i],
                hi_precision_data=False
            )
            signal.set_data([x_lo_prec, y_lo_prec + np.array([i] * n_samples)])
            plot.add_signal(signal)
        self.core_canvas.add_plot(plot)

        # A plot with 5 signals for marker-style testing
        markers = ['x', 'o', 's', 'd', '+']
        plot = PlotXY(plot_title="Marker")
        for i in range(5):
            signal = SignalXY(
                label=f"{markers[i]}",
                color=colors[i],
                marker=markers[i],
                hi_precision_data=False
            )
            signal.set_data([x_lo_prec, y_lo_prec + np.array([i] * n_samples)])
            plot.add_signal(signal)
        self.core_canvas.add_plot(plot)

        # A plot with 3 signals for marker-size testing
        marker_sizes = [8, 12, 14]
        plot = PlotXY(plot_title="MarkerSize")
        for i in range(3):
            signal = SignalXY(
                label=f"{marker_sizes[i]}",
                color=colors[i],
                marker=markers[i],
                marker_size=marker_sizes[i],
                hi_precision_data=False
            )
            signal.set_data([x_lo_prec, y_lo_prec + np.array([i] * n_samples)])
            plot.add_signal(signal)
        self.core_canvas.add_plot(plot)

        # A plot with 3 signals to test various kind of stepping draw styles
        step_types = [None, "steps-mid", "steps-post", "steps-pre"]
        plot = PlotXY(plot_title="Step")
        for i in range(4):
            signal = SignalXY(
                label=f"{step_types[i]}",
                color=colors[i],
                marker='x',
                step=step_types[i],
                hi_precision_data=False
            )
            signal.set_data([x_lo_prec, y_lo_prec + np.array([i] * n_samples)])
            plot.add_signal(signal)
        self.core_canvas.add_plot(plot)

    @unittest.skipIf(vtk_is_headless(), "VTK was built in headless mode.")
    def test_07_signal_properties_visuals_vtk(self):
        self.canvas = QtVTKCanvas()
        self.tst_07_signal_properties_visuals()

    @unittest.skipIf(matplotlib_is_headless(), "Matplotlib was built in headless mode.")
    def test_07_signal_properties_visuals_matplotlib(self):
        self.canvas = QtMatplotlibCanvas()
        self.tst_07_signal_properties_visuals()

    def tst_07_signal_properties_visuals(self):
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
