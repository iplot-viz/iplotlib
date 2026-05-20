"""Unit tests for the iplotlib Canvas core object."""

import unittest

from iplotlib.core.canvas import Canvas
from iplotlib.core.plot import PlotXY
from iplotlib.core.signal import SignalXY


class TestCanvas(unittest.TestCase):
    def test_default_shape(self):
        c = Canvas()
        self.assertEqual(c.rows, 1)
        self.assertEqual(c.cols, 1)
        self.assertEqual(len(c.plots), 1)

    def test_custom_shape(self):
        c = Canvas(rows=3, cols=2)
        self.assertEqual(c.rows, 3)
        self.assertEqual(c.cols, 2)
        self.assertEqual(len(c.plots), 2)
        for col in c.plots:
            self.assertEqual(col, [])

    def test_add_plot_first_column(self):
        c = Canvas(rows=2, cols=2)
        plot = PlotXY()
        c.add_plot(plot, 0)
        self.assertIs(c.plots[0][0], plot)
        self.assertEqual(len(c.plots[1]), 0)

    def test_add_plot_out_of_range_column(self):
        c = Canvas(rows=1, cols=1)
        with self.assertRaises(Exception):
            c.add_plot(PlotXY(), col=5)

    def test_add_plot_exceeds_rows(self):
        c = Canvas(rows=1, cols=1)
        c.add_plot(PlotXY(), 0)
        with self.assertRaises(Exception):
            c.add_plot(PlotXY(), 0)

    def test_enable_crosshair_sets_state(self):
        c = Canvas()
        c.enable_crosshair(color="blue", linewidth=2, horizontal=True, vertical=False)
        self.assertTrue(c.crosshair_enabled)
        self.assertEqual(c.crosshair_color, "blue")
        self.assertEqual(c.crosshair_line_width, 2)
        self.assertTrue(c.crosshair_horizontal)
        self.assertFalse(c.crosshair_vertical)

    def test_set_mouse_mode(self):
        c = Canvas()
        c.set_mouse_mode(Canvas.MOUSE_MODE_PAN)
        self.assertEqual(c.mouse_mode, Canvas.MOUSE_MODE_PAN)

    def test_canvas_with_signals(self):
        c = Canvas(rows=1, cols=1)
        plot = PlotXY()
        signal = SignalXY(label="s")
        signal.set_data([[0, 1, 2], [0, 1, 4]])
        plot.add_signal(signal)
        c.add_plot(plot, 0)
        self.assertEqual(len(c.plots[0][0].signals), 1)


if __name__ == "__main__":
    unittest.main()
