"""
The grid that the Layout tool of the toolbar offers: the mouse picks how many rows and columns to lay the plots of the
canvas out on, as a word processor picks the size of a table (see IplotQtCanvas.lay_out).
"""

from typing import Dict, Optional, Tuple

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPalette, QPen
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from iplotlib.core.display import ScaledPixels

# Side of a cell of the grid, and the gap between two cells.
CELL, GAP = ScaledPixels(16), ScaledPixels(3)
# Width of the line below the grid that names it.
LABEL_WIDTH = ScaledPixels(210)


class LayoutPicker(QWidget):
    """Cells to pick a grid from: those from the top left one to the one under the mouse light up, the line below
    names the grid, and a click picks it. A grid the plots cannot be laid out on shows grey and takes no click."""

    # The largest grid offered.
    ROWS, COLS = 10, 6

    picked = Signal(int, int)

    def __init__(self, parent: QWidget = None):
        super().__init__(parent)
        # How many plots besides its own the last cell of each grid takes, by (rows, cols), None for a grid the plots
        # cannot be laid out on (see IplotQtCanvas.layout_outcomes). None for none now.
        self._outcomes = None  # type: Optional[Dict[Tuple[int, int], Optional[int]]]
        self._cells = _Cells(self)
        self._label = QLabel(self)
        self._label.setWordWrap(True)
        # Wide enough for the name of any grid on one line, and high enough for two, so the menu keeps its size.
        self._label.setMinimumWidth(LABEL_WIDTH.px())
        self._label.setMinimumHeight(2 * self._label.fontMetrics().lineSpacing())
        self._label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        layout = QVBoxLayout(self)
        layout.addWidget(self._cells, alignment=Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(self._label)
        self._cells.hovered.connect(self._show)
        self._cells.clicked.connect(self._pick)
        self._show(None)

    def set_outcomes(self, outcomes: Optional[Dict[Tuple[int, int], Optional[int]]]):
        """What each grid would do, as IplotQtCanvas.layout_outcomes gives it: what the picker shows next."""
        self._outcomes = outcomes if outcomes and any(value is not None for value in outcomes.values()) else None
        self._cells.hovered_size = None
        self._cells.update()
        self._show(None)

    def outcome(self, rows: int, cols: int) -> Optional[int]:
        return None if self._outcomes is None else self._outcomes.get((rows, cols))

    def _show(self, size: Optional[Tuple[int, int]]):
        if self._outcomes is None:
            self._label.setText('Not while streaming or with a plot in focus')
            return
        if size is None:
            self._label.setText('Pick the rows and columns of the grid')
            return
        rows, cols = size
        name = f"{rows} {'row' if rows == 1 else 'rows'} × {cols} {'column' if cols == 1 else 'columns'}"
        joined = self.outcome(rows, cols)
        if joined is None:
            self._label.setText(f'{name}: the plots that do not fit cannot be merged into one')
        elif joined:
            self._label.setText(f'{name}: the last cell takes {joined + 1} plots as one')
        else:
            self._label.setText(name)

    def _pick(self, rows: int, cols: int):
        if self.outcome(rows, cols) is not None:
            self.picked.emit(rows, cols)


class _Cells(QWidget):
    """The cells of the picker, which follow the mouse."""

    hovered = Signal(object)
    clicked = Signal(int, int)

    def __init__(self, picker: LayoutPicker):
        super().__init__(picker)
        self._picker = picker
        self.hovered_size = None  # type: Optional[Tuple[int, int]]
        self.setMouseTracking(True)

    def sizeHint(self) -> QSize:
        step = CELL.px() + GAP.px()
        return QSize(round(LayoutPicker.COLS * step - GAP.px()), round(LayoutPicker.ROWS * step - GAP.px()))

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def _size_at(self, x: float, y: float) -> Optional[Tuple[int, int]]:
        step = CELL.px() + GAP.px()
        row, col = int(y // step) + 1, int(x // step) + 1
        if x < 0 or y < 0 or row > LayoutPicker.ROWS or col > LayoutPicker.COLS:
            return None
        return row, col

    def mouseMoveEvent(self, event):
        size = self._size_at(event.position().x(), event.position().y())
        if size != self.hovered_size:
            self.hovered_size = size
            self.update()
            self.hovered.emit(size)

    def leaveEvent(self, event):
        self.hovered_size = None
        self.update()
        self.hovered.emit(None)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            size = self._size_at(event.position().x(), event.position().y())
            if size is not None:
                self.clicked.emit(*size)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        palette = self.palette()
        accent, neutral = palette.color(QPalette.ColorRole.Highlight), palette.color(QPalette.ColorRole.Mid)
        rows, cols = self.hovered_size or (0, 0)
        allowed = self._picker.outcome(rows, cols) is not None
        side, step, radius = CELL.px(), CELL.px() + GAP.px(), ScaledPixels(2).px()
        for row in range(LayoutPicker.ROWS):
            for col in range(LayoutPicker.COLS):
                lit = row < rows and col < cols
                color = accent if lit and allowed else neutral
                fill = QColor(color)
                fill.setAlpha(110 if lit else 0)
                painter.setPen(QPen(color, ScaledPixels(1).px()))
                painter.setBrush(fill if lit else palette.color(QPalette.ColorRole.Base))
                painter.drawRoundedRect(QRectF(col * step + 0.5, row * step + 0.5, side - 1, side - 1), radius, radius)
        painter.end()
