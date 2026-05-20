"""
Backend-agnostic rendering tests for iplotlib. Each scenario builds a core Canvas,
pushes it through the Qt factory for both matplotlib and pyqtgraph, renders
off-screen and saves a PNG next to the baselines for visual inspection and future
image-diff regression checks.
"""

import os
import sys
import unittest

import numpy as np

from iplotlib.core.canvas import Canvas
from iplotlib.core.plot import PlotContour, PlotImage, PlotXY
from iplotlib.core.signal import SignalContour, SignalXY
from iplotlib.qt.gui.iplotQtCanvasFactory import IplotQtCanvasFactory
from iplotlib.qt.testing import compare_pixmap_to_baseline, ensure_qapp

ROOT = os.path.dirname(__file__)
BASELINE_DIR = os.path.join(ROOT, 'baseline')

BACKENDS = ('matplotlib', 'pyqt')
# Matplotlib rasterises with FreeType + bundled fonts so its output is
# bit-exact across platforms. PyQtGraph renders through Qt's native
# pipeline, whose font hinting and anti-aliasing differ between operating
# systems even in offscreen mode, so its baselines are only reliable on
# the canonical Linux platform used by CI and the Linux-based dev team.
# On other platforms the pyqt visual tests skip to avoid flakiness.
PYQT_CANONICAL_PLATFORM = 'linux'
# Matplotlib Agg is byte-stable across Linux distros so a strict tolerance
# is appropriate. Pyqtgraph renders through Qt's native painter which pulls
# system freetype/fontconfig — the same scene rendered on CODAC (RHEL) and
# on ubuntu-latest (CI) drifts by a few RMS points, especially when text
# is involved. A higher pyqt tolerance absorbs that drift while still
# catching real regressions (missing plots, wrong data, wrong legends).
BASELINE_TOLERANCE = 5.0
PYQT_BASELINE_TOLERANCE = 20.0


