"""Moving and resizing plots with the mouse, laying them out on a grid, and dropping on the grid, in both backends.

In the select mode, a plot dragged by its background moves: in its column the others make room for it, onto a plot
of another column the two trade places. Dragged by a corner, it spans other rows and columns. The canvas tells
where the plots went, undo takes them back, and each plot keeps its view. The slots the application reserves for
plots it does not draw show while a plot moves, move as plots do and take no plot over them. A drag from a curve or a
legend still moves those, and nothing moves out of the select mode, while a plot has the focus or while streaming.

The Layout tool of the toolbar lays the plots out on the grid picked in its menu, the plots that do not fit going into
the last cell as stacks of one plot. What the application takes can be dropped on a cell of the grid, empty or not.
"""

import gc
import sys
import unittest
import weakref
from unittest.mock import patch

import numpy as np
from PySide6.QtCore import QEvent, QMimeData, QPoint, QPointF, QRectF, QSizeF, Qt
from PySide6.QtGui import QDragEnterEvent, QDragLeaveEvent, QDragMoveEvent, QDropEvent, QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QAbstractScrollArea, QApplication, QMenu

from iplotlib.core import layout
from iplotlib.core.canvas import Canvas
from iplotlib.core.plot import PlotXY
from iplotlib.core.signal import SignalXY
from iplotlib.impl.pyqtgraph.pyQtGraphCanvas import _LegendEye
from iplotlib.qt.gui.iplotQtArrangement import HANDLE, RESIZE, _Overlay
from iplotlib.qt.gui.iplotQtCanvasFactory import IplotQtCanvasFactory
from iplotlib.qt.gui.iplotQtLayoutPicker import CELL, GAP, LayoutPicker
from iplotlib.qt.gui.iplotQtMainWindow import IplotQtMainWindow
from iplotlib.qt.testing import ensure_qapp

BACKENDS = ('matplotlib', 'pyqt')


def _canvas(columns, labels: dict = None, points: int = 10, empty=()) -> Canvas:
    """A canvas with a column of plots for each count of plots in `columns`: each plot draws a rising line of
    `points` points from 0 to 9, which leaves its top left corner empty, and is titled by its place. `labels` names
    the signals of some places, and the places in `empty` have no plot."""
    canvas = Canvas(rows=max(columns), cols=len(columns), mouse_mode=Canvas.MOUSE_MODE_SELECT)
    for col, count in enumerate(columns):
        for row in range(count):
            if (row, col) in empty:
                canvas.add_plot(None, col)
                continue
            plot = PlotXY(plot_title=f'{row}.{col}', row=row + 1, col=col + 1)
            signal = SignalXY(label=(labels or {}).get((row, col), f's{row}{col}'), uid=f'{row}.{col}')
            signal.set_data([np.linspace(0.0, 9.0, points), np.linspace(0.0, 9.0, points)])
            plot.add_signal(signal)
            canvas.add_plot(plot, col)
    return canvas


def _titles(canvas: Canvas) -> list:
    return [[plot.plot_title if plot is not None else None for plot in column] for column in canvas.plots]


def _plot(canvas: Canvas, title: str) -> PlotXY:
    return next(plot for plot, _ in layout.slots_of(canvas) if plot.plot_title == title)


