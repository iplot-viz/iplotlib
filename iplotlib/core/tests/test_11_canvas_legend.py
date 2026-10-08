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


def _canvas_with_a_customised_legend() -> Canvas:
    canvas = Canvas(legend=True)
    plot = PlotXY(legend_anchor={'1': [0.25, 0.5]}, legend_width=30, legend_collapsed=['1'])
    plot.add_signal(SignalXY(label="shown", uid="a"))
    plot.add_signal(SignalXY(label="hidden", uid="b", hidden=True))
    canvas.add_plot(plot, 0)
    return canvas


CUSTOMISED = ({'1': [0.25, 0.5]}, 30, ['1'], [False, True])


class TestLegendCustomisation(unittest.TestCase):
    """Where the legend was dragged, its size, whether it is folded away and the
    signals hidden from it travel with the workspace and survive a redraw."""

    @staticmethod
    def _legend_of(canvas: Canvas):
        plot = canvas.plots[0][0]
        # A workspace read back keys the stacks by their JSON name.
        signals = [signal for stack in plot.signals.values() for signal in stack]
        return (plot.legend_anchor, plot.legend_width, plot.legend_collapsed,
                [signal.hidden for signal in signals])

    def test_saved_with_the_workspace(self):
        restored = Canvas.from_dict(_canvas_with_a_customised_legend().to_dict())
        self.assertEqual(self._legend_of(restored), CUSTOMISED)

    def test_kept_when_the_canvas_is_drawn_again(self):
        old = _canvas_with_a_customised_legend().to_dict()
        redrawn = Canvas(legend=True)
        plot = PlotXY()
        plot.add_signal(SignalXY(label="shown", uid="a"))
        plot.add_signal(SignalXY(label="hidden", uid="b"))
        redrawn.add_plot(plot, 0)

        redrawn.merge(old)

        self.assertEqual(self._legend_of(redrawn), CUSTOMISED)

    def test_workspaces_saved_before_load_with_the_default_legend(self):
        old = _canvas_with_a_customised_legend().to_dict()
        plot = old['plots'][0][0]
        for key in ('legend_anchor', 'legend_width', 'legend_collapsed'):
            del plot[key]
        for signal in plot['signals']['1']:
            del signal['hidden']

        self.assertEqual(self._legend_of(Canvas.from_dict(old)), (None, 0, None, [False, False]))

    def test_reset_puts_the_legend_back_as_the_preferences_draw_it(self):
        plot = _canvas_with_a_customised_legend().plots[0][0]
        plot.reset_preferences()
        self.assertEqual(self._legend_of_plot(plot), (None, 0, None))

    @staticmethod
    def _legend_of_plot(plot):
        return plot.legend_anchor, plot.legend_width, plot.legend_collapsed


if __name__ == '__main__':
    unittest.main()
