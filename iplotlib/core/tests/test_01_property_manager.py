from iplotlib.core.signal import ArraySignal
import unittest
from iplotlib.core.canvas import Canvas
from iplotlib.core.axis import LinearAxis
from iplotlib.core.plot import PlotXY
from iplotlib.core.property_manager import PropertyManager

class VTKCanvasTesting(unittest.TestCase):
    def setUp(self) -> None:
        self.prop_manager = PropertyManager()
        self.canvas = Canvas(
            font_size = 24,
            font_color = "black",
            line_style = "solid",
            line_size = 4,
            marker = 'x',
            marker_size = 8,
            step = "steps-mid",
            hi_precision_data = True,
            dec_samples = 1000,
            legend = True,
            grid = False,
            mouse_mode = Canvas.MOUSE_MODE_SELECT,
            crosshair_enabled = False,
            crosshair_color = "red",
            crosshair_line_width = 1,
            crosshair_horizontal = True,
            crosshair_vertical = True,
            crosshair_per_plot = False,
            streaming = False,
            shared_x_axis = False,
            autoscale = True,
            auto_refresh = 0
        )
        super().setUp()

    def tearDown(self) -> None:
        self.canvas.plots[0].clear()
        return super().tearDown()

    def test_plot_inherits_canvas_properties(self):
        plot = PlotXY()

        self.canvas.add_plot(plot)
        
        self.prop_manager.acquire_plot_from_canvas(self.canvas, plot)
        
        self.assertEqual(plot.font_size, self.canvas.font_size)
        self.assertEqual(plot.font_color, self.canvas.font_color)
        self.assertEqual(plot.legend, self.canvas.legend)
        self.assertEqual(plot.grid, self.canvas.grid)
        self.assertEqual(plot.line_style, self.canvas.line_style)
        self.assertEqual(plot.line_size, self.canvas.line_size)
        self.assertEqual(plot.marker, self.canvas.marker)
        self.assertEqual(plot.marker_size, self.canvas.marker_size)
        self.assertEqual(plot.step, self.canvas.step)
        self.assertEqual(plot.dec_samples, self.canvas.dec_samples)
    
    def test_axis_inherits_canvas_properties(self):

        plot = PlotXY()

        self.canvas.add_plot(plot)
        self.prop_manager.acquire_plot_from_canvas(self.canvas, plot)

        for ax in plot.axes:
            self.assertEqual(ax.font_color, self.canvas.font_color)
            self.assertEqual(ax.font_size, self.canvas.font_size)
    
    def test_signal_inherits_plot_properties(self):

        plot = PlotXY()
        signal = ArraySignal()
        plot.add_signal(signal)

        self.prop_manager.acquire_signal_from_plot(plot, signal)
        self.assertEqual(signal.line_style, plot.line_style)
        self.assertEqual(signal.line_size, plot.line_size)
        self.assertEqual(signal.marker, plot.marker)
        self.assertEqual(signal.marker_size, plot.marker_size)
        self.assertEqual(signal.step, plot.step)


if __name__ == "__main__":
    unittest.main()
