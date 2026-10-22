"""Moving and resizing plots with the mouse, in both backends.

In the select mode, a plot dragged by its background moves: in its column the others make room for it, onto a plot
of another column the two trade places. Dragged by its bottom right corner, it spans other rows. The canvas tells
where the plots went, undo takes them back, and each plot keeps its view. The slots the application reserves for
plots it does not draw show while a plot moves, move as plots do and take no plot over them. A drag from a curve or a
legend still moves those, and nothing moves out of the select mode, while a plot has the focus or while streaming.
"""

import gc
import sys
import unittest
import weakref
from unittest.mock import patch

import numpy as np
from PySide6.QtCore import QEvent, QPoint, QPointF, QRectF, QSizeF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QAbstractScrollArea, QApplication, QMenu

from iplotlib.core import layout
from iplotlib.core.canvas import Canvas
from iplotlib.core.plot import PlotXY
from iplotlib.core.signal import SignalXY
from iplotlib.qt.gui.iplotQtArrangement import HANDLE, RESIZE, _Overlay
from iplotlib.qt.gui.iplotQtCanvasFactory import IplotQtCanvasFactory
from iplotlib.qt.testing import ensure_qapp

BACKENDS = ('matplotlib', 'pyqt')


def _canvas(columns, labels: dict = None) -> Canvas:
    """A canvas with a column of plots for each count of plots in `columns`: each plot draws a rising line, which
    leaves its top left corner empty, and is titled by its place. `labels` names the signals of some places."""
    canvas = Canvas(rows=max(columns), cols=len(columns), mouse_mode=Canvas.MOUSE_MODE_SELECT)
    for col, count in enumerate(columns):
        for row in range(count):
            plot = PlotXY(plot_title=f'{row}.{col}', row=row + 1, col=col + 1)
            signal = SignalXY(label=(labels or {}).get((row, col), f's{row}{col}'), uid=f'{row}.{col}')
            signal.set_data([np.arange(10.0), np.arange(10.0)])
            plot.add_signal(signal)
            canvas.add_plot(plot, col)
    return canvas


def _titles(canvas: Canvas) -> list:
    return [[plot.plot_title if plot is not None else None for plot in column] for column in canvas.plots]


def _plot(canvas: Canvas, title: str) -> PlotXY:
    return next(plot for plot, _ in layout.slots_of(canvas) if plot.plot_title == title)


class _Mouse:
    """Real Qt mouse events on the widget that draws the plots. Points are in the coordinates of the canvas widget."""

    def __init__(self, qt_canvas, app):
        self.qt_canvas, self.app = qt_canvas, app
        self.widget = qt_canvas._arranger._widget

    def _at(self, point) -> QPoint:
        return self.widget.mapFrom(self.qt_canvas, QPoint(round(point[0]), round(point[1])))

    def cell(self, row: int, col: int, fx: float = 0.2, fy: float = 0.3):
        """A point on the background of the cell: towards its top left corner, which the rising lines leave."""
        rows, cols = self.qt_canvas._grid_bounds()
        return cols[col] + (cols[col + 1] - cols[col]) * fx, rows[row] + (rows[row + 1] - rows[row]) * fy

    def corner(self, slot: layout.Slot):
        """The middle of the resize handle of the plot in the slot."""
        rows, cols = self.qt_canvas._grid_bounds()
        side = HANDLE.px()
        return cols[slot.right] - side / 2, rows[slot.bottom] - side / 2

    def hover(self, point):
        QTest.mouseMove(self.widget, self._at(point))
        self.app.processEvents()

    def drag(self, start, end, release=True, steps=8):
        a, b = self._at(start), self._at(end)
        QTest.mousePress(self.widget, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, a)
        self.app.processEvents()
        for step in range(1, steps + 1):
            QTest.mouseMove(self.widget, a + (b - a) * (step / steps))
            self.app.processEvents()
        if release:
            self.release(end)

    def release(self, point):
        QTest.mouseRelease(self.widget, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, self._at(point))
        self.app.processEvents()

    def click(self, point):
        QTest.mouseClick(self.widget, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, self._at(point))
        self.app.processEvents()


