"""Pipeline tests for the Qt canvas backends.

These exercise code paths that the static rendering tests don't hit:

- consecutive ``set_canvas`` calls (rebuild / cleanup paths),
- mutating a Canvas after the first draw (changing a preference, adding
  a signal) and re-drawing,
- swapping one Canvas for a different one on a live qt_canvas.

Each test renders once, mutates, renders again, and asserts the final
pixmap is non-null (no pixel diffing — that's ``test_rendering.py``'s
job). Running on both backends exercises both parsers'
``process_ipl_canvas`` / ``process_ipl_signal`` / cleanup paths, which
is why this file is safe to run on any platform: it checks behaviour,
not visual output.
"""

import os
import unittest

import numpy as np

from iplotlib.core.canvas import Canvas
from iplotlib.core.plot import PlotXY
from iplotlib.core.signal import SignalXY
from iplotlib.qt.gui.iplotQtCanvasFactory import IplotQtCanvasFactory
from iplotlib.qt.testing import ensure_qapp

BACKENDS = ('matplotlib', 'pyqt')

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')


def _make_canvas(title: str = "pipeline", n_signals: int = 1) -> Canvas:
    core = Canvas(1, 1, title=title)
    x = np.linspace(0, 10, 200)
    plot = PlotXY()
    for i in range(n_signals):
        sig = SignalXY(label=f"s{i}")
        sig.set_data([x, np.sin(x + i)])
        plot.add_signal(sig)
    core.add_plot(plot, 0)
    return core


class BackendPipelineTest(unittest.TestCase):
    def setUp(self) -> None:
        super().setUp()
        self.app = ensure_qapp()

    def _build(self, backend: str, canvas: Canvas):
        qt_canvas = IplotQtCanvasFactory.new(backend, canvas=canvas)
        qt_canvas.set_canvas(canvas)
        qt_canvas.resize(800, 600)
        self.app.processEvents()
        return qt_canvas

    def test_set_canvas_is_idempotent(self):
        """Calling set_canvas twice with the same Canvas must not raise or blank."""
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                canvas = _make_canvas("idempotent")
                qt_canvas = self._build(backend, canvas)

                qt_canvas.set_canvas(canvas)
                self.app.processEvents()

                pm = qt_canvas.grab()
                self.assertFalse(pm.isNull())
                self.assertGreater(pm.width(), 0)

    def test_replace_canvas_with_a_different_one(self):
        """Swapping the Canvas on a live qt_canvas rebuilds cleanly."""
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                first = _make_canvas("first", n_signals=1)
                second = _make_canvas("second", n_signals=3)
                qt_canvas = self._build(backend, first)

                qt_canvas.set_canvas(second)
                self.app.processEvents()

                self.assertIs(qt_canvas.get_canvas(), second)
                pm = qt_canvas.grab()
                self.assertFalse(pm.isNull())

    def test_mutate_preference_then_redraw(self):
        """Flipping grid off after the first draw must re-render."""
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                canvas = _make_canvas("mutate_grid")
                canvas.grid = True
                qt_canvas = self._build(backend, canvas)

                canvas.grid = False
                qt_canvas.set_canvas(canvas)
                self.app.processEvents()

                pm = qt_canvas.grab()
                self.assertFalse(pm.isNull())

    def test_add_signal_after_first_draw(self):
        """Adding a signal to an existing plot and redrawing is supported."""
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                canvas = _make_canvas("add_signal")
                qt_canvas = self._build(backend, canvas)

                plot = canvas.plots[0][0]
                x = np.linspace(0, 10, 200)
                extra = SignalXY(label="extra")
                extra.set_data([x, np.cos(x)])
                plot.add_signal(extra)
                qt_canvas.set_canvas(canvas)
                self.app.processEvents()

                pm = qt_canvas.grab()
                self.assertFalse(pm.isNull())


if __name__ == '__main__':
    unittest.main()
