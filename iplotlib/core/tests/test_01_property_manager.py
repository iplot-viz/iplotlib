from functools import partial
from iplotlib.core.signal import SignalXY, SignalContour
import unittest
from iplotlib.core.canvas import Canvas
from iplotlib.core.plot import PlotXY, PlotContour
from iplotlib.core.property_manager import PropertyManager


class TestPropertyManager(unittest.TestCase):
    def setUp(self) -> None:
        self.pm = PropertyManager()
        self.canvas = Canvas(
            font_size=24,
            font_color="#000000",
            tick_number=5,
            autoscale=True,
            background_color='#FF0000',
            legend=True,
            legend_position='upper right',
            legend_layout='horizontal',
            grid=False,
            log_scale=False,
            line_style="Solid",
            line_size=4,
            marker='x',
            marker_size=8,
            step="steps-mid",
            contour_filled=True,
            legend_format='color_bar',
            equivalent_units=False,
            color_map='plasma',
            contour_levels=8,
            mouse_mode=Canvas.MOUSE_MODE_SELECT,
            crosshair_enabled=False,
            crosshair_color="red",
            crosshair_line_width=1,
            crosshair_horizontal=True,
            crosshair_vertical=True,
            crosshair_per_plot=False,
            streaming=False,
            shared_x_axis=False,
            auto_refresh=0
        )
        super().setUp()

    def tearDown(self) -> None:
        self.canvas.plots[0].clear()
        return super().tearDown()

    def test_plot_xy_inherits_canvas_properties(self):
        plot = PlotXY()
        self.canvas.add_plot(plot)

        f = partial(self.pm.get_value, plot)

        self.assertEqual(f("font_size"), self.canvas.font_size)
        self.assertEqual(f("font_color"), self.canvas.font_color)
        self.assertEqual(f("tick_number"), self.canvas.tick_number)
        self.assertEqual(f("background_color"), self.canvas.background_color)
        self.assertEqual(f("legend"), self.canvas.legend)
        self.assertEqual(f("legend_position"), self.canvas.legend_position)
        self.assertEqual(f("legend_layout"), self.canvas.legend_layout)
        self.assertEqual(f("grid"), self.canvas.grid)
        self.assertEqual(f("log_scale"), self.canvas.log_scale)
        self.assertEqual(f("line_style"), self.canvas.line_style)
        self.assertEqual(f("line_size"), self.canvas.line_size)
        self.assertEqual(f("marker"), self.canvas.marker)
        self.assertEqual(f("marker_size"), self.canvas.marker_size)
        self.assertEqual(f("step"), self.canvas.step)

    def test_plot_contour_inherits_canvas_properties(self):
        plot = PlotContour()
        self.canvas.add_plot(plot)

        f = partial(self.pm.get_value, plot)

        self.assertEqual(f("font_size"), self.canvas.font_size)
        self.assertEqual(f("font_color"), self.canvas.font_color)
        self.assertEqual(f("tick_number"), self.canvas.tick_number)
        self.assertEqual(f("background_color"), self.canvas.background_color)
        self.assertEqual(f("legend"), self.canvas.legend)
        self.assertEqual(f("legend_position"), self.canvas.legend_position)
        self.assertEqual(f("legend_layout"), self.canvas.legend_layout)
        self.assertEqual(f("grid"), self.canvas.grid)
        self.assertEqual(f("log_scale"), self.canvas.log_scale)
        self.assertEqual(f("contour_filled"), self.canvas.contour_filled)
        self.assertEqual(f("legend_format"), self.canvas.legend_format)
        self.assertEqual(f("equivalent_units"), self.canvas.equivalent_units)
        self.assertEqual(f("color_map"), self.canvas.color_map)
        self.assertEqual(f("contour_levels"), self.canvas.contour_levels)

    def test_axis_inherits_canvas_properties(self):
        plot = PlotXY()
        self.canvas.add_plot(plot)

        for ax in plot.axes:
            f = partial(self.pm.get_value, ax[0] if isinstance(ax, list) else ax)
            self.assertEqual(f("font_color"), self.canvas.font_color)
            self.assertEqual(f("font_size"), self.canvas.font_size)
            self.assertEqual(f("tick_number"), self.canvas.tick_number)
            self.assertEqual(f("autoscale"), self.canvas.autoscale)

    def test_signal_xy_inherits_plot_properties(self):
        plot = PlotXY()
        signal = SignalXY()
        plot.add_signal(signal)
        self.canvas.add_plot(plot)

        f = partial(self.pm.get_value, signal)

        self.assertEqual(f("line_style"), self.canvas.line_style)
        self.assertEqual(f("line_size"), self.canvas.line_size)
        self.assertEqual(f("marker"), self.canvas.marker)
        self.assertEqual(f("marker_size"), self.canvas.marker_size)
        self.assertEqual(f("step"), self.canvas.step)

    def test_signal_contour_inherits_plot_properties(self):
        plot = PlotContour()
        signal = SignalContour()
        plot.add_signal(signal)
        self.canvas.add_plot(plot)

        f = partial(self.pm.get_value, signal)

        self.assertEqual(f("color_map"), self.canvas.color_map)
        self.assertEqual(f("contour_levels"), self.canvas.contour_levels)


if __name__ == "__main__":
    unittest.main()
