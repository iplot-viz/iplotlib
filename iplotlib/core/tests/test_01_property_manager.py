from functools import partial
from iplotlib.core.signal import SignalXY, SignalContour
import unittest
from iplotlib.core.canvas import Canvas
from iplotlib.core.plot import PlotXY, PlotContour
from iplotlib.core.display import DisplayScale, MODE_FIXED, MODE_OFF
from iplotlib.core.property_manager import PropertyManager


class TestPropertyManager(unittest.TestCase):
    def setUp(self) -> None:
        DisplayScale.reset()
        # Pin the scale so the inheritance assertions below do not depend on the
        # screen the test suite happens to run on.
        DisplayScale.instance().configure(mode=MODE_OFF, force=True)
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
        DisplayScale.reset()
        return super().tearDown()

    def test_plot_xy_inherits_canvas_properties(self):
        plot = PlotXY()
        self.canvas.add_plot(plot)

        f = partial(self.pm.get_raw_value, plot)

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

        f = partial(self.pm.get_raw_value, plot)

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
            f = partial(self.pm.get_raw_value, ax[0] if isinstance(ax, list) else ax)
            self.assertEqual(f("font_color"), self.canvas.font_color)
            self.assertEqual(f("font_size"), self.canvas.font_size)
            self.assertEqual(f("tick_number"), self.canvas.tick_number)
            self.assertEqual(f("autoscale"), self.canvas.autoscale)

    def test_signal_xy_inherits_plot_properties(self):
        plot = PlotXY()
        signal = SignalXY()
        plot.add_signal(signal)
        self.canvas.add_plot(plot)

        f = partial(self.pm.get_raw_value, signal)

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

        f = partial(self.pm.get_raw_value, signal)

        self.assertEqual(f("color_map"), self.canvas.color_map)
        self.assertEqual(f("contour_levels"), self.canvas.contour_levels)


class TestPropertyManagerDisplayScale(unittest.TestCase):
    """get_value renders, get_raw_value persists."""

    def setUp(self) -> None:
        DisplayScale.reset()
        self.pm = PropertyManager()
        self.canvas = Canvas(font_size=8, line_size=1, tick_number=7)

    def tearDown(self) -> None:
        DisplayScale.reset()

    def test_fonts_are_scaled_for_rendering(self):
        DisplayScale.instance().configure(mode=MODE_FIXED, value=2.0, force=True)
        self.assertEqual(self.pm.get_value(self.canvas, "font_size"), 16)

    def test_line_size_is_not_scaled(self):
        # Its cost grows with the sample count: a pen wider than one pixel
        # leaves Qt's fast line path and makes large pyqtgraph plots crawl.
        DisplayScale.instance().configure(mode=MODE_FIXED, value=2.0, force=True)
        self.assertEqual(self.pm.get_value(self.canvas, "line_size"), 1)

    def test_non_size_properties_are_untouched(self):
        DisplayScale.instance().configure(mode=MODE_FIXED, value=2.0, force=True)
        self.assertEqual(self.pm.get_value(self.canvas, "tick_number"), 7)

    def test_raw_value_is_never_scaled(self):
        # What the preferences form shows and what gets written back to
        # default_properties.json, so it must stay screen-independent.
        DisplayScale.instance().configure(mode=MODE_FIXED, value=2.0, force=True)
        self.assertEqual(self.pm.get_raw_value(self.canvas, "font_size"), 8)


if __name__ == "__main__":
    unittest.main()
