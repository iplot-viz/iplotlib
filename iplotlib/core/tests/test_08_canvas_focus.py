"""Unit tests for canvas focus_plot and full_mode_all_stack state."""

import unittest

from iplotlib.core.canvas import Canvas
from iplotlib.core.plot import PlotXY


class TestCanvasFocus(unittest.TestCase):
    def test_focus_plot_defaults_to_none(self):
        c = Canvas()
        self.assertIsNone(c.focus_plot)

    def test_focus_plot_can_be_assigned(self):
        c = Canvas()
        plot = PlotXY()
        c.add_plot(plot, 0)
        c.focus_plot = plot
        self.assertIs(c.focus_plot, plot)

    def test_full_mode_all_stack_default(self):
        c = Canvas()
        self.assertIsNone(c.full_mode_all_stack)

    def test_full_mode_all_stack_toggle(self):
        c = Canvas()
        c.full_mode_all_stack = True
        self.assertTrue(c.full_mode_all_stack)
        c.full_mode_all_stack = False
        self.assertFalse(c.full_mode_all_stack)


if __name__ == '__main__':
    unittest.main()
