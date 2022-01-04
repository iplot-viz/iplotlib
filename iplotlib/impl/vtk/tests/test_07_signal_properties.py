import numpy as np
import os
import unittest
from iplotlib.core.canvas import Canvas
from iplotlib.core.plot import PlotXY
from iplotlib.core.signal import SimpleSignal
from iplotlib.impl.vtk.utils import regression_test
from iplotlib.impl.vtk.tests.QVTKAppTestAdapter import QVTKAppTestAdapter
from iplotlib.impl.vtk.tests.vtk_hints import vtk_is_headless


class VTKCanvasTesting(QVTKAppTestAdapter):

    def setUp(self) -> None:

        # A 1col x 6row canvas
        self.core_canvas = Canvas(6, 1, title=os.path.basename(__file__), legend=True, grid=True)

        n_samples = 10
        x_lo_prec = np.linspace(0, 2 * np.math.pi, n_samples, dtype=np.float32)
        y_lo_prec = np.sin(x_lo_prec)

        # A plot with 5 signals for color testing
        colors = ["blue", "chocolate", "orange_red",
                  "cadmium_yellow", "emerald_green"]
        plot = PlotXY(title="Color")
        for i in range(5):
            signal = SimpleSignal(
                label=f"{colors[i]}",
                color=colors[i],
                hi_precision_data=False
            )
            signal.set_data([x_lo_prec, y_lo_prec + np.array([i] * n_samples)])
            plot.add_signal(signal)
        self.core_canvas.add_plot(plot)

        # A plot with 3 signals for line style testing
        line_styles = ["solid", "dashed", "dotted"]
        plot = PlotXY(title="LineStyle")
        for i in range(3):
            signal = SimpleSignal(
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
        plot = PlotXY(title="LineSize")
        for i in range(3):
            signal = SimpleSignal(
                label=f"LineSize-{line_sizes[i]}",
                color=colors[i],
                line_size=line_sizes[i],
                hi_precision_data=False
            )
            signal.set_data([x_lo_prec, y_lo_prec + np.array([i] * n_samples)])
            plot.add_signal(signal)
        self.core_canvas.add_plot(plot)

        # A plot with 5 signals for marker-style testing
        markers = ['x', 'o', 'square', 'diamond', 'circle']
        plot = PlotXY(title="Marker")
        for i in range(5):
            signal = SimpleSignal(
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
        plot = PlotXY(title="MarkerSize")
        for i in range(3):
            signal = SimpleSignal(
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
        plot = PlotXY(title="Step")
        for i in range(4):
            signal = SimpleSignal(
                label=f"{step_types[i]}",
                color=colors[i],
                marker='x',
                step=step_types[i],
                hi_precision_data=False
            )
            signal.set_data([x_lo_prec, y_lo_prec + np.array([i] * n_samples)])
            plot.add_signal(signal)
        self.core_canvas.add_plot(plot)

        return super().setUp()

    def tearDown(self):
        return super().tearDown()

    @unittest.skipIf(vtk_is_headless(), "VTK was built in headless mode.")
    def test_07_signal_properties_refresh(self):
        self.canvas.set_canvas(self.core_canvas)

    @unittest.skipIf(vtk_is_headless(), "VTK was built in headless mode.")
    def test_07_signal_properties_visuals(self):

        self.canvas.set_canvas(self.core_canvas)
        self.canvas.update()
        self.canvas.show()
        self.canvas.get_render_widget().Initialize()
        self.canvas.get_render_widget().Render()

        renWin = self.canvas.get_render_widget().GetRenderWindow()
        valid_image_name = os.path.basename(__file__).replace(
            "test", "valid").replace(".py", ".png")
        valid_image_path = os.path.join(os.path.join(
            os.path.dirname(__file__), "baseline"), valid_image_name)
        self.assertTrue(regression_test(valid_image_path, renWin))


if __name__ == "__main__":
    unittest.main()
