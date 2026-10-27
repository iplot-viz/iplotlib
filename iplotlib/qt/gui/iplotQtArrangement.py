"""
Moving and resizing the plots of a canvas with the mouse, in the select mode. A plot dragged by its background moves
and one dragged by a corner takes another size, the opposite corner staying where it is; while the mouse moves, an
overlay shows where the plots go (see iplotlib.core.layout). Things the application takes, such as variables of its
variable browser, can be dropped on a cell of the grid, in any mode: the overlay shows the cell under the mouse among
those no plot is drawn on.
"""

from functools import partial
from typing import List, Optional, Sequence, Tuple

from PySide6.QtCore import QEvent, QObject, QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPalette, QPen
from PySide6.QtWidgets import QAbstractScrollArea, QApplication, QWidget

from iplotlib.core import layout
from iplotlib.core.display import ScaledPixels
from iplotlib.core.drop_info import DropInfo
from iplotlib.core.layout import Arrangement, Slot

# Side of the square in a corner of a plot where a drag resizes it.
HANDLE = ScaledPixels(14)

MOVE, RESIZE, LAYOUT = 'Move plot', 'Resize plot', 'Layout'

# A corner of a plot, as whether it is a top one and whether it is a left one.
Corner = Tuple[bool, bool]
BOTTOM_RIGHT = (False, False)

# The bounds of the rows and of the columns of the grid of the canvas, from its top and from its left, in the
# coordinates of the canvas widget: n + 1 values for n rows or columns.
Bounds = Tuple[List[float], List[float]]

# The events of a drag from elsewhere over the widget.
_DRAGS = frozenset({QEvent.Type.DragEnter, QEvent.Type.DragMove, QEvent.Type.DragLeave, QEvent.Type.Drop})

# The events of the widget that the arranger acts on; it lets the others through untouched.
_EVENTS = frozenset({QEvent.Type.MouseButtonPress, QEvent.Type.MouseMove, QEvent.Type.MouseButtonRelease,
                     QEvent.Type.KeyPress, QEvent.Type.Hide, QEvent.Type.Leave}) | _DRAGS


