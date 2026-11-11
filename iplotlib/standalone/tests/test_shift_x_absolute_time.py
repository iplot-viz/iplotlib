"""In absolute time a signal can be shifted along X too, as in pulse mode: dragged, or with the DIST dialog, whose
Shift X is in seconds there. The times stay whole nanoseconds, which a float near 1e18 would round to 256 ns."""

import unittest
from types import SimpleNamespace

import numpy as np

from iplotlib.core.axis import LinearAxis
from iplotlib.core.canvas import Canvas
from iplotlib.core.plot import PlotXY
from iplotlib.core.signal import SignalXY
from iplotlib.qt.gui.iplotQtCanvasFactory import IplotQtCanvasFactory
from iplotlib.qt.gui.iplotSignalShiftDialog import SignalShiftDialog
from iplotlib.qt.testing import ensure_qapp

BACKENDS = ('matplotlib', 'pyqt')
# Neither a multiple of 256 ns.
T0 = 1_785_229_200_000_000_001
SHIFT = 1_000_000_007


class ShiftXInAbsoluteTimeTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.app = ensure_qapp()

    def _draw(self, backend, span=3_000_000_007):
        """A plot with a time axis and a signal of four samples over `span` nanoseconds: over a day, pyqtgraph
        gives the axis a unit of 100 ns."""
        canvas = Canvas(1, 1)
        plot = PlotXY(axes=[LinearAxis(is_date=True), [LinearAxis()]])
        signal = SignalXY(label='s', uid='uid-s')
        signal.data_access_enabled = False
        x = T0 + np.array([0, 1001, 2003, span], dtype=np.int64)
        signal.set_data([x, np.array([1.0, 2.0, 3.0, 4.0])])
        plot.add_signal(signal)
        canvas.add_plot(plot, 0)
        qt_canvas = IplotQtCanvasFactory.new(backend, canvas=canvas)
        self.addCleanup(qt_canvas.deleteLater)
        qt_canvas.set_canvas(canvas)
        qt_canvas.resize(800, 600)
        self.app.processEvents()
        parser = qt_canvas._parser
        return qt_canvas, signal, parser._signal_impl_plot_lut.get(parser.signal_lut_key(signal)), x

    @staticmethod
    def _drawn(qt_canvas, signal, impl_plot):
        """The times the signal is drawn at, in nanoseconds."""
        line = signal.lines[0]
        x = line.get_xdata() if hasattr(line, 'get_xdata') else line.getData()[0]
        return [qt_canvas._parser.transform_value(impl_plot, 0, float(value)) for value in x]

    def test_a_drag_shifts_the_signal_along_x_by_the_time_dragged(self):
        for backend in BACKENDS:
            for span in (3_000_000_007, 86_400_000_000_007):
                with self.subTest(backend=backend, span=span):
                    qt_canvas, signal, impl_plot, x = self._draw(backend, span)
                    parser = qt_canvas._parser
                    start = parser.transform_value(impl_plot, 0, int(x[0]), inverse=True)
                    end = parser.transform_value(impl_plot, 0, int(x[0]) + SHIFT, inverse=True)

                    qt_canvas._start_drag_shift(impl_plot, signal, 1.0, is_datetime=True, start_x=start)
                    qt_canvas._end_drag_shift(1.0, end)
                    self.app.processEvents()

                    # The three samples left in the view, moved by the time dragged to the nanosecond.
                    self.assertEqual(self._drawn(qt_canvas, signal, impl_plot), [int(v) for v in x[:3] + SHIFT])

    def test_while_dragging_the_preview_follows_along_x(self):
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                qt_canvas, signal, impl_plot, x = self._draw(backend)
                parser = qt_canvas._parser
                start = parser.transform_value(impl_plot, 0, int(x[0]), inverse=True)
                end = parser.transform_value(impl_plot, 0, int(x[0]) + SHIFT, inverse=True)
                line = signal.lines[0]
                drawn = np.asarray(line.get_xdata() if hasattr(line, 'get_xdata') else line.getData()[0], dtype=float)

                qt_canvas._start_drag_shift(impl_plot, signal, 1.0, is_datetime=True, start_x=start)
                qt_canvas._update_drag_shift(1.0, end)
                preview = qt_canvas._drag_shift_preview_line
                preview = preview[0] if isinstance(preview, list) else preview
                shown = np.asarray(preview.get_xdata() if hasattr(preview, 'get_xdata') else preview.getData()[0],
                                   dtype=float)
                qt_canvas._cancel_drag_shift()

                np.testing.assert_allclose(shown, drawn + (end - start))

    def test_undo_brings_the_signal_back(self):
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                qt_canvas, signal, impl_plot, x = self._draw(backend)
                parser = qt_canvas._parser
                start = parser.transform_value(impl_plot, 0, int(x[0]), inverse=True)
                end = parser.transform_value(impl_plot, 0, int(x[0]) + SHIFT, inverse=True)
                qt_canvas._start_drag_shift(impl_plot, signal, 1.0, is_datetime=True, start_x=start)
                qt_canvas._end_drag_shift(1.0, end)

                qt_canvas.undo()
                self.app.processEvents()

                self.assertEqual(self._drawn(qt_canvas, signal, impl_plot), [int(v) for v in x])

    def _press(self, backend, qt_canvas, impl_plot, x, y):
        """A left press on the plot at the time `x`, in nanoseconds, and the value `y`: a matplotlib event, or a
        Qt one on the view of pyqtgraph."""
        axis_x = qt_canvas._parser.transform_value(impl_plot, 0, x, inverse=True)
        if backend == 'pyqt':
            from PySide6.QtCore import QEvent, QPointF, Qt
            from PySide6.QtGui import QMouseEvent
            from PySide6.QtWidgets import QApplication
            view = qt_canvas._parser.figure
            viewport = view.viewport()
            pos = QPointF(view.mapFromScene(impl_plot.getViewBox().mapViewToScene(QPointF(axis_x, y))))
            for kind, buttons in ((QEvent.Type.MouseButtonPress, Qt.MouseButton.LeftButton),
                                  (QEvent.Type.MouseButtonRelease, Qt.MouseButton.NoButton)):
                QApplication.sendEvent(viewport, QMouseEvent(kind, pos, QPointF(viewport.mapToGlobal(pos.toPoint())),
                                                             Qt.MouseButton.LeftButton, buttons,
                                                             Qt.KeyboardModifier.NoModifier))
                self.app.processEvents()
        else:
            from matplotlib.backend_bases import MouseButton, MouseEvent
            px, py = impl_plot.transData.transform((axis_x, y))
            qt_canvas._mpl_mouse_press_handler(MouseEvent('button_press_event', impl_plot.figure.canvas, px, py,
                                                          button=MouseButton.LEFT))

    def test_dist_opens_the_dialog_with_the_time_measured(self):
        from unittest.mock import patch
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                qt_canvas, signal, impl_plot, x = self._draw(backend)
                qt_canvas.show()
                self.addCleanup(qt_canvas.hide)
                self.app.processEvents()
                qt_canvas.set_mouse_mode(Canvas.MOUSE_MODE_DIST)
                opened = []

                with patch.object(SignalShiftDialog, 'exec', lambda dialog: opened.append(dialog) or 0):
                    self._press(backend, qt_canvas, impl_plot, int(x[0]), 2.0)
                    self._press(backend, qt_canvas, impl_plot, int(x[0]) + SHIFT, 2.0)

                dialog, = opened
                self.addCleanup(dialog.deleteLater)
                self.assertTrue(dialog._dx_spin.isEnabled())
                # To the pixel the clicks fell on, some milliseconds over 3 s.
                self.assertAlmostEqual(dialog._dx_spin.value(), SHIFT / 1e9, delta=0.02)

    def test_the_dist_dialog_shifts_along_x_in_seconds(self):
        ensure_qapp()
        dialog = SignalShiftDialog(dx=float(3600 * 10 ** 9 + 7), dy=2.0, dz=0.0,
                                   signals=[SimpleNamespace(uid='uid-s', label='s', name='s')], dx_is_datetime=True)
        self.addCleanup(dialog.deleteLater)
        requested = []
        dialog.shiftRequested.connect(lambda *args: requested.append(args))

        self.assertTrue(dialog._dx_spin.isEnabled())
        self.assertEqual(dialog._dx_spin.suffix(), ' s')
        self.assertAlmostEqual(dialog._dx_spin.value(), 3600.000000007, places=9)
        dialog._signal_combo.setCurrentIndex(1)
        dialog._on_apply()

        # The shift in nanoseconds, whole, as the times it moves.
        (uid, _, _, _, dx, dy, duplicate), = requested
        self.assertEqual((uid, dx, dy, duplicate), ('uid-s', 3600 * 10 ** 9 + 7, 2.0, False))

    def test_the_dist_dialog_keeps_shift_x_as_it_was_on_other_axes(self):
        ensure_qapp()
        dialog = SignalShiftDialog(dx=2.5, dy=0.0, signals=[], dx_is_datetime=False)
        self.addCleanup(dialog.deleteLater)

        self.assertTrue(dialog._dx_spin.isEnabled())
        self.assertEqual(dialog._dx_spin.suffix(), '')
        self.assertEqual(dialog._dx_spin.value(), 2.5)


if __name__ == '__main__':
    unittest.main()
