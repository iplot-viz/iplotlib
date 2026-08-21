"""Data-request behavior of interactive panning, on both backends.

Every intermediate range of a pan drag used to update the requested range of
every signal in the shared-time group, and a source that decimates server-side
answers each of those with a real query, flooding the archive with windows
nobody looks at. Deferring the range update is what avoids that, but the
signals must still be redrawn on every move: a source that already holds the
whole pulse in memory has nothing to request, and skipping its redraw is what
left those plots empty during the drag.

These tests drive the backend range APIs the way a drag does (see
test_interactions.py for why raw mouse simulation is not viable offscreen) and
watch two calls per signal: ``set_limits``, which moves the range that feeds
the data hash and therefore the data access, and ``get_data``, which is the
redraw reading whatever is in memory.
"""

import unittest

import numpy as np

from iplotlib.core.canvas import Canvas
from iplotlib.core.plot import PlotXY
from iplotlib.core.signal import SignalXY
from iplotlib.qt.gui.iplotQtCanvasFactory import IplotQtCanvasFactory
from iplotlib.qt.testing import ensure_qapp

BACKENDS = ('matplotlib', 'pyqt')
T0, T1 = 0.0, 100.0


def _make_canvas() -> Canvas:
    core = Canvas(1, 1, title="pan-requests")
    x = np.linspace(T0, T1, 200)
    plot = PlotXY()
    for label in ("a", "b"):
        signal = SignalXY(label=label)
        signal.set_data([x, np.sin(x)])
        plot.add_signal(signal)
    core.add_plot(plot, 0)
    return core


def _first_impl_plot(qt_canvas, core_plot):
    impl_plots = qt_canvas._parser._plot_impl_plot_lut.get(id(core_plot), [])
    return impl_plots[0] if impl_plots else None


def _set_x_range(backend: str, impl, low: float, high: float) -> None:
    """Move the view the way a drag does, through the backend's own API."""
    if backend == 'pyqt':
        impl.getViewBox().setXRange(low, high, padding=0)
    else:
        impl.set_xlim(low, high)


class _Watch:
    """Counts set_limits/get_data per signal without altering their behaviour."""

    def __init__(self, signals):
        self.ranges = []
        self.redraws = 0
        self._originals = []
        for signal in signals:
            self._wrap(signal, 'set_limits', lambda args: self.ranges.append(tuple(args[0])))
            self._wrap(signal, 'get_data', lambda args: self._count())

    def _count(self):
        self.redraws += 1

    def _wrap(self, obj, name, hook):
        original = getattr(obj, name)

        def wrapper(*args, **kwargs):
            hook(args)
            return original(*args, **kwargs)

        setattr(obj, name, wrapper)
        self._originals.append((obj, name, original))

    def reset(self):
        self.ranges.clear()
        self.redraws = 0

    def restore(self):
        for obj, name, original in self._originals:
            setattr(obj, name, original)


class PanDataRequestTest(unittest.TestCase):
    """A pan drag requests data once, on release, and never stops redrawing."""

    def setUp(self):
        self.app = ensure_qapp()

    def _drive_pan(self, backend):
        """Run a three-step drag and return the watcher and the final window."""
        core = _make_canvas()
        qt_canvas = IplotQtCanvasFactory.new(backend, canvas=core)
        qt_canvas.set_canvas(core)
        self.app.processEvents()

        plot = core.plots[0][0]
        impl_plot = _first_impl_plot(qt_canvas, plot)
        self.assertIsNotNone(impl_plot, f"no impl plot for {backend}")

        parser = qt_canvas._parser
        signals = [ref() for ref in parser._impl_plot_cache_table.get_cache_item(impl_plot).signals]
        watch = _Watch(signals)
        self.addCleanup(watch.restore)

        parser.begin_interactive_pan()
        window = None
        for step in (1, 2, 3):
            window = (T0 + 10.0 * step, T1 + 10.0 * step)
            _set_x_range(backend, impl_plot, *window)
            self.app.processEvents()
        return parser, watch, window, len(signals)

    def test_drag_redraws_without_moving_the_requested_range(self):
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                _, watch, _, n_signals = self._drive_pan(backend)
                self.assertEqual([], watch.ranges,
                                 "a pan in progress must not move the requested range")
                self.assertGreaterEqual(watch.redraws, n_signals,
                                        "every signal must still be redrawn while panning")

    def test_release_requests_the_final_window_once_per_signal(self):
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                parser, watch, window, n_signals = self._drive_pan(backend)
                watch.reset()

                self.assertTrue(parser.end_interactive_pan(),
                                "the deferred update must be flushed on release")
                self.app.processEvents()

                self.assertEqual(n_signals, len(watch.ranges),
                                 "release must move the requested range once per signal")
                for requested in watch.ranges:
                    self.assertAlmostEqual(window[0], requested[0], places=6)
                    self.assertAlmostEqual(window[1], requested[1], places=6)

    def test_release_without_a_pan_does_nothing(self):
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                core = _make_canvas()
                qt_canvas = IplotQtCanvasFactory.new(backend, canvas=core)
                qt_canvas.set_canvas(core)
                self.app.processEvents()

                parser = qt_canvas._parser
                parser.begin_interactive_pan()
                self.assertFalse(parser.end_interactive_pan(),
                                 "a drag that changed no range has nothing to flush")


if __name__ == '__main__':
    unittest.main()
