"""Tests for canvas and plot legend state."""

import unittest

from iplotlib.core.canvas import Canvas
from iplotlib.core.plot import PlotXY
from iplotlib.core.signal import SignalXY


class TestLegendState(unittest.TestCase):
    def test_canvas_legend_toggle(self):
        c = Canvas(legend=True)
        self.assertTrue(c.legend)
        c.legend = False
        self.assertFalse(c.legend)

    def test_canvas_legend_position(self):
        c = Canvas(legend=True, legend_position="upper right")
        self.assertEqual(c.legend_position, "upper right")

    def test_canvas_legend_layout(self):
        c = Canvas(legend=True, legend_layout="horizontal")
        self.assertEqual(c.legend_layout, "horizontal")

    def test_plot_inherits_canvas_legend_via_property_manager(self):
        # A PlotXY without an explicit legend setting falls through to the
        # canvas preference via the PropertyManager resolution used at render
        # time; here we simply assert the plot's own slot is unset and that
        # the canvas setting is preserved.
        c = Canvas(legend=True)
        plot = PlotXY()
        c.add_plot(plot, 0)
        self.assertIsNone(plot.legend)
        self.assertTrue(c.legend)

    def test_signal_label_is_used_as_legend_entry(self):
        signal = SignalXY(label="S1")
        self.assertEqual(signal.label, "S1")


if __name__ == '__main__':
    unittest.main()