class _Gesture:
    def __init__(self, kind: str, plot, slot: Slot, start: QPointF, grab: Tuple[int, int] = (0, 0),
                 corner: Corner = BOTTOM_RIGHT):
        self.kind = kind
        self.plot = plot
        self.slot = slot
        self.start = start
        # The cell the plot was grabbed by, from its top left one.
        self.grab = grab
        # The corner a resize drags.
        self.corner = corner
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
        self._cursor = None  # type: Optional[Qt.CursorShape] # the cursor the widget shows to resize or move
        # The slots the application reserves, read once a drag from elsewhere comes in (see _drop_target).
        self._drop_reserved = None  # type: Optional[List[Slot]]
        widget.setMouseTracking(True)
        widget.setAcceptDrops(True)
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
        if kind in _DRAGS:
            return self._drag(event)
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
        rect = _rect(bounds, slot)
        corner = _corner_at(rect, point)
        if self._handle(rect, corner).contains(point):
            self._gesture = _Gesture(RESIZE, plot, slot, point, corner=corner)
            self._show_grip(None)
            QApplication.setOverrideCursor(_resize_cursor(corner))
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
        grip = cursor = None
        corner = BOTTOM_RIGHT
        if point is not None and self._canvas._arrangement_allowed():
            found = self._plot_at(point)
            if found is not None:
                plot, slot, bounds = found
                rect = _rect(bounds, slot)
                # The handle of the corner the mouse is nearest to.
                corner = _corner_at(rect, point)
                grip = self._handle(rect, corner)
                # As a press there would do (see _press): a press on a curve shifts the curve instead.
                if self._canvas._press_taken(point):
                    pass
                elif grip.contains(point):
                    cursor = _resize_cursor(corner)
                elif not self._canvas._press_shifts(point):
                    cursor = Qt.CursorShape.OpenHandCursor
        self._show_grip(grip, cursor, corner)

    # Drops

    def _drag(self, event) -> bool:
        """A drag from elsewhere over the widget: the cell a drop would go to shows, and a drop there tells the canvas
        (see IplotQtCanvas.dropSignal). Only a drag of something the application takes comes in."""
        kind = event.type()
        if kind == QEvent.Type.DragLeave:
            self._drop_reserved = None
            self._overlay.clear()
            return True
        if kind == QEvent.Type.DragEnter:
            if not self._canvas._drop_allowed(event.source(), event.mimeData()):
                event.ignore()
                return True
            self._show_grip(None)
            self._drop_reserved = layout.current(self._canvas.get_canvas(), self._canvas.reserved_slots()).reserved
        target = self._drop_target(event)
        if kind == QEvent.Type.Drop:
            self._drop_reserved = None
            self._overlay.clear()
            if target is None:
                event.ignore()
                return True
            slot, stack, _ = target
            info = DropInfo(slot.row + 1, slot.col + 1, stack, event.source())
            # Once the drop is over: the drag waits for it, and what the application does with it can take a while.
            QTimer.singleShot(0, self._canvas, partial(self._canvas.dropSignal.emit, info))
        elif target is None:
            self._overlay.clear()
            if kind == QEvent.Type.DragMove:
                # Not here, but the drag may come over a cell.
                event.ignore()
                return True
        else:
            slot, _, bounds = target
            self._overlay.show_shapes(self._drop_shapes(bounds, slot))
        # A copy: what was dragged stays where it came from.
        if event.possibleActions() & Qt.DropAction.CopyAction:
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
        else:
            event.acceptProposedAction()
        return True

    def _drop_target(self, event):
        """Where a drop at the event goes: the slot of the plot or of the reserved slot there, or the empty cell, with
        the stack of the plot under the mouse if the backend tells, and the bounds of the grid. None if it cannot."""
        if self._drop_reserved is None or not self._canvas._drop_allowed(event.source(), event.mimeData()):
            return None
        bounds = self._bounds()
        point = QPointF(self._widget.mapTo(self._canvas, event.position().toPoint()))
        if bounds is None or not _rect(bounds, Slot(0, 0, len(bounds[0]) - 1, len(bounds[1]) - 1)).contains(point):
            return None
        row, col = _cell(bounds[0], point.y()), _cell(bounds[1], point.x())
        for plot, slot in layout.slots_of(self._canvas.get_canvas()):
            if slot.contains(row, col):
                return slot, self._canvas._stack_at(point, plot), bounds
        slot = next((slot for slot in self._drop_reserved if slot.contains(row, col)), Slot(row, col))
        return slot, None, bounds

    def _drop_shapes(self, bounds: Bounds, target: Slot) -> List[Tuple[QRectF, int]]:
        """The cells no plot is drawn on, and the slot a drop goes to."""
        taken = [slot for _, slot in layout.slots_of(self._canvas.get_canvas())] + [target]
        rows, cols = len(bounds[0]) - 1, len(bounds[1]) - 1
        empty = [Slot(row, col) for row in range(rows) for col in range(cols)
                 if not any(slot.contains(row, col) for slot in taken)]
        return [(_rect(bounds, slot), _Overlay.RESERVED) for slot in empty] + [(_rect(bounds, target), _Overlay.TARGET)]

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
            target = gesture.target = self._resized(gesture, point, bounds)
            gesture.arrangement = layout.resized(canvas, gesture.plot, target.row_span, target.col_span,
                                                 reserved=gesture.reserved, row=target.row, col=target.col)
        allowed = gesture.arrangement is not None or gesture.target == gesture.slot
        QApplication.changeOverrideCursor(Qt.CursorShape.ForbiddenCursor if not allowed else
                                          Qt.CursorShape.ClosedHandCursor if gesture.kind == MOVE else
                                          _resize_cursor(gesture.corner))
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

    def _resized(self, gesture: _Gesture, point: QPointF, bounds: Bounds) -> Slot:
        """The slot of the plot with the corner it was grabbed by dragged to the point, the opposite one staying. Each
        side that moves goes to the bound of the grid nearest the point: the plot takes a row or a column more or less
        once the point is past the middle of it, not as soon as a few pixels cross a bound, and keeps one at least.
        Below the grid the rows go on, as tall as its last one, from a handle's side past it: a plot can grow past
        the bottom of its columns (see _nearest)."""
        slot, (top_side, left_side) = gesture.slot, gesture.corner
        top, bottom, left, right = slot.row, slot.bottom, slot.col, slot.right
        if top_side:
            top = min(_nearest(bounds[0], point.y()), bottom - 1)
        else:
            bottom = max(_nearest(bounds[0], point.y(), beyond=True), top + 1)
        if left_side:
            left = min(_nearest(bounds[1], point.x()), right - 1)
        else:
            right = max(_nearest(bounds[1], point.x()), left + 1)
        limit = self._canvas.max_span()
        if limit:
            # The application draws no bigger plot: the side that moves stops short.
            if bottom - top > limit:
                top, bottom = (bottom - limit, bottom) if top_side else (top, top + limit)
            if right - left > limit:
                left, right = (right - limit, right) if left_side else (left, left + limit)
        return Slot(top, left, bottom - top, right - left)

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
    def _handle(rect: QRectF, corner: Corner) -> QRectF:
        side = HANDLE.px()
        top, left = corner
        return QRectF(rect.left() if left else rect.right() - side, rect.top() if top else rect.bottom() - side,
                      side, side)

    def _show_grip(self, grip: Optional[QRectF], cursor: Optional[Qt.CursorShape] = None,
                   corner: Corner = BOTTOM_RIGHT):
        if grip != self._grip:
            self._grip = grip
            if grip is None:
                self._overlay.clear()
            else:
                self._overlay.show_shapes([(grip, _Overlay.GRIP)], corner)
        # The backends set the cursor of the same widget for their own tools (a mouse mode, the eye of a legend):
        # the one wanted goes back on when another took its place.
        if cursor != self._cursor or (cursor is not None and self._widget.cursor().shape() != cursor):
            self._cursor = cursor
            if cursor is not None:
                self._widget.setCursor(cursor)
            else:
                self._widget.unsetCursor()


