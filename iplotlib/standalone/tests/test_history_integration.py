"""Integration tests for IplotAxesRangeCmd + HistoryManager on a real backend.

The unit tests in ``core/tests/test_04_history_manager.py`` exercise the
stack mechanics with a dummy command. These tests exercise the real command
(``IplotAxesRangeCmd``) wired up to an actual backend parser, so undo/redo
is verified against real axis state rather than an in-memory log.
"""

import copy
import unittest

import numpy as np

from iplotlib.core.canvas import Canvas
from iplotlib.core.commands.axes_range import IplotAxesRangeCmd
from iplotlib.core.plot import PlotXY
from iplotlib.core.signal import SignalXY
from iplotlib.qt.gui.iplotQtCanvasFactory import IplotQtCanvasFactory
from iplotlib.qt.testing import ensure_qapp


def _make_canvas() -> Canvas:
    core = Canvas(1, 1, title="history_integration")
    x = np.linspace(0, 10, 200)
    plot = PlotXY()
    signal = SignalXY(label="s")
    signal.set_data([x, np.sin(x)])
    plot.add_signal(signal)
    core.add_plot(plot, 0)
    return core


class HistoryIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        super().setUp()
        self.app = ensure_qapp()

    def _scenario(self, backend: str):
        canvas = _make_canvas()
        qt_canvas = IplotQtCanvasFactory.new(backend, canvas=canvas)
        qt_canvas.set_canvas(canvas)
        qt_canvas.resize(800, 600)
        self.app.processEvents()

        parser = qt_canvas._parser
        initial_limits = parser.get_all_plot_limits()
        self.assertGreater(len(initial_limits), 0)

        original_x = (initial_limits[0].axes_ranges[0].begin,
                      initial_limits[0].axes_ranges[0].end)

        # Deep-copy the snapshot to produce a "zoomed" limits collection that
        # preserves plot_ref/signal_ref/slider_ref, then narrow the X range.
        zoomed = copy.deepcopy(initial_limits)
        # deepcopy does not copy weakrefs; restore them from the originals.
        for src, dst in zip(initial_limits, zoomed):
            dst.plot_ref = src.plot_ref
            for s_src, s_dst in zip(src.signals_ranges, dst.signals_ranges):
                s_dst.signal_ref = s_src.signal_ref
        span = original_x[1] - original_x[0]
        zoomed[0].axes_ranges[0].set_limits(original_x[0] + span * 0.25,
                                            original_x[1] - span * 0.25)

        cmd = IplotAxesRangeCmd('Zoom', old_limits=initial_limits,
                                new_limits=zoomed, parser=parser)
        parser._hm.done(cmd)
        cmd()  # apply the "new" zoomed limits
        self.app.processEvents()

        mid = parser.get_all_plot_limits()[0].axes_ranges[0]
        self.assertAlmostEqual(mid.begin, original_x[0] + span * 0.25, places=3)
        self.assertAlmostEqual(mid.end, original_x[1] - span * 0.25, places=3)

        parser._hm.undo()
        self.app.processEvents()

        restored = parser.get_all_plot_limits()[0].axes_ranges[0]
        self.assertAlmostEqual(restored.begin, original_x[0], places=3)
        self.assertAlmostEqual(restored.end, original_x[1], places=3)

    def test_matplotlib_zoom_undo(self):
        self._scenario('matplotlib')

    def test_pyqtgraph_zoom_undo(self):
        self._scenario('pyqt')


if __name__ == '__main__':
    unittest.main()