def _slots(canvas: Canvas) -> list:
    """Each plot by its title, with its row, its column and the rows and columns it spans."""
    return sorted((plot.plot_title, slot.row, slot.col, slot.row_span, slot.col_span)
                  for plot, slot in layout.slots_of(canvas))


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

    def corner(self, slot: layout.Slot, top: bool = False, left: bool = False):
        """The middle of the resize handle of the plot in the slot, in its bottom right corner or the one given."""
        rows, cols = self.qt_canvas._grid_bounds()
        side = HANDLE.px()
        return (cols[slot.col] + side / 2 if left else cols[slot.right] - side / 2,
                rows[slot.row] + side / 2 if top else rows[slot.bottom] - side / 2)

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

    def _qt_canvas(self, backend, columns=(3,), labels: dict = None, points: int = 10, empty=()):
        # One canvas shown at a time: the mouse of another, left over the same place, would take its events.
        previous = getattr(self, '_shown', None)
        if previous is not None:
            previous.close()
            self.app.processEvents()
        canvas = _canvas(columns, labels, points, empty)
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

    @staticmethod
    def _drawn_place(qt_canvas, impl) -> tuple:
        """The place the backend drew the plot of `impl` on: (row, col, row_span, col_span) of its grid."""
        parser = qt_canvas._parser
        if hasattr(impl, 'get_subplotspec'):
            spec = impl.get_subplotspec().get_topmost_subplotspec()
            return spec.rowspan.start, spec.colspan.start, len(spec.rowspan), len(spec.colspan)
        cells = parser.figure.ci.items[impl.parentItem()]
        rows, cols = {row for row, _ in cells}, {col for _, col in cells}
        return min(rows) - parser._row_offset, min(cols), len(rows), len(cols)

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

    def test_a_plot_grows_no_bigger_than_the_application_draws(self):
        for backend in BACKENDS:
            with self.subTest(backend):
                canvas, qt_canvas, mouse, arranged = self._qt_canvas(backend)
                qt_canvas.max_span = lambda: 2

                mouse.drag(mouse.corner(layout.Slot(0, 0)), mouse.cell(2, 0, fx=0.9, fy=0.6))

                self.assertEqual([(plot.plot_title, slot.row, slot.row_span) for plot, slot in
                                  layout.slots_of(canvas)], [('0.0', 0, 2), ('1.0', 2, 1), ('2.0', 3, 1)])

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

    def test_a_move_moves_what_the_backend_drew_without_drawing_it_again(self):
        for backend in BACKENDS:
            with self.subTest(backend):
                canvas, qt_canvas, mouse, arranged = self._qt_canvas(backend, columns=(3, 1))
                drawn = {plot.plot_title: self._impl(qt_canvas, canvas, plot.plot_title)
                         for plot, _ in layout.slots_of(canvas)}

                with patch.object(qt_canvas, 'refresh') as refresh:
                    mouse.drag(mouse.cell(2, 0), mouse.cell(0, 1))

                refresh.assert_not_called()
                self.assertEqual(_titles(canvas), [['0.0', '1.0', '0.1'], ['2.0']])
                for plot, slot in layout.slots_of(canvas):
                    impl = self._impl(qt_canvas, canvas, plot.plot_title)
                    self.assertIs(impl, drawn[plot.plot_title])
                    self.assertEqual(self._drawn_place(qt_canvas, impl),
                                     (slot.row, slot.col, slot.row_span, slot.col_span))

    def test_a_backend_that_cannot_move_its_plots_draws_them_again_where_they_go(self):
        for backend in BACKENDS:
            with self.subTest(backend):
                canvas, qt_canvas, mouse, arranged = self._qt_canvas(backend)

                with patch.object(qt_canvas._parser, 'relayout', return_value=False):
                    mouse.drag(mouse.cell(2, 0), mouse.cell(0, 0))

                self.assertEqual(_titles(canvas), [['2.0', '0.0', '1.0']])
                for plot, slot in layout.slots_of(canvas):
                    self.assertEqual(self._drawn_place(qt_canvas, self._impl(qt_canvas, canvas, plot.plot_title)),
                                     (slot.row, slot.col, slot.row_span, slot.col_span))

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

    def test_the_rulers_window_names_a_plot_moved_by_its_new_place(self):
        for backend in BACKENDS:
            with self.subTest(backend):
                canvas, qt_canvas, mouse, arranged = self._qt_canvas(backend, columns=(2, 1))
                plot = _plot(canvas, '0.0')
                qt_canvas._add_ruler_at(self._impl(qt_canvas, canvas, '0.0'), plot, 4.0, 4.0)
                self.app.processEvents()
                ruler = plot.rulers[0]

                qt_canvas._apply_arrangement('Move plot', layout.moved(canvas, plot, 1, 1))
                self.app.processEvents()

                # The window lists the plot the ruler is on first, and acts on the plot it names.
                plot_id = qt_canvas._ruler_window._rows[0]['plot_id']
                self.assertEqual(plot_id, qt_canvas._canvas_position_of(plot))
                qt_canvas.toggle_ruler_visibility(ruler.name, plot_id, False)
                self.assertFalse(ruler.visible)

    def test_the_last_plot_of_a_column_grows_below_the_grid(self):
        for backend in BACKENDS:
            with self.subTest(backend):
                canvas, qt_canvas, mouse, arranged = self._qt_canvas(backend)
                rows, cols = qt_canvas._grid_bounds()

                mouse.drag(mouse.corner(layout.Slot(2, 0)), (cols[1] - 20, rows[3] + (rows[3] - rows[2]) * 0.5))

                self.assertEqual([(plot.plot_title, slot.row, slot.row_span) for plot, slot in
                                  layout.slots_of(canvas)], [('0.0', 0, 1), ('1.0', 1, 1), ('2.0', 2, 2)])
                self.assertEqual((canvas.rows, canvas.cols), (4, 1))

    def test_a_plot_dragged_by_a_left_corner_grows_into_the_empty_cell_on_its_left(self):
        for backend in BACKENDS:
            with self.subTest(backend):
                # A plot in the right column, the cell on its left empty, and plots below.
                canvas, qt_canvas, mouse, arranged = self._qt_canvas(backend, columns=(2, 2), empty=[(0, 0)])
                rows, cols = qt_canvas._grid_bounds()
                start = mouse.corner(layout.Slot(0, 1), left=True)

                mouse.hover(start)
                self.assertEqual(mouse.widget.cursor().shape(), Qt.CursorShape.SizeBDiagCursor)
                mouse.drag(start, (cols[0] + (cols[1] - cols[0]) * 0.3, start[1]))

                self.assertEqual(_slots(canvas), [('0.1', 0, 0, 1, 2), ('1.0', 1, 0, 1, 1), ('1.1', 1, 1, 1, 1)])
                self.assertEqual(self._drawn_place(qt_canvas, self._impl(qt_canvas, canvas, '0.1')), (0, 0, 1, 2))
                self.assertEqual(arranged, [[(layout.Slot(0, 1), layout.Slot(0, 0, 1, 2))]])
                qt_canvas.undo()
                self.app.processEvents()
                self.assertEqual(_slots(canvas), [('0.1', 0, 1, 1, 1), ('1.0', 1, 0, 1, 1), ('1.1', 1, 1, 1, 1)])

    def test_a_plot_grown_by_a_left_corner_grows_no_bigger_than_the_application_draws(self):
        for backend in BACKENDS:
            with self.subTest(backend):
                canvas, qt_canvas, mouse, arranged = self._qt_canvas(backend, columns=(1, 1, 1),
                                                                     empty=[(0, 0), (0, 1)])
                qt_canvas.max_span = lambda: 2
                rows, cols = qt_canvas._grid_bounds()
                start = mouse.corner(layout.Slot(0, 2), left=True)

                mouse.drag(start, (cols[0] + 5, start[1]))

                self.assertEqual(_slots(canvas), [('0.2', 0, 1, 1, 2)])

    def test_a_plot_dragged_by_a_top_corner_grows_into_the_empty_cell_above_and_shrinks_back(self):
        for backend in BACKENDS:
            with self.subTest(backend):
                canvas, qt_canvas, mouse, arranged = self._qt_canvas(backend, columns=(2, 2), empty=[(0, 1)])
                rows, cols = qt_canvas._grid_bounds()
                start = mouse.corner(layout.Slot(1, 1), top=True)

                mouse.drag(start, (start[0], rows[0] + (rows[1] - rows[0]) * 0.3))
                self.assertEqual(_slots(canvas), [('0.0', 0, 0, 1, 1), ('1.0', 1, 0, 1, 1), ('1.1', 0, 1, 2, 1)])
                mouse.drag(mouse.corner(layout.Slot(0, 1, 2, 1), top=True), (start[0], rows[1] + 20))

                self.assertEqual(_slots(canvas), [('0.0', 0, 0, 1, 1), ('1.0', 1, 0, 1, 1), ('1.1', 1, 1, 1, 1)])

    def test_the_last_plot_of_a_column_grows_below_the_grid_with_the_mouse_a_little_past_it(self):
        for backend in BACKENDS:
            with self.subTest(backend):
                # As in a window that fills the screen, where the mouse goes no further than its edge.
                canvas, qt_canvas, mouse, arranged = self._qt_canvas(backend)
                rows, cols = qt_canvas._grid_bounds()

                mouse.drag(mouse.corner(layout.Slot(2, 0)), (cols[1] - 20, rows[3] + HANDLE.px() + 4))

                self.assertEqual([(plot.plot_title, slot.row, slot.row_span) for plot, slot in
                                  layout.slots_of(canvas)], [('0.0', 0, 1), ('1.0', 1, 1), ('2.0', 2, 2)])

    def test_a_corner_dragged_a_few_pixels_past_a_bound_takes_no_more_rows_or_columns(self):
        # A plot stretched into the empty cell on its right along its row, the mouse a little below or above it: a
        # row more would take the plots below, or the rows below the grid, which it cannot.
        cases = (('a row with plots below', [(0, 1)], layout.Slot(0, 0), 1, (-12, 12),
                  [('0.0', 0, 0, 1, 2), ('1.0', 1, 0, 1, 1), ('1.1', 1, 1, 1, 1)]),
                 ('the last row', [(1, 1)], layout.Slot(1, 0), 2, (5,),
                  [('0.0', 0, 0, 1, 1), ('0.1', 0, 1, 1, 1), ('1.0', 1, 0, 1, 2)]))
        for backend in BACKENDS:
            for name, empty, slot, bound, drifts, expected in cases:
                for drift in drifts:
                    with self.subTest(backend, row=name, drift=drift):
                        canvas, qt_canvas, mouse, arranged = self._qt_canvas(backend, columns=(2, 2), empty=empty)
                        rows, cols = qt_canvas._grid_bounds()

                        mouse.drag(mouse.corner(slot), (cols[1] + (cols[2] - cols[1]) * 0.7, rows[bound] + drift))

                        self.assertEqual(_slots(canvas), expected)

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

    def test_the_cursor_shows_where_the_mouse_takes_a_plot(self):
        for backend in BACKENDS:
            with self.subTest(backend):
                canvas, qt_canvas, mouse, arranged = self._qt_canvas(backend)

                mouse.hover(mouse.cell(1, 0))
                self.assertEqual(mouse.widget.cursor().shape(), Qt.CursorShape.OpenHandCursor)

                mouse.hover(self._curve_point(qt_canvas, canvas, '1.0', 5, 5))
                self.assertNotEqual(mouse.widget.cursor().shape(), Qt.CursorShape.OpenHandCursor)

    def test_a_click_on_a_curve_draws_the_canvas_no_more(self):
        # A press on a curve, missing the background that moves the plot, must not cost a drawing of the canvas.
        canvas, qt_canvas, mouse, arranged = self._qt_canvas('matplotlib')

        with patch.object(qt_canvas, 'render') as render:
            mouse.click(self._curve_point(qt_canvas, canvas, '1.0', 5, 5))

        render.assert_not_called()
        self.assertEqual(_titles(canvas), [['0.0', '1.0', '2.0']])

    def test_the_resize_handle_shows_under_the_mouse(self):
        for backend in BACKENDS:
            with self.subTest(backend):
                canvas, qt_canvas, mouse, arranged = self._qt_canvas(backend)

                mouse.hover(mouse.corner(layout.Slot(1, 0)))

                self.assertTrue(qt_canvas._arranger._overlay.isVisible())
                self.assertEqual(mouse.widget.cursor().shape(), Qt.CursorShape.SizeFDiagCursor)

                mouse.hover(mouse.cell(1, 0))
                self.assertNotEqual(mouse.widget.cursor().shape(), Qt.CursorShape.SizeFDiagCursor)

    def test_the_resize_handle_shows_in_the_corner_nearest_the_mouse(self):
        for backend in BACKENDS:
            with self.subTest(backend):
                canvas, qt_canvas, mouse, arranged = self._qt_canvas(backend)
                arranger, slot = qt_canvas._arranger, layout.Slot(1, 0)
                rows, cols = qt_canvas._grid_bounds()

                for top, left, cursor in ((True, True, Qt.CursorShape.SizeFDiagCursor),
                                          (True, False, Qt.CursorShape.SizeBDiagCursor),
                                          (False, True, Qt.CursorShape.SizeBDiagCursor),
                                          (False, False, Qt.CursorShape.SizeFDiagCursor)):
                    # Towards the corner, then on its handle.
                    mouse.hover(mouse.cell(1, 0, fx=0.1 if left else 0.9, fy=0.1 if top else 0.9))
                    grip = arranger._grip
                    self.assertEqual((grip.top() == rows[1], grip.left() == cols[0]), (top, left))
                    mouse.hover(mouse.corner(slot, top, left))
                    self.assertEqual(mouse.widget.cursor().shape(), cursor)
                    self.assertTrue(arranger._overlay.isVisible())

    def test_the_mouse_over_a_curve_of_many_points_looks_at_the_points_near_it_only(self):
        for backend in BACKENDS:
            with self.subTest(backend):
                canvas, qt_canvas, mouse, arranged = self._qt_canvas(backend, points=200_000)
                distance = qt_canvas._min_distance_to_segments
                points = []

                def measured(coords, click):
                    points.append(len(coords))
                    return distance(coords, click)
                with patch.object(qt_canvas, '_min_distance_to_segments', side_effect=measured):
                    mouse.hover(mouse.cell(1, 0))
                    background = mouse.widget.cursor().shape()
                    mouse.hover(self._curve_point(qt_canvas, canvas, '1.0', 5, 5))

                self.assertEqual(background, Qt.CursorShape.OpenHandCursor)
                self.assertNotEqual(mouse.widget.cursor().shape(), Qt.CursorShape.OpenHandCursor)
                # Those a few pixels around the mouse, out of the 200 000 of each curve.
                self.assertTrue(points)
                self.assertLess(max(points), 20_000)

    def test_the_hand_comes_back_after_another_tool_showed_its_cursor(self):
        canvas, qt_canvas, mouse, arranged = self._qt_canvas('matplotlib')
        mouse.hover(mouse.cell(1, 0))
        qt_canvas.set_mouse_mode(Canvas.MOUSE_MODE_ZOOM)
        mouse.hover(mouse.cell(1, 0, fx=0.25))
        qt_canvas.set_mouse_mode(Canvas.MOUSE_MODE_SELECT)
        for fx in (0.2, 0.25, 0.3):
            mouse.hover(mouse.cell(1, 0, fx=fx))
        self.assertEqual(mouse.widget.cursor().shape(), Qt.CursorShape.OpenHandCursor)

        canvas, qt_canvas, mouse, arranged = self._qt_canvas('pyqt')
        view = qt_canvas._parser.figure
        eye = next(item for item in view.scene().items() if isinstance(item, _LegendEye))
        eye.setVisible(True)
        centre = view.viewport().mapTo(qt_canvas, view.mapFromScene(eye.sceneBoundingRect().center()))
        mouse.hover(mouse.cell(1, 0))
        mouse.hover((centre.x(), centre.y()))
        for fx in (0.2, 0.25, 0.3):
            mouse.hover(mouse.cell(1, 0, fx=fx))
        self.assertEqual(mouse.widget.cursor().shape(), Qt.CursorShape.OpenHandCursor)

    # Laying the plots out on a grid

    def test_the_plots_are_laid_out_on_the_grid_picked_without_drawing_them_again(self):
        for backend in BACKENDS:
            with self.subTest(backend):
                canvas, qt_canvas, mouse, arranged = self._qt_canvas(backend, columns=(4,))
                impls = {title: self._impl(qt_canvas, canvas, title) for title in ('0.0', '1.0', '2.0', '3.0')}

                with patch.object(qt_canvas, 'refresh') as refresh:
                    qt_canvas.lay_out(2, 2)
                    self.app.processEvents()

                refresh.assert_not_called()
                self.assertEqual(_titles(canvas), [['0.0', '1.0'], ['2.0', '3.0']])
                self.assertEqual({title: self._drawn_place(qt_canvas, impl) for title, impl in impls.items()},
                                 {'0.0': (0, 0, 1, 1), '1.0': (1, 0, 1, 1), '2.0': (0, 1, 1, 1), '3.0': (1, 1, 1, 1)})
                self.assertEqual(len(arranged), 1)
                self.assertEqual(qt_canvas.get_next_undo_cmd_name(), 'Layout')

                qt_canvas.undo()
                self.app.processEvents()
                self.assertEqual(_titles(canvas), [['0.0', '1.0', '2.0', '3.0']])
                self.assertEqual((canvas.layout_rows, canvas.layout_cols), (None, None))

    def test_the_plots_beyond_the_last_cell_are_drawn_as_stacks_of_one_plot_there(self):
        for backend in BACKENDS:
            with self.subTest(backend):
                canvas, qt_canvas, mouse, arranged = self._qt_canvas(backend)

                qt_canvas.lay_out(1, 2)
                self.app.processEvents()

                joined = canvas.plots[1][0]
                self.assertEqual([[signal.label for signal in signals] for signals in joined.signals.values()],
                                 [['s10'], ['s20']])
                self.assertEqual(len(qt_canvas._parser._plot_impl_plot_lut[id(joined)]), 2)
                self.assertEqual({((before.row, before.col, before.stack_offset), (after.row, after.col,
                                                                                   after.stack_offset))
                                  for before, after in arranged[-1]}, {((1, 0, 0), (0, 1, 0)), ((2, 0, 0), (0, 1, 1))})

                qt_canvas.undo()
                self.app.processEvents()
                self.assertEqual(_titles(canvas), [['0.0', '1.0', '2.0']])
                self.assertEqual([len(qt_canvas._parser._plot_impl_plot_lut[id(plot)]) for plot in canvas.plots[0]],
                                 [1, 1, 1])

    def test_a_joined_plot_shows_the_x_ranges_of_all_its_plots_and_undo_gives_each_its_own_back(self):
        for backend in BACKENDS:
            with self.subTest(backend):
                canvas, qt_canvas, mouse, arranged = self._qt_canvas(backend)
                parser = qt_canvas._parser
                # Without a shared time, each plot keeps a view of its own.
                canvas.shared_x_axis = False
                parser.set_oaw_axis_limits(self._impl(qt_canvas, canvas, '1.0'), 0, (1.0, 3.0))
                parser.set_oaw_axis_limits(self._impl(qt_canvas, canvas, '2.0'), 0, (5.0, 8.0))
                qt_canvas._flush_view()
                self.app.processEvents()

                qt_canvas.lay_out(1, 2)
                self.app.processEvents()
                for impl in parser._plot_impl_plot_lut[id(canvas.plots[1][0])]:
                    np.testing.assert_allclose(parser.get_oaw_axis_limits(impl, 0), (1.0, 8.0))

                qt_canvas.undo()
                self.app.processEvents()
                np.testing.assert_allclose(parser.get_oaw_axis_limits(self._impl(qt_canvas, canvas, '1.0'), 0),
                                           (1.0, 3.0))
                np.testing.assert_allclose(parser.get_oaw_axis_limits(self._impl(qt_canvas, canvas, '2.0'), 0),
                                           (5.0, 8.0))

    def test_undo_or_redo_that_takes_the_plot_in_focus_away_shows_all_the_plots(self):
        for backend in BACKENDS:
            with self.subTest(backend):
                canvas, qt_canvas, mouse, arranged = self._qt_canvas(backend)
                parser = qt_canvas._parser
                qt_canvas.lay_out(1, 2)
                self.app.processEvents()
                qt_canvas._full_screen_mode_on(parser._plot_impl_plot_lut[id(canvas.plots[1][0])][0])
                self.app.processEvents()

                qt_canvas.undo()
                self.app.processEvents()
                self.assertIsNone(parser._focus_plot)
                self.assertEqual([len(parser._plot_impl_plot_lut.get(id(plot), [])) for plot in canvas.plots[0]],
                                 [1, 1, 1])

                qt_canvas._full_screen_mode_on(self._impl(qt_canvas, canvas, '2.0'))
                self.app.processEvents()
                qt_canvas.redo()
                self.app.processEvents()
                self.assertIsNone(parser._focus_plot)
                self.assertEqual([len(parser._plot_impl_plot_lut.get(id(plot), []))
                                  for plot, _ in layout.slots_of(canvas)], [1, 2])

    def test_the_markers_window_shows_the_stack_a_marker_takes_in_a_joined_plot(self):
        for backend in BACKENDS:
            with self.subTest(backend):
                win = IplotQtMainWindow()
                self.addCleanup(win.close)
                canvas = _canvas((3,))
                qt_canvas = IplotQtCanvasFactory.new(backend, canvas=canvas)
                win.canvasStack.addWidget(qt_canvas)
                win.show()
                win.canvasStack.refreshLinks()
                self.app.processEvents()
                signal = next(iter(_plot(canvas, '2.0').signals.values()))[0]
                qt_canvas._marker_window.add_marker(signal, (5.0, 5.0), signal.label)

                qt_canvas.lay_out(1, 2)
                self.app.processEvents()
                self.assertEqual(qt_canvas._marker_window.table.item(0, 1).text(), '2.1.2')

                qt_canvas.undo()
                self.app.processEvents()
                self.assertEqual(qt_canvas._marker_window.table.item(0, 1).text(), '1.3.1')
                win.close()

    def test_the_mini_map_comes_with_the_one_plot_a_layout_leaves_and_goes_on_undo(self):
        win = IplotQtMainWindow()
        self.addCleanup(win.close)
        canvas = _canvas((2,))
        qt_canvas = IplotQtCanvasFactory.new('matplotlib', canvas=canvas)
        win.canvasStack.addWidget(qt_canvas)
        win.show()
        win.canvasStack.refreshLinks()
        self.app.processEvents()
        action = win.toolBar.minimapAction
        self.assertFalse(action.isEnabled())

        qt_canvas.lay_out(1, 1)
        self.app.processEvents()
        self.assertTrue(action.isEnabled())
        action.setChecked(True)
        self.app.processEvents()
        self.assertTrue(canvas.show_minimap)

        qt_canvas.undo()
        self.app.processEvents()
        self.assertEqual((action.isEnabled(), action.isChecked(), canvas.show_minimap), (False, False, False))

    def test_the_toolbar_lays_the_plots_out_on_the_grid_picked_in_its_menu(self):
        win = IplotQtMainWindow()
        self.addCleanup(win.close)
        canvas = _canvas((3,))
        qt_canvas = IplotQtCanvasFactory.new('matplotlib', canvas=canvas)
        win.canvasStack.addWidget(qt_canvas)
        win.show()
        self.app.processEvents()
        picker = win.toolBar.layoutPicker

        win.toolBar.layoutMenu.aboutToShow.emit()
        self.assertEqual([picker.outcome(1, 1), picker.outcome(1, 2), picker.outcome(3, 1), picker.outcome(2, 2)],
                         [2, 1, 0, 0])

        picker.picked.emit(3, 2)
        self.app.processEvents()
        self.assertEqual(_titles(canvas), [['0.0', '1.0', '2.0'], []])
        self.assertEqual((canvas.rows, canvas.cols), (3, 2))
        self.assertEqual(win.toolBar.undoAction.text(), 'Undo Layout')

        canvas.streaming = True
        win.toolBar.layoutMenu.aboutToShow.emit()
        canvas.streaming = False
        self.assertIsNone(picker.outcome(2, 2))
        self.assertIn('streaming', picker._label.text())

    def test_the_layout_picker_names_the_grid_under_the_mouse_and_picks_the_one_clicked(self):
        picker = LayoutPicker()
        self.addCleanup(picker.close)
        picker.set_outcomes({(rows, cols): (0 if rows * cols >= 3 else None if rows * cols == 1 else 3 - rows * cols)
                             for rows in range(1, LayoutPicker.ROWS + 1) for cols in range(1, LayoutPicker.COLS + 1)})
        picker.show()
        self.app.processEvents()
        picked = []
        picker.picked.connect(lambda rows, cols: picked.append((rows, cols)))
        step = CELL.px() + GAP.px()

        def at(rows, cols):
            return QPoint(round((cols - 0.5) * step), round((rows - 0.5) * step))

        def hover(rows, cols):
            # Straight to the cells: QTest.mouseMove moves the cursor of the platform, which goes to the first window
            # under it, and the small picker may lie under a window that another test left open.
            point = QPointF(at(rows, cols))
            QApplication.sendEvent(picker._cells, QMouseEvent(QEvent.Type.MouseMove, point,
                                                              picker._cells.mapToGlobal(point), Qt.MouseButton.NoButton,
                                                              Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier))

        hover(3, 2)
        self.assertEqual(picker._label.text(), '3 rows × 2 columns')
        hover(1, 2)
        self.assertEqual(picker._label.text(), '1 row × 2 columns: the last cell takes 2 plots as one')
        hover(1, 1)
        self.assertIn('cannot', picker._label.text())

        QTest.mouseClick(picker._cells, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, at(1, 1))
        QTest.mouseClick(picker._cells, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, at(3, 2))
        self.assertEqual(picked, [(3, 2)])

        picker.set_outcomes(None)
        self.assertIn('streaming', picker._label.text())

    # Dropping on the grid

    def _drag(self, qt_canvas, point, drop=True) -> bool:
        """A drag from elsewhere that comes over the canvas to the point, in the coordinates of the canvas widget, and
        drops there: whether the canvas took the last event."""
        widget = qt_canvas._arranger._widget
        local = widget.mapFrom(qt_canvas, QPoint(round(point[0]), round(point[1])))
        mime = QMimeData()
        mime.setText('variable')
        args = (Qt.DropAction.CopyAction | Qt.DropAction.MoveAction, mime, Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier)
        events = [QDragEnterEvent(local, *args), QDragMoveEvent(local, *args)]
        if drop:
            events.append(QDropEvent(QPointF(local), *args))
        for event in events:
            QApplication.sendEvent(widget, event)
            if not event.isAccepted():
                break
        self.app.processEvents()
        return event.isAccepted()

    def test_something_dropped_on_an_empty_cell_or_on_a_plot_tells_where(self):
        for backend in BACKENDS:
            with self.subTest(backend):
                canvas, qt_canvas, mouse, arranged = self._qt_canvas(backend, columns=(2, 1))
                qt_canvas.accepts_drop = lambda source, mime: True
                dropped = []
                qt_canvas.dropSignal.connect(dropped.append)

                self.assertTrue(self._drag(qt_canvas, mouse.cell(1, 1)))
                self.assertTrue(self._drag(qt_canvas, mouse.cell(1, 0)))
                self.app.processEvents()

                self.assertEqual([(info.row, info.col, info.stack) for info in dropped], [(2, 2, None), (2, 1, 1)])
                self.assertFalse(qt_canvas._arranger._overlay.isVisible())

    def test_a_grid_picked_for_a_canvas_with_no_plot_takes_drops_on_its_cells(self):
        for backend in BACKENDS:
            with self.subTest(backend):
                previous = getattr(self, '_shown', None)
                if previous is not None:
                    previous.close()
                    self.app.processEvents()
                canvas = Canvas(mouse_mode=Canvas.MOUSE_MODE_SELECT)
                qt_canvas = IplotQtCanvasFactory.new(backend, canvas=canvas)
                self._shown = qt_canvas
                self.addCleanup(qt_canvas.close)
                qt_canvas.resize(800, 900)
                qt_canvas.show()
                self.app.processEvents()
                qt_canvas.accepts_drop = lambda source, mime: True
                dropped = []
                qt_canvas.dropSignal.connect(dropped.append)

                qt_canvas.lay_out(2, 3)
                self.app.processEvents()
                self._drag(qt_canvas, _Mouse(qt_canvas, self.app).cell(1, 2))
                self.app.processEvents()

                self.assertEqual((canvas.rows, canvas.cols), (2, 3))
                self.assertEqual([(info.row, info.col, info.stack) for info in dropped], [(2, 3, None)])

    def test_something_dropped_on_a_plot_goes_to_the_stack_under_the_mouse(self):
        for backend in BACKENDS:
            with self.subTest(backend):
                canvas, qt_canvas, mouse, arranged = self._qt_canvas(backend)
                qt_canvas.lay_out(1, 1)
                self.app.processEvents()
                qt_canvas.accepts_drop = lambda source, mime: True
                dropped = []
                qt_canvas.dropSignal.connect(dropped.append)

                # Three stacks share the cell: the last one is at its bottom.
                self._drag(qt_canvas, mouse.cell(0, 0, fx=0.5, fy=0.85))
                self.app.processEvents()

                self.assertEqual([(info.row, info.col, info.stack) for info in dropped], [(1, 1, 3)])

    def test_a_drag_over_the_canvas_shows_the_cell_it_would_drop_on(self):
        for backend in BACKENDS:
            with self.subTest(backend):
                canvas, qt_canvas, mouse, arranged = self._qt_canvas(backend, columns=(2, 1))
                qt_canvas.accepts_drop = lambda source, mime: True
                rows, cols = qt_canvas._grid_bounds()

                self._drag(qt_canvas, mouse.cell(0, 0), drop=False)

                overlay = qt_canvas._arranger._overlay
                self.assertTrue(overlay.isVisible())
                empty = QRectF(QPointF(cols[1], rows[1]), QPointF(cols[2], rows[2]))
                plot = QRectF(QPointF(cols[0], rows[0]), QPointF(cols[1], rows[1]))
                self.assertEqual(overlay._shapes, [(empty, _Overlay.RESERVED), (plot, _Overlay.TARGET)])

                QApplication.sendEvent(qt_canvas._arranger._widget, QDragLeaveEvent())
                self.assertFalse(overlay.isVisible())

    def test_nothing_the_application_does_not_take_is_dropped_nor_anything_while_streaming(self):
        for backend in BACKENDS:
            with self.subTest(backend):
                canvas, qt_canvas, mouse, arranged = self._qt_canvas(backend, columns=(2, 1))
                dropped = []
                qt_canvas.dropSignal.connect(dropped.append)

                self.assertFalse(self._drag(qt_canvas, mouse.cell(1, 1)))
                qt_canvas.accepts_drop = lambda source, mime: True
                canvas.streaming = True
                self.assertFalse(self._drag(qt_canvas, mouse.cell(1, 1)))
                canvas.streaming = False
                self.app.processEvents()

                self.assertEqual(dropped, [])
                self.assertFalse(qt_canvas._arranger._overlay.isVisible())


if __name__ == '__main__':
    unittest.main()
