"""Workspace serialization roundtrip tests.

MINT persists and restores canvases through ``Canvas.to_dict`` /
``Canvas.from_dict`` (and ``to_json`` / ``from_json``). A silent break here
would lose the user's workspace on reload, so these tests lock in a few
invariants that exercise the core shape/data/plot-type paths.
"""

import json
import unittest

import numpy as np

from iplotlib.core.canvas import Canvas
from iplotlib.core.plot import PlotXY
from iplotlib.core.signal import SignalXY


def _build_sample_canvas() -> Canvas:
    c = Canvas(rows=2, cols=1, title="roundtrip", shared_x_axis=True,
               grid=True, legend=True)
    plot = PlotXY(plot_title="p0")
    s = SignalXY(label="signal_a", color="#ff0000")
    s.set_data([np.array([0.0, 1.0, 2.0]), np.array([0.0, 2.0, 4.0])])
    plot.add_signal(s)
    c.add_plot(plot, 0)
    return c


class TestWorkspaceRoundtrip(unittest.TestCase):
    def test_dict_roundtrip_preserves_shape(self):
        original = _build_sample_canvas()
        restored = Canvas.from_dict(original.to_dict())

        self.assertEqual(restored.rows, original.rows)
        self.assertEqual(restored.cols, original.cols)
        self.assertEqual(len(restored.plots), len(original.plots))
        self.assertEqual(len(restored.plots[0]), len(original.plots[0]))

    def test_dict_roundtrip_preserves_canvas_properties(self):
        original = _build_sample_canvas()
        restored = Canvas.from_dict(original.to_dict())

        self.assertEqual(restored.title, original.title)
        self.assertEqual(restored.shared_x_axis, original.shared_x_axis)
        self.assertEqual(restored.grid, original.grid)
        self.assertEqual(restored.legend, original.legend)

    def test_dict_roundtrip_preserves_plot_and_signal(self):
        original = _build_sample_canvas()
        restored = Canvas.from_dict(original.to_dict())

        restored_plot = restored.plots[0][0]
        self.assertIsInstance(restored_plot, PlotXY)
        self.assertEqual(restored_plot.plot_title, "p0")

        stacks = list(restored_plot.signals.values())
        self.assertEqual(len(stacks), 1)
        self.assertEqual(len(stacks[0]), 1)
        restored_signal = stacks[0][0]
        self.assertEqual(restored_signal.label, "signal_a")
        self.assertEqual(restored_signal.color, "#ff0000")

    def test_json_roundtrip(self):
        original = _build_sample_canvas()
        as_json = original.to_json()
        # to_json returns valid JSON
        parsed = json.loads(as_json)
        self.assertIsInstance(parsed, dict)

        restored = Canvas.from_json(as_json)
        self.assertEqual(restored.rows, original.rows)
        self.assertEqual(restored.cols, original.cols)
        self.assertEqual(restored.title, original.title)

    def test_empty_canvas_roundtrip(self):
        original = Canvas(rows=1, cols=1, title="empty")
        restored = Canvas.from_dict(original.to_dict())

        self.assertEqual(restored.rows, 1)
        self.assertEqual(restored.cols, 1)
        self.assertEqual(restored.title, "empty")


if __name__ == '__main__':
    unittest.main()
