"""
Moving and resizing the plots of a canvas with the mouse, in the select mode. A plot dragged by its background moves
and one dragged by its bottom right corner takes another size; while the mouse moves, an overlay shows where the
plots go (see iplotlib.core.layout).
"""

from functools import partial
from typing import List, Optional, Sequence, Tuple

from PySide6.QtCore import QEvent, QObject, QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPalette, QPen
from PySide6.QtWidgets import QAbstractScrollArea, QApplication, QWidget

from iplotlib.core import layout
from iplotlib.core.display import ScaledPixels
from iplotlib.core.layout import Arrangement, Slot

# Side of the square in the bottom right corner of a plot where a drag resizes it.
HANDLE = ScaledPixels(14)

MOVE, RESIZE = 'Move plot', 'Resize plot'

# The bounds of the rows and of the columns of the grid of the canvas, from its top and from its left, in the
# coordinates of the canvas widget: n + 1 values for n rows or columns.
Bounds = Tuple[List[float], List[float]]

# The events of the widget that the arranger acts on; it lets the others through untouched.
_EVENTS = frozenset({QEvent.Type.MouseButtonPress, QEvent.Type.MouseMove, QEvent.Type.MouseButtonRelease,
                     QEvent.Type.KeyPress, QEvent.Type.Hide, QEvent.Type.Leave})


class _Gesture:
    def __init__(self, kind: str, plot, slot: Slot, start: QPointF, grab: Tuple[int, int] = (0, 0)):
        self.kind = kind
        self.plot = plot
        self.slot = slot
        self.start = start
        # The cell the plot was grabbed by, from its top left one.
        self.grab = grab
        # A move starts once the mouse has gone some way with the button down; a resize, on the press.
        self.started = kind == RESIZE
        self.arrangement = None  # type: Optional[Arrangement]
        self.target = slot
        # The slots the application reserves for plots it does not draw now, read once the gesture starts.
        self.reserved = None  # type: Optional[List[Slot]]