def _cell(bounds: Sequence[float], value: float) -> int:
    """The row or the column at `value`: the first or the last one beyond the grid."""
    for index in range(len(bounds) - 2):
        if value < bounds[index + 1]:
            return index
    return len(bounds) - 2


def _nearest(bounds: Sequence[float], value: float, beyond: bool = False) -> int:
    """The bound nearest `value`, the later one half way between two. With `beyond`, a value past the last bound by
    the side of a resize handle counts a bound more, and one more for each further step as long as the last one:
    past the grid the mouse soon meets the edge of the screen."""
    step = bounds[-1] - bounds[-2]
    past = value - bounds[-1] - HANDLE.px()
    if beyond and past >= 0 and step > 0:
        return len(bounds) + int(past / step)
    return min(range(len(bounds)), key=lambda index: (abs(bounds[index] - value), -index))


def _corner_at(rect: QRectF, point: QPointF) -> Corner:
    """The corner of the rectangle nearest the point."""
    centre = rect.center()
    return point.y() < centre.y(), point.x() < centre.x()


def _resize_cursor(corner: Corner) -> Qt.CursorShape:
    """The arrows along the diagonal of the corner."""
    top, left = corner
    return Qt.CursorShape.SizeFDiagCursor if top == left else Qt.CursorShape.SizeBDiagCursor


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
        self._grip_corner = BOTTOM_RIGHT
        self.hide()

    def show_shapes(self, shapes: List[Tuple[QRectF, int]], grip_corner: Corner = BOTTOM_RIGHT):
        """Show the shapes, a grip among them in the corner of the plot given."""
        self._shapes = shapes
        self._grip_corner = grip_corner
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
                self._paint_grip(painter, rect, neutral, self._grip_corner)
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
    def _paint_grip(painter: QPainter, rect: QRectF, color: QColor, corner: Corner):
        """Three short diagonal strokes in the corner of the plot, the usual sign of a size grip."""
        painter.setPen(QPen(color, ScaledPixels(1.5).px()))
        top, left = corner
        inset = ScaledPixels(3).px()
        # From the corner of the square towards its middle.
        x = rect.left() + inset if left else rect.right() - inset
        y = rect.top() + inset if top else rect.bottom() - inset
        across, down = (1 if left else -1), (1 if top else -1)
        step = rect.width() / 4
        for index in range(1, 4):
            offset = step * index
            painter.drawLine(QPointF(x + across * offset, y), QPointF(x, y + down * offset))
