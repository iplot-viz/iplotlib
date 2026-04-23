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


class HistoryChainTest(unittest.TestCase):
    """Chains of multiple commands plus drop_history on both backends."""

    def setUp(self) -> None:
        super().setUp()
        self.app = ensure_qapp()

    def _push_zoom(self, parser, factor_in: float):
        """Push a zoom command that narrows the X range by ``factor_in`` on each end."""
        current = parser.get_all_plot_limits()
        narrowed = copy.deepcopy(current)
        for src, dst in zip(current, narrowed):
            dst.plot_ref = src.plot_ref
            for s_src, s_dst in zip(src.signals_ranges, dst.signals_ranges):
                s_dst.signal_ref = s_src.signal_ref
        span = (current[0].axes_ranges[0].end
                - current[0].axes_ranges[0].begin)
        narrowed[0].axes_ranges[0].set_limits(
            current[0].axes_ranges[0].begin + span * factor_in,
            current[0].axes_ranges[0].end - span * factor_in)

        cmd = IplotAxesRangeCmd('Zoom', old_limits=current,
                                new_limits=narrowed, parser=parser)
        parser._hm.done(cmd)
        cmd()
        self.app.processEvents()
        return current

    def _scenario(self, backend: str):
        canvas = _make_canvas()
        qt_canvas = IplotQtCanvasFactory.new(backend, canvas=canvas)
        qt_canvas.set_canvas(canvas)
        qt_canvas.resize(800, 600)
        self.app.processEvents()
        return qt_canvas

    def test_chained_undo_walks_back_through_each_command(self):
        """Push Zoom₁ → Zoom₂ → undo twice returns to the original range."""
        for backend in ('matplotlib', 'pyqt'):
            with self.subTest(backend=backend):
                qt_canvas = self._scenario(backend)
                parser = qt_canvas._parser
                original = parser.get_all_plot_limits()[0].axes_ranges[0]
                original_begin, original_end = original.begin, original.end

                self._push_zoom(parser, 0.1)  # Zoom 1
                self._push_zoom(parser, 0.15)  # Zoom 2

                parser._hm.undo()
                parser._hm.undo()
                self.app.processEvents()

                restored = parser.get_all_plot_limits()[0].axes_ranges[0]
                self.assertAlmostEqual(restored.begin, original_begin, places=3)
                self.assertAlmostEqual(restored.end, original_end, places=3)

    def test_drop_history_disables_undo_and_redo(self):
        for backend in ('matplotlib', 'pyqt'):
            with self.subTest(backend=backend):
                qt_canvas = self._scenario(backend)
                parser = qt_canvas._parser

                self._push_zoom(parser, 0.2)
                self.assertTrue(qt_canvas.can_undo())

                qt_canvas.drop_history()
                self.app.processEvents()

                self.assertFalse(qt_canvas.can_undo())
                self.assertFalse(qt_canvas.can_redo())

    def test_undo_then_redo_returns_to_zoomed_state(self):
        """undo then redo of the same command restores the zoomed range."""
        for backend in ('matplotlib', 'pyqt'):
            with self.subTest(backend=backend):
                qt_canvas = self._scenario(backend)
                parser = qt_canvas._parser

                self._push_zoom(parser, 0.2)
                zoomed = parser.get_all_plot_limits()[0].axes_ranges[0]
                zb, ze = zoomed.begin, zoomed.end

                parser._hm.undo()
                self.app.processEvents()
                parser._hm.redo()
                self.app.processEvents()

                after = parser.get_all_plot_limits()[0].axes_ranges[0]
                self.assertAlmostEqual(after.begin, zb, places=3)
                self.assertAlmostEqual(after.end, ze, places=3)


if __name__ == '__main__':
    unittest.main()
