from functools import partial
from iplotlib.core.signal import SimpleSignal
import unittest
from iplotlib.core.canvas import Canvas
from iplotlib.core.plot import PlotXY
from iplotlib.core.property_manager import PropertyManager


class TestPropertyManager(unittest.TestCase):
    def setUp(self) -> None:
        self.pm = PropertyManager()
        self.canvas = Canvas(
            font_size=24,
            font_color="#000000",
            line_style="solid",
            line_size=4,
            marker='x',
            marker_size=8,
            step="steps-mid",
            hi_precision_data=True,
            dec_samples=1000,
            legend=True,
            grid=False,
            mouse_mode=Canvas.MOUSE_MODE_SELECT,
            crosshair_enabled=False,
            crosshair_color="red",
            crosshair_line_width=1,
            crosshair_horizontal=True,
            crosshair_vertical=True,
            crosshair_per_plot=False,
            streaming=False,
            shared_x_axis=False,
            autoscale=True,
            auto_refresh=0
        )
        super().setUp()

    def tearDown(self) -> None:
        self.canvas.plots[0].clear()
        return super().tearDown()

    def test_plot_inherits_canvas_properties(self):
        plot = PlotXY()

        self.canvas.add_plot(plot)
        f = partial(self.pm.get_value, canvas=self.canvas, plot=plot)

        self.assertEqual(f("font_size"), self.canvas.font_size)
        self.assertEqual(f("font_color"), self.canvas.font_color)
        self.assertEqual(f("legend"), self.canvas.legend)
        self.assertEqual(f("grid"), self.canvas.grid)
        self.assertEqual(f("line_style"), self.canvas.line_style)
        self.assertEqual(f("line_size"), self.canvas.line_size)
        self.assertEqual(f("marker"), self.canvas.marker)
        self.assertEqual(f("marker_size"), self.canvas.marker_size)
        self.assertEqual(f("step"), self.canvas.step)
        self.assertEqual(f("dec_samples"), self.canvas.dec_samples)

    def test_axis_inherits_canvas_properties(self):
        plot = PlotXY()

        self.canvas.add_plot(plot)

        for ax in plot.axes:
            f = partial(self.pm.get_value, canvas=self.canvas, plot=plot, axis=ax)
            self.assertEqual(f("font_color"), self.canvas.font_color)
            self.assertEqual(f("font_size"), self.canvas.font_size)

    def test_signal_inherits_plot_properties(self):
        plot = PlotXY()
        signal = SimpleSignal()
        plot.add_signal(signal)

        f = partial(self.pm.get_value, canvas=self.canvas, plot=plot, signal=signal)

        self.assertEqual(f("line_style"), self.canvas.line_style)
        self.assertEqual(f("line_size"), self.canvas.line_size)
        self.assertEqual(f("marker"), self.canvas.marker)
        self.assertEqual(f("marker_size"), self.canvas.marker_size)
        self.assertEqual(f("step"), self.canvas.step)


if __name__ == "__main__":
    unittest.main()
