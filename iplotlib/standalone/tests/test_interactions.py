"""Interactive tests: programmatically drive pan/zoom on both backends.

Full mouse-event simulation (``QTest.mousePress``/``mouseMove``/``mouseRelease``)
is fragile on the offscreen platform because hit-testing depends on widget
geometry that is never actually laid out on screen.  Instead, these tests
invoke the public backend APIs that the interactive modes ultimately call
(``ViewBox.setRange`` for pyqtgraph, ``Axes.set_xlim`` for matplotlib) and
assert that the axis range is updated.  We also capture pixmaps before and
after the interaction to catch visual regressions of the backend's rendering
after a zoom/pan, not just the numerical range change.
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


class InteractionsTest(unittest.TestCase):
    def setUp(self) -> None:
        super().setUp()
        self.app = ensure_qapp()

    def _first_impl_plot(self, qt_canvas, core_plot):
        impl_plots = qt_canvas._parser._plot_impl_plot_lut.get(id(core_plot), [])
        self.assertGreater(len(impl_plots), 0,
                           "parser must register an implementation plot for the core plot")
        return impl_plots[0]

    def _grab_baseline(self, qt_canvas, name: str, backend: str) -> None:
        pixmap = qt_canvas.grab()
        self.assertFalse(pixmap.isNull())
        if backend == 'pyqt' and not sys.platform.startswith(PYQT_CANONICAL_PLATFORM):
            # Skip the pixmap diff on non-canonical platforms; numerical
            # assertions above already validated the interaction.
            return
        compare_pixmap_to_baseline(pixmap, os.path.join(BASELINE_DIR, f"{name}.png"),
                                   tol=BASELINE_TOLERANCE)

    def test_pyqtgraph_zoom_updates_viewbox_range(self):
        canvas = _make_canvas()
        qt_canvas = IplotQtCanvasFactory.new('pyqt', canvas=canvas)
        qt_canvas.set_canvas(canvas)
        qt_canvas.resize(800, 600)
        self.app.processEvents()
        self._grab_baseline(qt_canvas, "interaction_pyqt_before_zoom", 'pyqt')

        plot_item = self._first_impl_plot(qt_canvas, canvas.plots[0][0])
        vb = plot_item.getViewBox()
        before = list(vb.viewRange()[0])

        # Same call PlotItem makes internally when the user rubber-band zooms.
        vb.setXRange(before[0] + 2.0, before[1] - 2.0, padding=0)
        self.app.processEvents()

        after = list(vb.viewRange()[0])
        self.assertAlmostEqual(after[0], before[0] + 2.0, places=3)
        self.assertAlmostEqual(after[1], before[1] - 2.0, places=3)

        self._grab_baseline(qt_canvas, "interaction_pyqt_after_zoom", 'pyqt')

    def test_matplotlib_pan_updates_axes_xlim(self):
        canvas = _make_canvas()
        qt_canvas = IplotQtCanvasFactory.new('matplotlib', canvas=canvas)
        qt_canvas.set_canvas(canvas)
        qt_canvas.resize(800, 600)
        self.app.processEvents()
        self._grab_baseline(qt_canvas, "interaction_matplotlib_before_pan", 'matplotlib')

        ax = self._first_impl_plot(qt_canvas, canvas.plots[0][0])
        lo_before, hi_before = ax.get_xlim()
        shift = (hi_before - lo_before) * 0.25
        ax.set_xlim(lo_before + shift, hi_before + shift)
        self.app.processEvents()

        lo_after, hi_after = ax.get_xlim()
        self.assertAlmostEqual(lo_after, lo_before + shift, places=3)
        self.assertAlmostEqual(hi_after, hi_before + shift, places=3)

        self._grab_baseline(qt_canvas, "interaction_matplotlib_after_pan", 'matplotlib')


if __name__ == '__main__':
    unittest.main()