class PlotArranger(QObject):
    """Watches the mouse over the widget that draws the plots of an IplotQtCanvas. The canvas gives the bounds of its
    grid, says whether the plots can be arranged now and whether a press or a drag is someone else's (a curve, a
    legend, a slider), and lays itself out (see IplotQtCanvas._apply_arrangement)."""

    def __init__(self, canvas, widget: QWidget):
        super().__init__(canvas)
        self._canvas = canvas
        self._widget = widget
        self._overlay = _Overlay(canvas)
        self._gesture = None  # type: Optional[_Gesture]
        self._grip = None  # type: Optional[QRectF] # the resize handle shown under the mouse
        self._hand = False  # whether the widget shows the resize cursor
        widget.setMouseTracking(True)
        widget.installEventFilter(self)
        # A view that draws in a viewport takes the keys itself.
        view = widget.parentWidget()
        if isinstance(view, QAbstractScrollArea) and view.viewport() is widget:
            view.installEventFilter(self)

    def eventFilter(self, watched, event) -> bool:
        kind = event.type()
        # Qt still sends events while it destroys the canvas, which the garbage collector of Python can do after
        # it cleared the arranger: then nothing is left to act on.
        if kind not in _EVENTS or not hasattr(self, '_widget'):
            return False
        if watched is not self._widget:
            if kind == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Escape and self._gesture is not None:
                self.cancel()
                return True
            return False
        if kind == QEvent.Type.MouseButtonPress:
            return self._press(event)
        if kind == QEvent.Type.MouseMove:
            return self._move(event)
        if kind == QEvent.Type.MouseButtonRelease:
            return self._release(event)
        if kind == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Escape and self._gesture is not None:
            self.cancel()
            return True
        if kind == QEvent.Type.Hide:
            self.cancel()
        elif kind == QEvent.Type.Leave and self._gesture is None:
            self._show_grip(None)
        return False

    def cancel(self):
        """Forget the gesture under way, if any, leaving the plots where they are."""
        gesture, self._gesture = self._gesture, None
        if gesture is not None and gesture.started:
            QApplication.restoreOverrideCursor()
        self._overlay.clear()
        self._show_grip(None)

    # The mouse

    def _press(self, event) -> bool:
        if self._gesture is not None:
            # A press during a gesture: another button, or the left one again after its release went elsewhere.
            self.cancel()
        if event.button() != Qt.MouseButton.LeftButton:
            return False
        point = self._point(event)
        found = self._plot_at(point)
        if found is None or self._canvas._press_taken(point):
            return False
        plot, slot, bounds = found
        if self._handle(_rect(bounds, slot)).contains(point):
            self._gesture = _Gesture(RESIZE, plot, slot, point)
            self._show_grip(None)
            QApplication.setOverrideCursor(Qt.CursorShape.SizeFDiagCursor)
            self._update(point, bounds)
            # The plot does not see the press: a drag from its corner resizes it and nothing else.
            return True
        row, col = _cell(bounds[0], point.y()), _cell(bounds[1], point.x())
        self._gesture = _Gesture(MOVE, plot, slot, point, (row - slot.row, col - slot.col))
        return False

    def _move(self, event) -> bool:
        point = self._point(event)
        gesture = self._gesture
        if gesture is None:
            self._hover(point if event.buttons() == Qt.MouseButton.NoButton else None)
            return False
        if not event.buttons() & Qt.MouseButton.LeftButton:
            # The release of the button went elsewhere, to a menu for one: the gesture ends without moving anything.
            self.cancel()
            return False
        bounds = self._bounds()
        if not gesture.started:
            # The press may have started something else: a shift of a curve, a drag of a legend or of a slider.
            if bounds is None or self._canvas._drag_taken():
                self._gesture = None
                return False
            if (point - gesture.start).manhattanLength() < QApplication.startDragDistance():
                return False
            gesture.started = True
            self._show_grip(None)
            QApplication.setOverrideCursor(Qt.CursorShape.ClosedHandCursor)
        if bounds is not None:
            self._update(point, bounds)
        return True

    def _release(self, event) -> bool:
        gesture = self._gesture
        if gesture is None or event.button() != Qt.MouseButton.LeftButton:
            return False
        self._gesture = None
        if not gesture.started:
            return False
        QApplication.restoreOverrideCursor()
        self._overlay.clear()
        if gesture.arrangement is not None:
            # The plot saw the press of a move, and sees its release before the plots move: a click the backend makes
            # of them reaches the plot the press was on, not the one that takes its place.
            QTimer.singleShot(0, self, partial(self._canvas._apply_arrangement, gesture.kind, gesture.arrangement))
        # The plot saw the press of a move, not that of a resize.
        return gesture.kind == RESIZE

    def _hover(self, point: Optional[QPointF]):
        grip = None
        if point is not None and self._canvas._arrangement_allowed():
            found = self._plot_at(point)
            if found is not None:
                plot, slot, bounds = found
                grip = self._handle(_rect(bounds, slot))
        self._show_grip(grip, point is not None and grip is not None and grip.contains(point))

    # Where the plots go

    def _update(self, point: QPointF, bounds: Bounds):
        gesture = self._gesture
        canvas = self._canvas.get_canvas()
        if gesture.reserved is None:
            gesture.reserved = layout.current(canvas, self._canvas.reserved_slots()).reserved
        row, col = _cell(bounds[0], point.y()), _cell(bounds[1], point.x())
        if gesture.kind == MOVE:
            gesture.arrangement = layout.moved(canvas, gesture.plot, row, col, *gesture.grab,
                                               reserved=gesture.reserved)
            rows, cols = layout.grid_size(canvas)
            top = min(max(row - gesture.grab[0], 0), rows - gesture.slot.row_span)
            left = min(max(col - gesture.grab[1], 0), cols - gesture.slot.col_span)
            gesture.target = gesture.slot.moved_to(top, left) if not gesture.slot.contains(row, col) else gesture.slot
        else:
            # Below the grid the rows go on, as tall as its last one: a plot can grow past the bottom of its columns.
            row = _row_below(bounds[0], point.y())
            row_span, col_span = max(1, row - gesture.slot.row + 1), max(1, col - gesture.slot.col + 1)
            limit = self._canvas.max_span()
            if limit:
                # The application draws no bigger plot.
                row_span, col_span = min(row_span, limit), min(col_span, limit)
            gesture.target = Slot(gesture.slot.row, gesture.slot.col, row_span, col_span)
            gesture.arrangement = layout.resized(canvas, gesture.plot, gesture.target.row_span,
                                                 gesture.target.col_span, reserved=gesture.reserved)
        allowed = gesture.arrangement is not None or gesture.target == gesture.slot
        QApplication.changeOverrideCursor(Qt.CursorShape.ForbiddenCursor if not allowed else
                                          Qt.CursorShape.ClosedHandCursor if gesture.kind == MOVE else
                                          Qt.CursorShape.SizeFDiagCursor)
        shapes = []
        if gesture.arrangement is not None:
            after = self._preview_bounds(bounds, gesture.arrangement)
            before = {id(plot): slot for plot, slot in layout.slots_of(canvas)}
            taken = [slot for _, slot in gesture.arrangement.slots] + gesture.arrangement.reserved
            # Where the plot was, if nothing takes its place.
            if after is bounds and not any(slot.overlaps(gesture.slot) for slot in taken):
                shapes.append((_rect(bounds, gesture.slot), _Overlay.SOURCE))
            shapes += _reserved_shapes(after, gesture.arrangement.reserved)
            for plot, slot in gesture.arrangement.slots:
                if plot is gesture.plot:
                    shapes.append((_rect(after, slot), _Overlay.TARGET))
                # With another number of rows or columns, every plot takes another size.
                elif before.get(id(plot)) != slot or after is not bounds:
                    shapes.append((_rect(after, slot), _Overlay.MOVED))
        else:
            shapes.append((_rect(bounds, gesture.slot), _Overlay.SOURCE))
            shapes += _reserved_shapes(bounds, gesture.reserved)
            if not allowed:
                shapes.append((_rect(bounds, _within(gesture.target, bounds)), _Overlay.FORBIDDEN))
        self._overlay.show_shapes(shapes)

    @staticmethod
    def _preview_bounds(bounds: Bounds, arrangement: Arrangement) -> Bounds:
        """The bounds the grid would have for the arrangement: those it has, or the same room shared out evenly
        between the rows and the columns it would have."""
        rows, cols = bounds
        if len(rows) == arrangement.rows + 1 and len(cols) == arrangement.cols + 1:
            return bounds
        return _even(rows[0], rows[-1], arrangement.rows), _even(cols[0], cols[-1], arrangement.cols)

    # Geometry

    def _point(self, event) -> QPointF:
        return QPointF(self._widget.mapTo(self._canvas, event.position().toPoint()))

    def _bounds(self) -> Optional[Bounds]:
        canvas = self._canvas.get_canvas()
        bounds = self._canvas._grid_bounds() if canvas is not None else None
        if bounds is None:
            return None
        rows, cols = layout.grid_size(canvas)
        if len(bounds[0]) != rows + 1 or len(bounds[1]) != cols + 1:
            return None
        return bounds

    def _plot_at(self, point: QPointF):
        """The plot under the point with its slot, and the bounds of the grid, if the plots can be arranged."""
        if not self._canvas._arrangement_allowed():
            return None
        bounds = self._bounds()
        if bounds is None or not _rect(bounds, Slot(0, 0, len(bounds[0]) - 1, len(bounds[1]) - 1)).contains(point):
            return None
        row, col = _cell(bounds[0], point.y()), _cell(bounds[1], point.x())
        for plot, slot in layout.slots_of(self._canvas.get_canvas()):
            if slot.contains(row, col):
                return plot, slot, bounds
        return None

    @staticmethod
    def _handle(rect: QRectF) -> QRectF:
        side = HANDLE.px()
        return QRectF(rect.right() - side, rect.bottom() - side, side, side)

    def _show_grip(self, grip: Optional[QRectF], hand: bool = False):
        if grip != self._grip:
            self._grip = grip
            if grip is None:
                self._overlay.clear()
            else:
                self._overlay.show_shapes([(grip, _Overlay.GRIP)])
        if hand != self._hand:
            self._hand = hand
            if hand:
                self._widget.setCursor(Qt.CursorShape.SizeFDiagCursor)
            else:
                self._widget.unsetCursor()


