"""Behaviour-level tests for the Qt canvas backends.

Complements the pixel-diff rendering tests with invariants that run on
both backends but do not require visual baselines:

- stats(canvas) computes and fills the stats table.
- autoscale_all_y() adjusts Y ranges without crashing.
- set_mouse_mode() accepts every Canvas.MOUSE_MODE_* constant and updates
  the internal state.
- reset() / refresh() cycle back to a valid canvas.
- enable_crosshair + processEvents round-trips through both backends.

These exercise paths in qtMatplotlibCanvas.py / qtPyQtGraphCanvas.py that
the static rendering tests don't reach.
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


def _canvas_with_noisy_signal() -> Canvas:
    """Canvas with a single plot whose Y range is non-trivial so autoscale
    / stats have something to work on."""
    core = Canvas(1, 1, title="backend_behaviour")
    x = np.linspace(0, 10, 200)
    plot = PlotXY()
    sig = SignalXY(label="noisy")
    sig.set_data([x, np.sin(x) + 0.3 * np.cos(7 * x)])
    plot.add_signal(sig)
    core.add_plot(plot, 0)
    return core


class StatsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = ensure_qapp()

    def test_stats_does_not_raise_on_empty_canvas(self):
        """Calling stats on an empty canvas must not crash."""
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                empty = Canvas(1, 1, title="empty")
                qt_canvas = IplotQtCanvasFactory.new(backend, canvas=empty)
                qt_canvas.set_canvas(empty)
                qt_canvas.resize(400, 300)
                self.app.processEvents()

                qt_canvas.stats(empty)
                self.app.processEvents()

    def test_stats_on_canvas_with_signals_completes(self):
        """Stats with real signals fills the stats table without raising."""
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                canvas = _canvas_with_noisy_signal()
                qt_canvas = IplotQtCanvasFactory.new(backend, canvas=canvas)
                qt_canvas.set_canvas(canvas)
                qt_canvas.resize(400, 300)
                self.app.processEvents()

                qt_canvas.stats(canvas)
                self.app.processEvents()


class AutoscaleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = ensure_qapp()

    def test_autoscale_all_y_runs_without_error(self):
        """autoscale_all_y must traverse every PlotXY in the figure cleanly."""
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                canvas = _canvas_with_noisy_signal()
                qt_canvas = IplotQtCanvasFactory.new(backend, canvas=canvas)
                qt_canvas.set_canvas(canvas)
                qt_canvas.resize(400, 300)
                self.app.processEvents()

                qt_canvas.autoscale_all_y()
                self.app.processEvents()


class MouseModeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = ensure_qapp()

    def test_set_mouse_mode_accepts_every_mode(self):
        """All Canvas.MOUSE_MODE_* constants must be accepted by set_mouse_mode."""
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                canvas = _canvas_with_noisy_signal()
                qt_canvas = IplotQtCanvasFactory.new(backend, canvas=canvas)
                qt_canvas.set_canvas(canvas)
                qt_canvas.resize(400, 300)
                self.app.processEvents()

                for mode in (Canvas.MOUSE_MODE_SELECT, Canvas.MOUSE_MODE_CROSSHAIR,
                             Canvas.MOUSE_MODE_PAN, Canvas.MOUSE_MODE_ZOOM,
                             Canvas.MOUSE_MODE_DIST, Canvas.MOUSE_MODE_MARKER):
                    qt_canvas.set_mouse_mode(mode)
                    self.app.processEvents()
                    self.assertEqual(qt_canvas._mmode, mode)


class RefreshAndResetTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = ensure_qapp()

    def test_refresh_preserves_canvas(self):
        """refresh() redraws the same canvas without dropping it."""
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                canvas = _canvas_with_noisy_signal()
                qt_canvas = IplotQtCanvasFactory.new(backend, canvas=canvas)
                qt_canvas.set_canvas(canvas)
                qt_canvas.resize(400, 300)
                self.app.processEvents()

                qt_canvas.refresh()
                self.app.processEvents()
                self.assertIs(qt_canvas.get_canvas(), canvas)

    def test_reset_clears_canvas(self):
        """reset() removes the canvas from the widget (set_canvas(None))."""
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                canvas = _canvas_with_noisy_signal()
                qt_canvas = IplotQtCanvasFactory.new(backend, canvas=canvas)
                qt_canvas.set_canvas(canvas)
                qt_canvas.resize(400, 300)
                self.app.processEvents()

                qt_canvas.reset()
                self.app.processEvents()
                self.assertIsNone(qt_canvas.get_canvas())


class CrosshairEnabledRenderTest(unittest.TestCase):
    """Enabling the crosshair must not break the render path on either backend."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.app = ensure_qapp()

    def test_enable_crosshair_and_grab(self):
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                canvas = _canvas_with_noisy_signal()
                canvas.enable_crosshair(color="#d62728", linewidth=1,
                                        horizontal=True, vertical=True)
                qt_canvas = IplotQtCanvasFactory.new(backend, canvas=canvas)
                qt_canvas.set_canvas(canvas)
                qt_canvas.resize(400, 300)
                self.app.processEvents()

                self.assertTrue(canvas.crosshair_enabled)
                pm = qt_canvas.grab()
                self.assertFalse(pm.isNull())


