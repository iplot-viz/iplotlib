"""Unit tests for the Plot hierarchy (PlotXY, PlotContour, PlotImage)."""

import unittest

import numpy as np
from iplotlib.core.plot import PlotXY, PlotContour, PlotImage
from iplotlib.core.signal import SignalXY


class TestPlotXY(unittest.TestCase):
    def test_add_signal_default_stack(self):
        plot = PlotXY()
        s = SignalXY(label="s")
        plot.add_signal(s)
        self.assertIn(1, plot.signals)
        self.assertEqual(plot.signals[1], [s])

    def test_add_multiple_signals_in_different_stacks(self):
        plot = PlotXY()
        s1 = SignalXY(label="s1")
        s2 = SignalXY(label="s2")
        plot.add_signal(s1, stack=1)
        plot.add_signal(s2, stack=2)
        self.assertEqual(len(plot.signals), 2)
        self.assertIs(plot.signals[1][0], s1)
        self.assertIs(plot.signals[2][0], s2)

    def test_stacked_signals_in_same_stack(self):
        plot = PlotXY()
        s1 = SignalXY(label="s1")
        s2 = SignalXY(label="s2")
        plot.add_signal(s1, stack=1)
        plot.add_signal(s2, stack=1)
        self.assertEqual(len(plot.signals[1]), 2)

    def test_signal_parent_is_weakref_to_plot(self):
        plot = PlotXY()
        s = SignalXY(label="s")
        plot.add_signal(s)
        self.assertIs(s.parent(), plot)


class TestPlotContour(unittest.TestCase):
    def test_contour_has_axes(self):
        plot = PlotContour()
        self.assertEqual(len(plot.axes), 2)


class TestPlotImage(unittest.TestCase):
    def test_image_has_axes(self):
        plot = PlotImage()
        self.assertEqual(len(plot.axes), 2)


if __name__ == '__main__':
    unittest.main()
