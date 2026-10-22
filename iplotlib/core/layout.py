"""
Where the plots of a canvas sit on its grid, and where they go when one of them moves or takes another size.

``canvas.plots[col][row]`` holds the plot whose top left cell is that one, and the plot covers ``row_span`` rows and
``col_span`` columns from there. Rows and columns count from 0 in this module.
"""

from dataclasses import dataclass
from typing import List, Optional, Tuple

from iplotlib.core.canvas import Canvas
from iplotlib.core.plot import Plot


@dataclass(frozen=True)
class Slot:
    """The cells a plot covers: its top left cell and how many rows and columns it spans."""
    row: int
    col: int
    row_span: int = 1
    col_span: int = 1

    @property
    def bottom(self) -> int:
        """The row below the slot."""
        return self.row + self.row_span

    @property
    def right(self) -> int:
        """The column right of the slot."""
        return self.col + self.col_span

    def contains(self, row: int, col: int) -> bool:
        return self.row <= row < self.bottom and self.col <= col < self.right

    def overlaps(self, other: 'Slot') -> bool:
        return self.row < other.bottom and other.row < self.bottom and self.col < other.right and other.col < self.right

    def moved_to(self, row: int, col: int) -> 'Slot':
        return Slot(row, col, self.row_span, self.col_span)


@dataclass
class Arrangement:
    """Where the plots of a canvas go, and the size the grid takes for them."""
    slots: List[Tuple[Plot, Slot]]
    rows: int
    cols: int
    # The slot before and after of each plot that moved or took another size, and of each empty cell that moved
    # with them. An application that keeps the place of each plot elsewhere, as the table of MINT does, moves what
    # it keeps for a cell, a plot or nothing drawn, to the cell that took its place.
    changes: List[Tuple[Slot, Slot]]


def slots_of(canvas: Canvas) -> List[Tuple[Plot, Slot]]:
    """The plots of the canvas with their slots."""
    return [(plot, Slot(row, col, max(1, plot.row_span or 1), max(1, plot.col_span or 1)))
            for col, column in enumerate(canvas.plots or []) for row, plot in enumerate(column) if plot is not None]


def grid_size(canvas: Canvas) -> Tuple[int, int]:
    """The rows and columns of the grid: those of the canvas, and more if a plot spans beyond them."""
    slots = [slot for _, slot in slots_of(canvas)]
    return (max([canvas.rows or 1] + [slot.bottom for slot in slots]),
            max([canvas.cols or 1] + [slot.right for slot in slots]))


def current(canvas: Canvas) -> Arrangement:
    """The arrangement the canvas has, to go back to it."""
    rows, cols = grid_size(canvas)
    return Arrangement(slots_of(canvas), rows, cols, [])


def moved(canvas: Canvas, plot: Plot, row: int, col: int, grab_row: int = 0, grab_col: int = 0) \
        -> Optional[Arrangement]:
    """Where the plots go when `plot` is dropped with the cell (row, col) under the pointer, having been grabbed by
    its cell (grab_row, grab_col) from its top left one. None if nothing changes or the plot does not fit there.

    In its own columns, when no other plot covers them only in part, the plot goes between the others, which keep
    their order and close up. Elsewhere, it trades places with the plot dropped on, each taking the slot of the
    other, or it takes the empty cells it is dropped on if they leave room for it."""
    slots = slots_of(canvas)
    source = _slot(slots, plot)
    rows, cols = grid_size(canvas)
    row, col = _clamp(row, 0, rows - 1), _clamp(col, 0, cols - 1)
    if source is None or source.contains(row, col):
        return None
    lane = _lane(slots, source)
    if lane is not None and source.col <= col < source.right:
        return _reordered(canvas, slots, lane, plot, row, rows)
    target = next(((other, slot) for other, slot in slots if slot.contains(row, col)), None)
    if target is not None:
        other, slot = target
        return _arrangement(canvas, slots, {id(plot): slot, id(other): source}, [])
    top = _clamp(row - grab_row, 0, rows - source.row_span)
    left = _clamp(col - grab_col, 0, cols - source.col_span)
    taken = source.moved_to(top, left)
    if any(slot.overlaps(taken) for other, slot in slots if other is not plot):
        return None
    # A cell drawn empty can still hold what the application keeps for it: it goes where the plot was.
    return _arrangement(canvas, slots, {id(plot): taken}, [(Slot(top, left), Slot(source.row, source.col))])