class CrosshairMouseMotionTest(unittest.TestCase):
    """Drive the crosshair drawing path by invoking the mouse-motion handlers.

    Using the backend-native event APIs bypasses Qt's offscreen hit-testing
    (unreliable) while still exercising every line the real mouse handler
    would execute. Matplotlib has ``FigureCanvasBase.motion_notify_event``
    which dispatches to every ``mpl_connect('motion_notify_event', ...)``
    callback; pyqtgraph exposes ``scene.sigMouseMoved`` which is what
    ``IplotCrosshairWidget.on_move`` listens on.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.app = ensure_qapp()

    def _build_with_crosshair(self, backend: str):
        canvas = _canvas_with_noisy_signal()
        canvas.enable_crosshair(color="#d62728", linewidth=1,
                                horizontal=True, vertical=True)
        qt_canvas = IplotQtCanvasFactory.new(backend, canvas=canvas)
        qt_canvas.set_canvas(canvas)
        qt_canvas.resize(600, 400)
        self.app.processEvents()
        qt_canvas.set_mouse_mode(Canvas.MOUSE_MODE_CROSSHAIR)
        self.app.processEvents()
        return canvas, qt_canvas

    def test_matplotlib_motion_notify_reaches_multicursor(self):
        from matplotlib.backend_bases import MouseEvent

        canvas, qt_canvas = self._build_with_crosshair('matplotlib')
        parser = qt_canvas._parser

        self.assertGreaterEqual(len(parser._cursors), 1,
                                "crosshair mode must install at least one cursor")

        # Build a synthetic motion event in the pixel center of the first
        # axes and dispatch it through the figure's callback registry.
        # This is the same path real mouse motion takes in matplotlib.
        fig = parser.figure
        ax = fig.axes[0]
        bbox = ax.get_position()
        fw = fig.get_figwidth() * fig.dpi
        fh = fig.get_figheight() * fig.dpi
        x_pixel = (bbox.x0 + bbox.width / 2) * fw
        y_pixel = (bbox.y0 + bbox.height / 2) * fh

        event = MouseEvent('motion_notify_event', fig.canvas, x_pixel, y_pixel)
        fig.canvas.callbacks.process('motion_notify_event', event)
        self.app.processEvents()

        # The MultiCursor flips need_clear to True after a valid motion.
        self.assertTrue(parser._cursors[0].need_clear)

    def test_pyqtgraph_sigmousemoved_reaches_crosshair(self):
        from PySide6.QtCore import QPointF

        canvas, qt_canvas = self._build_with_crosshair('pyqt')
        parser = qt_canvas._parser

        self.assertTrue(parser._cursor_active,
                        "crosshair mode must activate the pyqtgraph cursor")
        self.assertGreaterEqual(len(parser._cursors), 1)

        figure = parser.figure
        scene = figure.scene()
        # Centre of the first plot item's scene bounding rect guarantees
        # the crosshair's hit-test inside the plot succeeds.
        plot_impl = parser._plot_impl_plot_lut[id(canvas.plots[0][0])][0]
        rect = plot_impl.sceneBoundingRect()
        pos = QPointF(rect.center().x(), rect.center().y())
        scene.sigMouseMoved.emit(pos)
        self.app.processEvents()

        # After a valid motion the cursor caches the last-seen X value.
        self.assertIsNotNone(parser._cursors[0]._last_x)


if __name__ == '__main__':
    unittest.main()