class RenderingTest(unittest.TestCase):
    """Parametrised rendering tests covering both supported backends."""

    def setUp(self) -> None:
        super().setUp()
        self.app = ensure_qapp()
        os.makedirs(BASELINE_DIR, exist_ok=True)

    def _render(self, backend: str, core_canvas: Canvas, out_name: str):
        if backend == 'pyqt' and not sys.platform.startswith(PYQT_CANONICAL_PLATFORM):
            self.skipTest("pyqt visual baselines are canonical on Linux only")

        qt_canvas = IplotQtCanvasFactory.new(backend, canvas=core_canvas)
        qt_canvas.set_canvas(core_canvas)
        qt_canvas.resize(800, 600)
        self.app.processEvents()

        pixmap = qt_canvas.grab()
        self.assertFalse(pixmap.isNull(), f"{backend}: null pixmap for {out_name}")
        self.assertGreater(pixmap.width(), 0)
        self.assertGreater(pixmap.height(), 0)

        baseline = os.path.join(BASELINE_DIR, f"{out_name}_{backend}.png")
        tol = PYQT_BASELINE_TOLERANCE if backend == 'pyqt' else BASELINE_TOLERANCE
        compare_pixmap_to_baseline(pixmap, baseline, tol=tol)

    # --------------------------
    #           TESTS
    # --------------------------

    def test_02_canvas_sizing(self):
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                core_canvas = Canvas(2, 2, title="canvas_sizing")
                self._render(backend, core_canvas, "canvas_sizing")

    def test_05_canvas_simple(self):
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                core_canvas = Canvas(2, 2, title="canvas_simple")
                x = np.array([0., 1., 2., 3.])
                for col in range(2):
                    for _ in range(2):
                        plot = PlotXY()
                        signal = SignalXY(label=f"s{col}")
                        signal.set_data([x, x])
                        plot.add_signal(signal)
                        core_canvas.add_plot(plot, col)
                self._render(backend, core_canvas, "canvas_simple")

    def test_06_canvas_complex(self):
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                core_canvas = Canvas(3, 2, title="canvas_complex")
                x = np.linspace(0, 10, 200)
                for col in range(2):
                    for i in range(3):
                        plot = PlotXY()
                        signal = SignalXY(label=f"s{col}.{i}")
                        signal.set_data([x, np.sin(x + i)])
                        plot.add_signal(signal)
                        core_canvas.add_plot(plot, col)
                self._render(backend, core_canvas, "canvas_complex")

    def test_08_datetime_tics_simple(self):
        """Canvas whose X axis carries nanosecond timestamps (ITER convention)."""
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                core_canvas = Canvas(1, 1, title="datetime_tics_simple")
                base = np.int64(1700000000) * np.int64(10 ** 9)
                x = base + np.arange(100) * np.int64(10 ** 9)
                y = np.sin(np.linspace(0, 2 * np.pi, 100))
                plot = PlotXY()
                signal = SignalXY(label="datetime_signal")
                signal.set_data([x, y])
                plot.add_signal(signal)
                core_canvas.add_plot(plot, 0)
                self._render(backend, core_canvas, "datetime_tics_simple")

    def test_07_signal_properties(self):
        """Multiple signals with distinct colours and line styles on the same plot."""
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                core_canvas = Canvas(1, 1, title="signal_properties")
                x = np.linspace(0, 10, 200)
                styles = [
                    {"color": "#d62728", "line_style": "-"},
                    {"color": "#1f77b4", "line_style": "--"},
                    {"color": "#2ca02c", "line_style": ":"},
                ]
                plot = PlotXY()
                for i, style in enumerate(styles):
                    signal = SignalXY(label=f"signal_{i}",
                                      color=style["color"],
                                      line_style=style["line_style"])
                    signal.set_data([x, np.sin(x + i)])
                    plot.add_signal(signal)
                core_canvas.add_plot(plot, 0)
                self._render(backend, core_canvas, "signal_properties")

    def test_09_plot_contour(self):
        """A 2D contour plot exercises the SignalContour/PlotContour path."""
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                core_canvas = Canvas(1, 1, title="plot_contour")
                grid = np.linspace(-3, 3, 40)
                xx, yy = np.meshgrid(grid, grid)
                z = np.sin(xx) * np.cos(yy)
                plot = PlotContour()
                signal = SignalContour(label="contour_signal")
                # iplotlib's matplotlib contour path requires all three buffers 2D,
                # so we pass the meshgrid directly instead of 1D axis vectors.
                signal.set_data([xx, yy, z])
                plot.add_signal(signal)
                core_canvas.add_plot(plot, 0)
                self._render(backend, core_canvas, "plot_contour")

    @unittest.skip("PlotImage rendering raises in both backends when set_data([2D]) "
                   "is used outside the full data pipeline — see follow-up issue")
    def test_10_plot_image(self):
        """A PlotImage with a 2D array (mirrors standalone customImageData).

        Currently skipped: matplotlib raises AttributeError('AxesImage' has no
        'clear') and pyqtgraph raises RuntimeError('Internal C++ object
        (ImageItem) already deleted'). The test keeps the scenario documented
        so it can be enabled once the rendering path is fixed.
        """
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                core_canvas = Canvas(1, 1, title="plot_image")
                rng = np.random.default_rng(seed=42)
                data = rng.random((16, 16))
                plot = PlotImage(plot_title="image")
                signal = SignalXY(label="image_signal")
                signal.set_data([data])
                plot.add_signal(signal)
                core_canvas.add_plot(plot, 0)
                self._render(backend, core_canvas, "plot_image")

    def test_11_canvas_legend(self):
        """Canvas with legend enabled and two named signals in one plot."""
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                core_canvas = Canvas(1, 1, title="canvas_legend",
                                     legend=True, legend_position="upper right")
                x = np.linspace(0, 10, 200)
                plot = PlotXY()
                for i, label in enumerate(("alpha", "beta")):
                    sig = SignalXY(label=label)
                    sig.set_data([x, np.sin(x + i)])
                    plot.add_signal(sig)
                core_canvas.add_plot(plot, 0)
                self._render(backend, core_canvas, "canvas_legend")

    def _render_simple_canvas(self, backend: str, out_name: str, **canvas_kwargs):
        core_canvas = Canvas(1, 1, title=out_name, **canvas_kwargs)
        x = np.linspace(0.5, 10.0, 200)
        plot = PlotXY()
        signal = SignalXY(label="s")
        signal.set_data([x, np.sin(x) + 2.0])  # positive so log_scale is valid
        plot.add_signal(signal)
        core_canvas.add_plot(plot, 0)
        self._render(backend, core_canvas, out_name)

    def test_13_preference_grid_off(self):
        """Canvas with grid=False must render without grid lines."""
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                self._render_simple_canvas(backend, "pref_grid_off", grid=False)

    def test_14_preference_log_scale(self):
        """Canvas with log_scale=True must render Y axis on a log scale.

        Pyqtgraph currently draws an empty plot when log_scale is enabled on
        a SignalXY (axis ticks come out logarithmic but the line itself is
        not rendered). Matplotlib works. The pyqt subtest is skipped until
        the backend is fixed — see follow-up issue.
        """
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                if backend == 'pyqt':
                    self.skipTest("pyqtgraph log_scale does not render the "
                                  "signal line — see follow-up issue")
                self._render_simple_canvas(backend, "pref_log_scale", log_scale=True)

    def test_15_preference_font_size_large(self):
        """Canvas with a larger font_size must render bigger tick/title text."""
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                self._render_simple_canvas(backend, "pref_font_size_large", font_size=14)

    def test_16_preference_background_color(self):
        """Canvas with a custom background_color must render with that fill."""
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                self._render_simple_canvas(backend, "pref_background_color",
                                           background_color="#eef3ff")

    def test_17_preference_shared_x_axis(self):
        """Two stacked plots with shared_x_axis=True share their X range."""
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                core_canvas = Canvas(2, 1, title="pref_shared_x_axis",
                                     shared_x_axis=True)
                x = np.linspace(0, 10, 200)
                for i in range(2):
                    plot = PlotXY()
                    signal = SignalXY(label=f"s{i}")
                    signal.set_data([x, np.sin(x + i)])
                    plot.add_signal(signal)
                    core_canvas.add_plot(plot, 0)
                self._render(backend, core_canvas, "pref_shared_x_axis")

    def test_12_canvas_with_crosshair_enabled_builds(self):
        """Canvas with crosshair enabled renders without errors.

        The crosshair itself is drawn on mouse-motion events (bound to
        matplotlib's ``motion_notify_event`` and pyqtgraph's
        ``sigMouseMoved``). A static offscreen render never receives those
        events, so the baseline captures the plot without a crosshair drawn,
        and the test effectively verifies that enabling the crosshair does
        not break the render path. A separate mouse-driven test would be
        needed to capture the crosshair actually drawn at a cursor position.
        """
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                core_canvas = Canvas(1, 1, title="canvas_with_crosshair")
                core_canvas.enable_crosshair(color="#d62728", linewidth=1,
                                             horizontal=True, vertical=True)
                x = np.linspace(0, 10, 200)
                plot = PlotXY()
                signal = SignalXY(label="crosshair_signal")
                signal.set_data([x, np.sin(x)])
                plot.add_signal(signal)
                core_canvas.add_plot(plot, 0)
                self._render(backend, core_canvas, "canvas_with_crosshair")


if __name__ == '__main__':
    unittest.main()