def resized(canvas: Canvas, plot: Plot, row_span: int, col_span: int) -> Optional[Arrangement]:
    """Where the plots go when `plot` spans these rows and columns. None if nothing changes or the plot does not fit.

    In its own columns, when no other plot covers them only in part, a taller plot moves the plots below it down
    and a shorter one moves them up. Otherwise the plot grows only into empty cells of the grid."""
    slots = slots_of(canvas)
    source = _slot(slots, plot)
    if source is None:
        return None
    taken = Slot(source.row, source.col, max(1, row_span), max(1, col_span))
    if taken == source:
        return None
    lane = _lane(slots, source) if taken.col_span == source.col_span else None
    if lane is not None:
        shift = taken.row_span - source.row_span
        places = {id(plot): taken}
        changes = []
        for other, slot in lane:
            if slot.row > source.row:
                places[id(other)] = slot.moved_to(slot.row + shift, slot.col)
        # The empty cells between the plots below move with them.
        occupied = {row for _, slot in lane for row in range(slot.row, slot.bottom)}
        lane_bottom = max(slot.bottom for _, slot in lane)
        for row in range(source.bottom, lane_bottom):
            if row not in occupied:
                changes += [(Slot(row, col), Slot(row + shift, col)) for col in range(source.col, source.right)]
        return _arrangement(canvas, slots, places, changes)
    rows, cols = grid_size(canvas)
    if taken.bottom > rows or taken.right > cols:
        return None
    if any(slot.overlaps(taken) for other, slot in slots if other is not plot):
        return None
    return _arrangement(canvas, slots, {id(plot): taken}, [])


def arrange(canvas: Canvas, arrangement: Arrangement):
    """Lay the plots of the canvas out as the arrangement says, as an application building the canvas would: each
    column lists its plots down to its last one, with None where no plot starts."""
    canvas.rows, canvas.cols = arrangement.rows, arrangement.cols
    columns = [dict() for _ in range(arrangement.cols)]
    for plot, slot in arrangement.slots:
        columns[slot.col][slot.row] = plot
        plot.row, plot.col = slot.row + 1, slot.col + 1
        plot.row_span, plot.col_span = slot.row_span, slot.col_span
    canvas.plots = [[column.get(row) for row in range(max(column) + 1)] if column else [] for column in columns]


def _slot(slots: List[Tuple[Plot, Slot]], plot: Plot) -> Optional[Slot]:
    return next((slot for other, slot in slots if other is plot), None)


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(value, high))


def _lane(slots: List[Tuple[Plot, Slot]], source: Slot) -> Optional[List[Tuple[Plot, Slot]]]:
    """The plots in the columns of the slot, from the top, if each of them covers exactly those columns."""
    lane = [(plot, slot) for plot, slot in slots if slot.col < source.right and source.col < slot.right]
    if any(slot.col != source.col or slot.col_span != source.col_span for _, slot in lane):
        return None
    return sorted(lane, key=lambda item: item[1].row)


def _reordered(canvas: Canvas, slots: List[Tuple[Plot, Slot]], lane: List[Tuple[Plot, Slot]], plot: Plot,
               row: int, rows: int) -> Optional[Arrangement]:
    col, col_span = lane[0][1].col, lane[0][1].col_span
    # The lane as blocks of rows down to the bottom of the grid: a plot, or a row with no plot.
    blocks = []  # type: List[Tuple[Optional[Plot], Slot]]
    top = 0
    for other, slot in lane:
        blocks += [(None, Slot(empty, col, 1, col_span)) for empty in range(top, slot.row)]
        blocks.append((other, slot))
        top = slot.bottom
    blocks += [(None, Slot(empty, col, 1, col_span)) for empty in range(top, rows)]
    index = next(i for i, (other, _) in enumerate(blocks) if other is plot)
    target = next((i for i, (_, slot) in enumerate(blocks) if slot.row <= row < slot.bottom), len(blocks) - 1)
    if target == index:
        return None
    blocks.insert(target, blocks.pop(index))
    places, changes = {}, []
    top = 0
    for other, slot in blocks:
        if slot.row != top:
            if other is not None:
                places[id(other)] = slot.moved_to(top, slot.col)
            else:
                changes += [(Slot(slot.row, col), Slot(top, col)) for col in range(slot.col, slot.right)]
        top += slot.row_span
    return _arrangement(canvas, slots, places, changes)


def _arrangement(canvas: Canvas, slots: List[Tuple[Plot, Slot]], places: dict,
                 empty_changes: List[Tuple[Slot, Slot]]) -> Arrangement:
    """The arrangement with the plots in `places` (by id) moved there, the others where they are."""
    rows, cols = grid_size(canvas)
    new_slots = [(plot, places.get(id(plot), slot)) for plot, slot in slots]
    changes = [(slot, places[id(plot)]) for plot, slot in slots if id(plot) in places]
    # A grid that ends with its plots, as an application builds it from where they are, still does; one that keeps
    # room beyond them keeps that size at least.
    new_rows = max(slot.bottom for _, slot in new_slots)
    if rows > max(slot.bottom for _, slot in slots):
        new_rows = max(new_rows, rows)
    new_cols = max(slot.right for _, slot in new_slots)
    if cols > max(slot.right for _, slot in slots):
        new_cols = max(new_cols, cols)
    return Arrangement(new_slots, new_rows, new_cols, changes + empty_changes)