def _cell(bounds: Sequence[float], value: float) -> int:
    """The row or the column at `value`: the first or the last one beyond the grid."""
    for index in range(len(bounds) - 2):
        if value < bounds[index + 1]:
            return index
    return len(bounds) - 2


def _row_below(rows: Sequence[float], y: float) -> int:
    """The row at `y`, counting rows below the grid as tall as its last one."""
    height = rows[-1] - rows[-2]
    if y < rows[-1] or height <= 0:
        return _cell(rows, y)
    return len(rows) - 1 + int((y - rows[-1]) // height)


def _rect(bounds: Bounds, slot: Slot) -> QRectF:
    rows, cols = bounds
    return QRectF(QPointF(cols[slot.col], rows[slot.row]), QPointF(cols[slot.right], rows[slot.bottom]))


def _within(slot: Slot, bounds: Bounds) -> Slot:
    """The part of the slot inside the grid."""
    rows, cols = len(bounds[0]) - 1, len(bounds[1]) - 1
    return Slot(slot.row, slot.col, max(1, min(slot.row_span, rows - slot.row)),
                max(1, min(slot.col_span, cols - slot.col)))


def _even(start: float, end: float, count: int) -> List[float]:
    return [start + (end - start) * index / count for index in range(count + 1)]


def _reserved_shapes(bounds: Bounds, reserved: Sequence[Slot]) -> List[Tuple[QRectF, int]]:
    """The reserved slots that start inside the grid, cut to it: nothing is drawn there, so the overlay shows them."""
    rows, cols = len(bounds[0]) - 1, len(bounds[1]) - 1
    return [(_rect(bounds, _within(slot, bounds)), _Overlay.RESERVED) for slot in reserved
            if slot.row < rows and slot.col < cols]


class _Overlay(QWidget):
    """Draws over the canvas where the plots go while one moves or takes another size, and the resize handle of the
    plot under the mouse. The mouse goes through it to the plots."""

    SOURCE, TARGET, MOVED, FORBIDDEN, GRIP, RESERVED = range(6)

    def __init__(self, canvas: QWidget):
        super().__init__(canvas)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self._shapes = []  # type: List[Tuple[QRectF, int]]
        self.hide()

    def show_shapes(self, shapes: List[Tuple[QRectF, int]]):
        self._shapes = shapes
        self.setGeometry(self.parentWidget().rect())
        self.raise_()
        self.show()
        self.update()

    def clear(self):
        self._shapes = []
        self.hide()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        accent = self.palette().color(QPalette.ColorRole.Highlight)
        neutral = self.palette().color(QPalette.ColorRole.Dark)
        inset = ScaledPixels(3).px()
        for rect, style in self._shapes:
            if style == self.GRIP:
                self._paint_grip(painter, rect, neutral)
                continue
            box = rect.adjusted(inset, inset, -inset, -inset)
            color = accent if style in (self.TARGET, self.MOVED) else neutral
            fill = QColor(color)
            fill.setAlpha({self.SOURCE: 25, self.TARGET: 70, self.MOVED: 18, self.FORBIDDEN: 45,
                           self.RESERVED: 12}[style])
            pen = QPen(color, ScaledPixels(2).px() if style == self.TARGET else ScaledPixels(1.5).px())
            if style != self.TARGET:
                pen.setStyle(Qt.PenStyle.DotLine if style == self.RESERVED else Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.setBrush(fill)
            radius = ScaledPixels(4).px()
            painter.drawRoundedRect(box, radius, radius)
        painter.end()

    @staticmethod
    def _paint_grip(painter: QPainter, rect: QRectF, color: QColor):
        """Three short diagonal strokes in the corner, the usual sign of a size grip."""
        painter.setPen(QPen(color, ScaledPixels(1.5).px()))
        corner = rect.bottomRight() - QPointF(ScaledPixels(3).px(), ScaledPixels(3).px())
        step = rect.width() / 4
        for index in range(1, 4):
            offset = step * index
            painter.drawLine(corner - QPointF(offset, 0), corner - QPointF(0, offset))
