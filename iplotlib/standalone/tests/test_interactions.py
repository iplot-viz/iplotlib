"""Interactive tests: programmatically drive pan/zoom on both backends.

Full mouse-event simulation (``QTest.mousePress``/``mouseMove``/``mouseRelease``)
is fragile on the offscreen platform because hit-testing depends on widget
geometry that is never actually laid out on screen. Instead, these tests
invoke the public backend APIs that the interactive modes ultimately call
(``ViewBox.setXRange`` for pyqtgraph, ``Axes.set_xlim`` for matplotlib) and
assert that the axis range is updated. We also capture pixmaps before and
after the interaction to catch visual regressions of the backend's
rendering after a zoom/pan, not just the numerical range change.

Both pan and zoom are exercised on both backends so the visual coverage
is symmetric.
"""

import os
import sys
import unittest

import numpy as np

from iplotlib.core.canvas import Canvas
from iplotlib.core.plot import PlotXY
from iplotlib.core.signal import SignalXY
from iplotlib.qt.gui.iplotQtCanvasFactory import IplotQtCanvasFactory
from iplotlib.qt.testing import compare_pixmap_to_baseline, ensure_qapp

ROOT = os.path.dirname(__file__)
BASELINE_DIR = os.path.join(ROOT, 'baseline')
BACKENDS = ('matplotlib', 'pyqt')
PYQT_CANONICAL_PLATFORM = 'linux'
BASELINE_TOLERANCE = 5.0


def _make_canvas() -> Canvas:
    core = Canvas(1, 1, title="interactions")
    x = np.linspace(0, 10, 200)
    plot = PlotXY()
    signal = SignalXY(label="s")
    signal.set_data([x, np.sin(x)])
    plot.add_signal(signal)
    core.add_plot(plot, 0)
    return core


def _first_impl_plot(qt_canvas, core_plot):
    impl_plots = qt_canvas._parser._plot_impl_plot_lut.get(id(core_plot), [])
    assert impl_plots, "parser must register an implementation plot for the core plot"
    return impl_plots[0]


def _set_x_range(backend: str, impl, low: float, high: float) -> None:
    """Call the backend-specific API that pan/zoom ultimately invoke."""
    if backend == 'pyqt':
        impl.getViewBox().setXRange(low, high, padding=0)
    else:
        impl.set_xlim(low, high)


def _get_x_range(backend: str, impl):
    if backend == 'pyqt':
        return tuple(impl.getViewBox().viewRange()[0])
    return impl.get_xlim()


class InteractionsTest(unittest.TestCase):
    def setUp(self) -> None:
        super().setUp()
        self.app = ensure_qapp()

    def _skip_pyqt_visual_on_non_linux(self, backend: str) -> bool:
        return backend == 'pyqt' and not sys.platform.startswith(PYQT_CANONICAL_PLATFORM)

    def _grab_and_diff(self, qt_canvas, name: str, backend: str) -> None:
        pixmap = qt_canvas.grab()
        self.assertFalse(pixmap.isNull())
        if self._skip_pyqt_visual_on_non_linux(backend):
            return
        compare_pixmap_to_baseline(pixmap, os.path.join(BASELINE_DIR, f"{name}.png"),
                                   tol=BASELINE_TOLERANCE)

    def _build(self, backend: str):
        canvas = _make_canvas()
        qt_canvas = IplotQtCanvasFactory.new(backend, canvas=canvas)
        qt_canvas.set_canvas(canvas)
        qt_canvas.resize(800, 600)
        self.app.processEvents()
        return canvas, qt_canvas

    def test_pan_updates_x_range(self):
        """Pan shifts both limits by the same amount; output must re-render."""
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                canvas, qt_canvas = self._build(backend)
                self._grab_and_diff(qt_canvas, f"interaction_{backend}_before_pan", backend)

                impl = _first_impl_plot(qt_canvas, canvas.plots[0][0])
                lo_before, hi_before = _get_x_range(backend, impl)
                shift = (hi_before - lo_before) * 0.25
                _set_x_range(backend, impl, lo_before + shift, hi_before + shift)
                self.app.processEvents()

                lo_after, hi_after = _get_x_range(backend, impl)
                self.assertAlmostEqual(lo_after, lo_before + shift, places=3)
                self.assertAlmostEqual(hi_after, hi_before + shift, places=3)

                self._grab_and_diff(qt_canvas, f"interaction_{backend}_after_pan", backend)

    def test_zoom_updates_x_range(self):
        """Zoom shrinks the range symmetrically; output must re-render."""
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                canvas, qt_canvas = self._build(backend)
                self._grab_and_diff(qt_canvas, f"interaction_{backend}_before_zoom", backend)

                impl = _first_impl_plot(qt_canvas, canvas.plots[0][0])
                lo_before, hi_before = _get_x_range(backend, impl)
                _set_x_range(backend, impl, lo_before + 2.0, hi_before - 2.0)
                self.app.processEvents()

                lo_after, hi_after = _get_x_range(backend, impl)
                self.assertAlmostEqual(lo_after, lo_before + 2.0, places=3)
                self.assertAlmostEqual(hi_after, hi_before - 2.0, places=3)

                self._grab_and_diff(qt_canvas, f"interaction_{backend}_after_zoom", backend)


if __name__ == '__main__':
    unittest.main()