class TestArrangePlots(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.app = ensure_qapp()

    def _qt_canvas(self, backend, columns=(3,), labels: dict = None):
        # One canvas shown at a time: the mouse of another, left over the same place, would take its events.
        previous = getattr(self, '_shown', None)
        if previous is not None:
            previous.close()
            self.app.processEvents()
        canvas = _canvas(columns, labels)
        qt_canvas = IplotQtCanvasFactory.new(backend, canvas=canvas)
        self._shown = qt_canvas
        self.addCleanup(qt_canvas.close)
        qt_canvas.resize(800, 900)
        qt_canvas.show()
        self.app.processEvents()
        qt_canvas.set_mouse_mode(Canvas.MOUSE_MODE_SELECT)
        self.app.processEvents()
        arranged = []
        qt_canvas.plotsArranged.connect(arranged.append)
        return canvas, qt_canvas, _Mouse(qt_canvas, self.app), arranged

    def _impl(self, qt_canvas, canvas, title):
        return qt_canvas._parser._plot_impl_plot_lut[id(_plot(canvas, title))][0]

    def _legend_rect(self, qt_canvas, canvas, title) -> QRectF:
        """The legend of the plot, in the coordinates of the canvas widget."""
        impl = self._impl(qt_canvas, canvas, title)
        if hasattr(impl, 'get_legend'):
            box = impl.get_legend().get_window_extent()
            renderer = qt_canvas._mpl_renderer
            ratio = renderer.devicePixelRatioF()
            top_left = renderer.mapTo(qt_canvas, QPoint(round(box.x0 / ratio), round(renderer.height() - box.y1 / ratio)))
            return QRectF(QPointF(top_left), QSizeF(box.width / ratio, box.height / ratio))
        view = qt_canvas._parser.figure
        rect = view.mapFromScene(impl.legend.sceneBoundingRect()).boundingRect()
        return QRectF(rect.translated(view.viewport().mapTo(qt_canvas, QPoint(0, 0))))

    def _curve_point(self, qt_canvas, canvas, title, x, y):
        """Where the point (x, y) of the data of the plot is drawn, in the coordinates of the canvas widget."""
        impl = self._impl(qt_canvas, canvas, title)
        if hasattr(impl, 'transData'):
            renderer = qt_canvas._mpl_renderer
            ratio = renderer.devicePixelRatioF()
            px, py = impl.transData.transform((x, y))
            local = QPointF(px / ratio, renderer.height() - py / ratio)
            return QPointF(renderer.mapTo(qt_canvas, local.toPoint())).toTuple()
        view = qt_canvas._parser.figure
        local = view.mapFromScene(impl.vb.mapViewToScene(QPointF(x, y)))
        return QPointF(view.viewport().mapTo(qt_canvas, local)).toTuple()

    def test_a_plot_dragged_up_its_column_goes_before_the_plot_dropped_on(self):
        for backend in BACKENDS:
            with self.subTest(backend):
                canvas, qt_canvas, mouse, arranged = self._qt_canvas(backend)

                mouse.drag(mouse.cell(2, 0), mouse.cell(0, 0))

                self.assertEqual(_titles(canvas), [['2.0', '0.0', '1.0']])
                self.assertEqual(len(arranged), 1)
                self.assertEqual({((before.row, before.col), (after.row, after.col)) for before, after in arranged[0]},
                                 {((2, 0), (0, 0)), ((0, 0), (1, 0)), ((1, 0), (2, 0))})
                self.assertEqual(qt_canvas.get_next_undo_cmd_name(), 'Move plot')
                self.assertIsNone(QApplication.overrideCursor())

    def test_undo_and_redo_take_the_plots_back_and_forth(self):
        for backend in BACKENDS:
            with self.subTest(backend):
                canvas, qt_canvas, mouse, arranged = self._qt_canvas(backend)
                mouse.drag(mouse.cell(2, 0), mouse.cell(0, 0))

                qt_canvas.undo()
                self.app.processEvents()
                self.assertEqual(_titles(canvas), [['0.0', '1.0', '2.0']])
                self.assertEqual({((before.row, before.col), (after.row, after.col)) for before, after in arranged[-1]},
                                 {((0, 0), (2, 0)), ((1, 0), (0, 0)), ((2, 0), (1, 0))})

                qt_canvas.redo()
                self.app.processEvents()
                self.assertEqual(_titles(canvas), [['2.0', '0.0', '1.0']])
                self.assertEqual(len(arranged), 3)

    def test_a_plot_dropped_on_a_plot_of_another_column_trades_places_with_it(self):
        for backend in BACKENDS:
            with self.subTest(backend):
                canvas, qt_canvas, mouse, arranged = self._qt_canvas(backend, columns=(2, 2))

                mouse.drag(mouse.cell(0, 0), mouse.cell(1, 1))

                self.assertEqual(_titles(canvas), [['1.1', '1.0'], ['0.1', '0.0']])

    def test_a_plot_dragged_by_its_corner_spans_more_rows_and_moves_the_plots_below_down(self):
        for backend in BACKENDS:
            with self.subTest(backend):
                canvas, qt_canvas, mouse, arranged = self._qt_canvas(backend)
                top = layout.Slot(0, 0)

                mouse.drag(mouse.corner(top), mouse.cell(1, 0, fx=0.9, fy=0.6))

                self.assertEqual([(plot.plot_title, slot.row, slot.row_span) for plot, slot in
                                  layout.slots_of(canvas)], [('0.0', 0, 2), ('1.0', 2, 1), ('2.0', 3, 1)])
                self.assertEqual((canvas.rows, canvas.cols), (4, 1))
                self.assertEqual(qt_canvas.get_next_undo_cmd_name(), RESIZE)
                qt_canvas.undo()
                self.app.processEvents()
                self.assertEqual([(slot.row, slot.row_span) for _, slot in layout.slots_of(canvas)],
                                 [(0, 1), (1, 1), (2, 1)])
                self.assertEqual(canvas.rows, 3)

    def test_each_plot_keeps_its_view(self):
        for backend in BACKENDS:
            with self.subTest(backend):
                canvas, qt_canvas, mouse, arranged = self._qt_canvas(backend)
                parser = qt_canvas._parser
                parser.set_oaw_axis_limits(self._impl(qt_canvas, canvas, '2.0'), 0, (2.0, 5.0))
                qt_canvas._flush_view()
                self.app.processEvents()

                mouse.drag(mouse.cell(2, 0), mouse.cell(0, 0))

                lo, hi = parser.get_oaw_axis_limits(self._impl(qt_canvas, canvas, '2.0'), 0)
                self.assertAlmostEqual(lo, 2.0, places=6)
                self.assertAlmostEqual(hi, 5.0, places=6)

    def test_a_drag_from_a_curve_shifts_the_curve_and_moves_no_plot(self):
        for backend in BACKENDS:
            with self.subTest(backend):
                canvas, qt_canvas, mouse, arranged = self._qt_canvas(backend)

                mouse.drag(self._curve_point(qt_canvas, canvas, '2.0', 5.0, 5.0), mouse.cell(0, 0))

                self.assertEqual(_titles(canvas), [['0.0', '1.0', '2.0']])
                self.assertEqual(arranged, [])
                self.assertEqual(qt_canvas.get_next_undo_cmd_name(), 'Shift')

    def test_the_plots_drawn_again_still_take_the_mouse(self):
        for backend in BACKENDS:
            with self.subTest(backend):
                canvas, qt_canvas, mouse, arranged = self._qt_canvas(backend)
                for _ in range(3):
                    mouse.drag(mouse.cell(2, 0), mouse.cell(0, 0))

                mouse.drag(self._curve_point(qt_canvas, canvas, '0.0', 5.0, 5.0), mouse.cell(2, 0))

                self.assertEqual(_titles(canvas), [['0.0', '1.0', '2.0']])
                self.assertEqual(qt_canvas.get_next_undo_cmd_name(), 'Shift')

    def test_a_drag_from_a_legend_moves_the_legend_and_no_plot(self):
        for backend in BACKENDS:
            with self.subTest(backend):
                canvas, qt_canvas, mouse, arranged = self._qt_canvas(backend)
                legend = self._legend_rect(qt_canvas, canvas, '2.0')

                # From its middle: by its left or right side, a drag resizes it.
                mouse.drag(legend.center().toTuple(), mouse.cell(2, 0, fx=0.35, fy=0.8))

                self.assertEqual(_titles(canvas), [['0.0', '1.0', '2.0']])
                self.assertEqual(arranged, [])
                moved = self._legend_rect(qt_canvas, canvas, '2.0')
                self.assertGreater(abs(moved.top() - legend.top()) + abs(moved.left() - legend.left()), 20)

    def test_a_click_moves_nothing(self):
        for backend in BACKENDS:
            with self.subTest(backend):
                canvas, qt_canvas, mouse, arranged = self._qt_canvas(backend)

                mouse.click(mouse.cell(2, 0))

                self.assertEqual(_titles(canvas), [['0.0', '1.0', '2.0']])
                self.assertEqual(arranged, [])

    def test_nothing_moves_out_of_the_select_mode_while_a_plot_has_the_focus_or_while_streaming(self):
        for backend in BACKENDS:
            for case in ('zoom', 'focus', 'streaming'):
                with self.subTest(backend=backend, case=case):
                    canvas, qt_canvas, mouse, arranged = self._qt_canvas(backend)
                    start, end = mouse.cell(2, 0), mouse.cell(0, 0)
                    if case == 'zoom':
                        qt_canvas.set_mouse_mode(Canvas.MOUSE_MODE_ZOOM)
                    elif case == 'focus':
                        qt_canvas._full_screen_mode_on(self._impl(qt_canvas, canvas, '2.0'))
                    else:
                        canvas.streaming = True
                    self.app.processEvents()

                    mouse.drag(start, end)

                    self.assertEqual(_titles(canvas), [['0.0', '1.0', '2.0']])
                    self.assertEqual(arranged, [])

    def test_escape_leaves_the_plots_where_they_were(self):
        for backend in BACKENDS:
            with self.subTest(backend):
                canvas, qt_canvas, mouse, arranged = self._qt_canvas(backend)

                mouse.drag(mouse.cell(2, 0), mouse.cell(0, 0), release=False)
                # The keys go to the view that draws in the widget, if any.
                view = mouse.widget.parentWidget()
                QTest.keyClick(view if isinstance(view, QAbstractScrollArea) else mouse.widget, Qt.Key.Key_Escape)
                mouse.release(mouse.cell(0, 0))

                self.assertEqual(_titles(canvas), [['0.0', '1.0', '2.0']])
                self.assertEqual(arranged, [])
                self.assertFalse(qt_canvas._arranger._overlay.isVisible())
                self.assertIsNone(QApplication.overrideCursor())

    def test_a_press_of_another_button_ends_the_gesture(self):
        for backend in BACKENDS:
            with self.subTest(backend):
                canvas, qt_canvas, mouse, arranged = self._qt_canvas(backend)
                mouse.drag(mouse.cell(2, 0), mouse.cell(0, 0), release=False)

                # A right click opens a menu of the plot, which can take the release of the drag.
                at = mouse._at(mouse.cell(0, 0))
                QTest.mousePress(mouse.widget, Qt.MouseButton.RightButton, Qt.KeyboardModifier.NoModifier, at)
                QTest.mouseRelease(mouse.widget, Qt.MouseButton.RightButton, Qt.KeyboardModifier.NoModifier, at)
                self.app.processEvents()
                for menu in [widget for widget in QApplication.topLevelWidgets() if isinstance(widget, QMenu)]:
                    menu.close()
                mouse.release(mouse.cell(0, 0))

                self.assertEqual(_titles(canvas), [['0.0', '1.0', '2.0']])
                self.assertEqual(arranged, [])
                self.assertIsNone(QApplication.overrideCursor())

    def test_a_drag_whose_release_went_elsewhere_ends_at_the_next_move(self):
        for backend in BACKENDS:
            with self.subTest(backend):
                canvas, qt_canvas, mouse, arranged = self._qt_canvas(backend)
                mouse.drag(mouse.cell(2, 0), mouse.cell(0, 0), release=False)

                at = QPointF(mouse._at(mouse.cell(0, 0)))
                QApplication.sendEvent(mouse.widget, QMouseEvent(QEvent.Type.MouseMove, at, mouse.widget.mapToGlobal(at),
                                                                 Qt.MouseButton.NoButton, Qt.MouseButton.NoButton,
                                                                 Qt.KeyboardModifier.NoModifier))
                self.assertIsNone(qt_canvas._arranger._gesture)
                self.assertIsNone(QApplication.overrideCursor())
                mouse.release(mouse.cell(0, 0))

                self.assertEqual(_titles(canvas), [['0.0', '1.0', '2.0']])
                self.assertEqual(arranged, [])

    def test_the_release_of_a_move_reaches_the_plots_where_they_were(self):
        # pyqtgraph makes a click of the press and the release of a drag it did not see move: the click must land on
        # the background the drag started from, not on the legend of the plot that takes its place.
        long_name = 'a much longer name of a signal, which takes the room of the shorter ones'
        for backend in BACKENDS:
            with self.subTest(backend):
                canvas, qt_canvas, mouse, arranged = self._qt_canvas(backend, labels={(1, 0): long_name})
                legend = self._legend_rect(qt_canvas, canvas, '2.0')
                start = (legend.left() - 25, legend.top() + 6)
                self.assertFalse(qt_canvas._press_taken(QPointF(*start)))

                mouse.drag(start, mouse.cell(0, 0))

                self.assertEqual(_titles(canvas), [['2.0', '0.0', '1.0']])
                self.assertEqual([signal.label for plot, _ in layout.slots_of(canvas)
                                  for signals in plot.signals.values() for signal in signals if signal.hidden], [])

    def test_a_marker_keeps_its_plot_when_the_plot_moves(self):
        for backend in BACKENDS:
            with self.subTest(backend):
                canvas, qt_canvas, mouse, arranged = self._qt_canvas(backend)
                signal = next(iter(_plot(canvas, '2.0').signals.values()))[0]
                qt_canvas._marker_window.add_marker(signal, (5.0, 5.0), signal.label)

                mouse.drag(mouse.cell(2, 0), mouse.cell(0, 0))

                plot_id = qt_canvas._marker_window.table.item(0, 1).data(Qt.ItemDataRole.UserRole)
                self.assertEqual(plot_id, signal.get_id())
                self.assertIs(qt_canvas.get_signal_marker(plot_id[:2], signal.uid)[0], signal)

    def test_the_last_plot_of_a_column_grows_below_the_grid(self):
        for backend in BACKENDS:
            with self.subTest(backend):
                canvas, qt_canvas, mouse, arranged = self._qt_canvas(backend)
                rows, cols = qt_canvas._grid_bounds()

                mouse.drag(mouse.corner(layout.Slot(2, 0)), (cols[1] - 20, rows[3] + (rows[3] - rows[2]) * 0.5))

                self.assertEqual([(plot.plot_title, slot.row, slot.row_span) for plot, slot in
                                  layout.slots_of(canvas)], [('0.0', 0, 1), ('1.0', 1, 1), ('2.0', 2, 2)])
                self.assertEqual((canvas.rows, canvas.cols), (4, 1))

    def test_an_arrangement_of_plots_drawn_again_since_is_left_aside(self):
        for backend in BACKENDS:
            with self.subTest(backend):
                canvas, qt_canvas, mouse, arranged = self._qt_canvas(backend)
                arrangement = layout.moved(canvas, _plot(canvas, '2.0'), 0, 0)
                # As an application drawing the canvas again does: other plots in the same places.
                canvas.plots = _canvas((3,)).plots
                qt_canvas.refresh()
                drawn = [list(column) for column in canvas.plots]

                qt_canvas._apply_arrangement('Move plot', arrangement)

                self.assertEqual(canvas.plots, drawn)
                self.assertTrue(all(new is old for new, old in zip(canvas.plots[0], drawn[0])))
                self.assertEqual(arranged, [])

    def test_a_plot_that_does_not_fit_where_it_is_dropped_stays(self):
        for backend in BACKENDS:
            with self.subTest(backend):
                canvas, qt_canvas, mouse, arranged = self._qt_canvas(backend, columns=(1, 1))
                # A plot spanning both rows of its column, next to a plot that leaves an empty cell below it.
                layout.arrange(canvas, layout.resized(canvas, _plot(canvas, '0.0'), 2, 1))
                qt_canvas.refresh()
                self.app.processEvents()

                mouse.drag(mouse.cell(0, 0), mouse.cell(1, 1))

                self.assertEqual(_titles(canvas), [['0.0'], ['0.1']])
                self.assertEqual(arranged, [])

    def test_a_reserved_slot_shows_while_dragging_and_trades_places_with_the_plot_dropped_on_it(self):
        for backend in BACKENDS:
            with self.subTest(backend):
                canvas, qt_canvas, mouse, arranged = self._qt_canvas(backend, columns=(2, 1))
                # The empty cell below the plot of the second column is kept for a plot the application does not draw.
                qt_canvas.reserved_slots = lambda: [layout.Slot(1, 1)]

                mouse.drag(mouse.cell(0, 0), mouse.cell(1, 1), release=False)
                reserved = [rect for rect, style in qt_canvas._arranger._overlay._shapes if style == _Overlay.RESERVED]
                mouse.release(mouse.cell(1, 1))

                self.assertEqual(len(reserved), 1)
                self.assertTrue(reserved[0].contains(QPointF(*mouse.cell(0, 0, fx=0.5, fy=0.5))))
                self.assertEqual(_titles(canvas), [[None, '1.0'], ['0.1', '0.0']])
                self.assertEqual({((before.row, before.col), (after.row, after.col)) for before, after in arranged[0]},
                                 {((0, 0), (1, 1)), ((1, 1), (0, 0))})

    def test_a_plot_does_not_grow_over_a_reserved_slot(self):
        for backend in BACKENDS:
            with self.subTest(backend):
                canvas, qt_canvas, mouse, arranged = self._qt_canvas(backend, columns=(2, 1))
                qt_canvas.reserved_slots = lambda: [layout.Slot(1, 1)]
                end = mouse.cell(1, 1, fx=0.6, fy=0.6)

                mouse.drag(mouse.corner(layout.Slot(1, 0)), end, release=False)
                shown = [style for _, style in qt_canvas._arranger._overlay._shapes]
                mouse.release(end)

                self.assertIn(_Overlay.FORBIDDEN, shown)
                self.assertEqual(_titles(canvas), [['0.0', '1.0'], ['0.1']])
                self.assertEqual(arranged, [])

    def test_qt_destroys_a_canvas_whose_arranger_python_already_cleared(self):
        # The garbage collector can clear the arranger before the canvas it frees with it: Qt then sends the events
        # of the widgets it destroys through the arranger. A pyqtgraph canvas goes once dropped, and the error of an
        # event filter called meanwhile goes to sys.excepthook.
        qt_canvas = IplotQtCanvasFactory.new('pyqt', canvas=_canvas((3,)))
        qt_canvas.show()
        self.app.processEvents()
        qt_canvas.set_mouse_mode(Canvas.MOUSE_MODE_SELECT)
        qt_canvas.close()
        self.app.processEvents()
        qt_canvas._arranger.__dict__.clear()
        dropped, errors = weakref.ref(qt_canvas), []

        with patch.object(sys, 'excepthook', lambda kind, value, traceback: errors.append(value)):
            del qt_canvas
            gc.collect()
            self.app.processEvents()

        self.assertIsNone(dropped())
        self.assertEqual(errors, [])

    def test_the_resize_handle_shows_under_the_mouse(self):
        for backend in BACKENDS:
            with self.subTest(backend):
                canvas, qt_canvas, mouse, arranged = self._qt_canvas(backend)

                mouse.hover(mouse.corner(layout.Slot(1, 0)))

                self.assertTrue(qt_canvas._arranger._overlay.isVisible())
                self.assertEqual(mouse.widget.cursor().shape(), Qt.CursorShape.SizeFDiagCursor)

                mouse.hover(mouse.cell(1, 0))
                self.assertNotEqual(mouse.widget.cursor().shape(), Qt.CursorShape.SizeFDiagCursor)


if __name__ == '__main__':
    unittest.main()
