"""
Where the plots of a canvas sit on its grid, and where they go when one of them moves or takes another size.

``canvas.plots[col][row]`` holds the plot whose top left cell is that one, and the plot covers ``row_span`` rows and
``col_span`` columns from there. Rows and columns count from 0 in this module.

An application can reserve slots of the grid for plots it does not draw now, as MINT does for the rows of its table
whose data could not be read: a reserved slot moves and trades places as a plot does, and no plot moves or grows over
it.

The grid can also be chosen, rows by columns, for the plots to be laid out on it, which it keeps from then on (see
laid_out).
"""

import copy
import weakref
from dataclasses import dataclass, field
from typing import Iterable, List, Optional, Tuple

from iplotlib.core.canvas import Canvas
from iplotlib.core.plot import Plot, PlotXY


@dataclass(frozen=True)
class Slot:
    """The cells a plot covers: its top left cell and how many rows and columns it spans."""
    row: int
    col: int
    row_span: int = 1
    col_span: int = 1
    # In a change that joins plots (see Arrangement.changes): the stack number that the stacks the change takes are
    # counted past. 0 everywhere else.
    stack_offset: int = 0

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
    # The slot before and after of each plot, and of each reserved slot, that moved or took another size. An
    # application that keeps the place of each plot elsewhere, as the table of MINT does, moves what it keeps there.
    # When plots are joined into one (see laid_out), their changes carry stack offsets: a change takes, from its slot
    # before, the stacks numbered past its offset that no change from the same slot with a higher offset takes, and
    # numbers them past the offset of its slot after. Undone, this gives each joined plot its stacks back.
    changes: List[Tuple[Slot, Slot]]
    # Where the reserved slots go.
    reserved: List[Slot] = field(default_factory=list)
    # The rows and columns of the grid chosen for the plots, which the grid keeps at least: None for none (see
    # Canvas.layout_rows).
    layout: Tuple[Optional[int], Optional[int]] = (None, None)


class _Reserved:
    """Takes the place of the plot that a reserved slot is kept for."""


def slots_of(canvas: Canvas) -> List[Tuple[Plot, Slot]]:
    """The plots of the canvas with their slots."""
    return [(plot, Slot(row, col, max(1, plot.row_span or 1), max(1, plot.col_span or 1)))
            for col, column in enumerate(canvas.plots or []) for row, plot in enumerate(column) if plot is not None]


def grid_size(canvas: Canvas) -> Tuple[int, int]:
    """The rows and columns of the grid: those of the canvas, and more if a plot spans beyond them."""
    slots = [slot for _, slot in slots_of(canvas)]
    return (max([canvas.rows or 1] + [slot.bottom for slot in slots]),
            max([canvas.cols or 1] + [slot.right for slot in slots]))


def current(canvas: Canvas, reserved: Iterable[Slot] = ()) -> Arrangement:
    """The arrangement the canvas has, to go back to it, with the reserved slots that take part in arrangements."""
    rows, cols = grid_size(canvas)
    return Arrangement(slots_of(canvas), rows, cols, [], [slot for _, slot in _reserved(canvas, reserved)],
                       (canvas.layout_rows, canvas.layout_cols))


def moved(canvas: Canvas, plot: Plot, row: int, col: int, grab_row: int = 0, grab_col: int = 0,
          reserved: Iterable[Slot] = ()) -> Optional[Arrangement]:
    """Where the plots go when `plot` is dropped with the cell (row, col) under the pointer, having been grabbed by
    its cell (grab_row, grab_col) from its top left one. None if nothing changes or the plot does not fit there.

    In its own columns, when no other plot covers them only in part, the plot goes between the others, which keep
    their order and close up. Elsewhere, it trades places with the plot dropped on, each taking the slot of the
    other, or it takes the empty cells it is dropped on if they leave room for it. The reserved slots move as the
    plots do."""
    slots = _occupants(canvas, reserved)
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
        return _arrangement(canvas, slots, {id(plot): slot, id(other): source})
    top = _clamp(row - grab_row, 0, rows - source.row_span)
    left = _clamp(col - grab_col, 0, cols - source.col_span)
    taken = source.moved_to(top, left)
    if any(slot.overlaps(taken) for other, slot in slots if other is not plot):
        return None
    return _arrangement(canvas, slots, {id(plot): taken})


def resized(canvas: Canvas, plot: Plot, row_span: int, col_span: int, reserved: Iterable[Slot] = ()) \
        -> Optional[Arrangement]:
    """Where the plots go when `plot` spans these rows and columns. None if nothing changes or the plot does not fit.

    In its own columns, when no other plot covers them only in part, a taller plot moves the plots below it down
    and a shorter one moves them up. Otherwise the plot grows only into empty cells of the grid. The reserved slots
    move as the plots do."""
    slots = _occupants(canvas, reserved)
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
        for other, slot in lane:
            if slot.row > source.row:
                places[id(other)] = slot.moved_to(slot.row + shift, slot.col)
        return _arrangement(canvas, slots, places)
    rows, cols = grid_size(canvas)
    if taken.bottom > rows or taken.right > cols:
        return None
    if any(slot.overlaps(taken) for other, slot in slots if other is not plot):
        return None
    return _arrangement(canvas, slots, {id(plot): taken})


def laid_out(canvas: Canvas, rows: int, cols: int, reserved: Iterable[Slot] = (), stacks: dict = None) \
        -> Optional[Arrangement]:
    """The plots of the canvas on a grid of `rows` by `cols`, which it keeps from then on, each in a cell of its own:
    they fill the columns one after the other, each from the top, in the order they have down the columns now, and
    the cells left over stay empty. When the plots outnumber the cells, the plot of the last cell and those after it
    are joined into one there, each giving its stacks below those of the one before (see _joined). None if they
    cannot be: if one of them is a reserved slot, or not a plot that can share its X axis.

    The reserved slots take cells as the plots do. `stacks` gives, by the row and the column of a plot, the highest
    stack the application keeps for it, drawn or not: the stacks of the plot joined after it are counted past that
    one, so that those it does not draw keep their own numbers."""
    occupants = sorted(_occupants(canvas, reserved), key=lambda item: (item[1].col, item[1].row))
    cells = rows * cols
    kept, joined = (occupants, []) if len(occupants) <= cells else (occupants[:cells - 1], occupants[cells - 1:])
    places = [Slot(index % rows, index // rows) for index in range(len(kept))]
    plots = [(other, place) for (other, _), place in zip(kept, places) if not isinstance(other, _Reserved)]
    changes = [(slot, place) for (_, slot), place in zip(kept, places) if place != slot]
    if joined:
        found = _joined(joined, stacks or {})
        if found is None:
            return None
        plot, offsets = found
        last = Slot(rows - 1, cols - 1)
        plots.append((plot, last))
        changes += [(slot, Slot(last.row, last.col, stack_offset=offset)) for (_, slot), offset in zip(joined, offsets)
                    if offset or slot != last]
    return Arrangement(plots, rows, cols, changes,
                       [place for (other, _), place in zip(kept, places) if isinstance(other, _Reserved)], (rows, cols))


def arrange(canvas: Canvas, arrangement: Arrangement):
    """Lay the plots of the canvas out as the arrangement says, as an application building the canvas would: each
    column lists its plots down to its last one, with None where no plot starts."""
    canvas.rows, canvas.cols = arrangement.rows, arrangement.cols
    canvas.layout_rows, canvas.layout_cols = arrangement.layout
    columns = [dict() for _ in range(arrangement.cols)]
    for plot, slot in arrangement.slots:
        columns[slot.col][slot.row] = plot
        plot.row, plot.col = slot.row + 1, slot.col + 1
        plot.row_span, plot.col_span = slot.row_span, slot.col_span
        _adopt(canvas, plot)
    canvas.plots = [[column.get(row) for row in range(max(column) + 1)] if column else [] for column in columns]


def _joined(plots: List[Tuple[object, Slot]], stacks: dict) -> Optional[Tuple[PlotXY, List[int]]]:
    """A plot with the stacks of these plots, given with their slots, those of each below those of the one before and
    below the highest stack the application keeps for it (`stacks`, see laid_out), and the number the stacks of each
    are counted past in it. It takes the X axis of the first, the rulers of all of them, and the legends dragged or
    folded away with their stacks. None unless they are all plots of curves along X of the same kind, dates or not:
    only those can share an X axis.

    The plots are left as they were, to take their stacks back: arrange makes the joined plot the parent of its
    signals and axes, and gives them back to their plots when they come back."""
    # The stacks of a plot take its Y axes in order.
    if any(type(plot) is not PlotXY or not plot.signals or len(plot.axes[1]) != len(plot.signals)
           for plot, _ in plots) or len({bool(getattr(plot.axes[0], 'is_date', False)) for plot, _ in plots}) > 1:
        return None
    first = plots[0][0]
    joined = copy.copy(first)
    joined.signals = {}
    joined.axes = [first.axes[0], []]
    joined.rulers, joined.legend_anchor, joined.legend_collapsed = [], {}, []
    offsets, top = [], 0
    for plot, slot in plots:
        offsets.append(top)
        joined.axes[1] += plot.axes[1]
        for stack, signals in plot.signals.items():
            joined.signals[top + stack] = list(signals)
        # The rulers go by their names, which those of the plots before keep.
        joined.rulers += [ruler for ruler in plot.rulers or [] if all(ruler.name != r.name for r in joined.rulers)]
        for stack, anchor in (plot.legend_anchor or {}).items():
            joined.legend_anchor[str(top + int(stack))] = list(anchor)
        joined.legend_collapsed += [str(top + int(stack)) for stack in plot.legend_collapsed or []]
        top += max([*plot.signals, stacks.get((slot.row, slot.col), 0)])
    joined.legend_anchor = joined.legend_anchor or None
    joined.legend_collapsed = joined.legend_collapsed or None
    return joined, offsets


def _adopt(canvas: Canvas, plot: Plot):
    """Make the canvas the parent of the plot and the plot that of its axes and signals: a plot joined from others,
    or one of those back from it, takes them over."""
    plot.parent = weakref.ref(canvas)
    plot.axes[0].parent = weakref.ref(plot)
    for axis in plot.axes[1]:
        axis.parent = weakref.ref(plot)
    for signals in plot.signals.values():
        for signal in signals:
            signal.parent = weakref.ref(plot)


def _reserved(canvas: Canvas, reserved: Iterable[Slot]) -> List[Tuple[_Reserved, Slot]]:
    """The reserved slots that take part in arrangements, each with what takes the place of its plot. A reserved slot
    that a plot, or a reserved slot given before it, covers in part shares cells with it already and stays out."""
    taken = [slot for _, slot in slots_of(canvas)]
    kept = []
    for slot in reserved:
        if not any(slot.overlaps(other) for other in taken):
            taken.append(slot)
            kept.append((_Reserved(), slot))
    return kept


def _occupants(canvas: Canvas, reserved: Iterable[Slot]) -> List[Tuple[object, Slot]]:
    """The plots of the canvas and the reserved slots that take part in arrangements, each with its slot."""
    return slots_of(canvas) + _reserved(canvas, reserved)


def _slot(slots: List[Tuple[object, Slot]], plot: Plot) -> Optional[Slot]:
    return next((slot for other, slot in slots if other is plot), None)


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(value, high))


def _lane(slots: List[Tuple[object, Slot]], source: Slot) -> Optional[List[Tuple[object, Slot]]]:
    """The plots and reserved slots in the columns of the slot, from the top, if each covers exactly those columns."""
    lane = [(other, slot) for other, slot in slots if slot.col < source.right and source.col < slot.right]
    if any(slot.col != source.col or slot.col_span != source.col_span for _, slot in lane):
        return None
    return sorted(lane, key=lambda item: item[1].row)


def _reordered(canvas: Canvas, slots: List[Tuple[object, Slot]], lane: List[Tuple[object, Slot]], plot: Plot,
               row: int, rows: int) -> Optional[Arrangement]:
    col, col_span = lane[0][1].col, lane[0][1].col_span
    # The lane as blocks of rows down to the bottom of the grid: a plot or a reserved slot, or a row with neither.
    blocks = []  # type: List[Tuple[Optional[object], Slot]]
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
    places = {}
    top = 0
    for other, slot in blocks:
        if other is not None and slot.row != top:
            places[id(other)] = slot.moved_to(top, slot.col)
        top += slot.row_span
    return _arrangement(canvas, slots, places)


def _arrangement(canvas: Canvas, slots: List[Tuple[object, Slot]], places: dict) -> Arrangement:
    """The arrangement with the plots and reserved slots in `places` (by id) moved there, the others where they are."""
    rows, cols = grid_size(canvas)
    new_slots = [(other, places.get(id(other), slot)) for other, slot in slots]
    changes = [(slot, places[id(other)]) for other, slot in slots if id(other) in places]
    drawn = [slot for other, slot in slots if not isinstance(other, _Reserved)]
    plots = [(other, slot) for other, slot in new_slots if not isinstance(other, _Reserved)]
    # A grid that ends with its plots, as an application builds it from where they are, still does; one that keeps
    # room beyond them keeps that size at least, as one chosen for them does. Reserved slots take no room: nothing is
    # drawn there.
    new_rows = max([slot.bottom for _, slot in plots] + [canvas.layout_rows or 0])
    if rows > max(slot.bottom for slot in drawn):
        new_rows = max(new_rows, rows)
    new_cols = max([slot.right for _, slot in plots] + [canvas.layout_cols or 0])
    if cols > max(slot.right for slot in drawn):
        new_cols = max(new_cols, cols)
    return Arrangement(plots, new_rows, new_cols, changes,
                       [slot for other, slot in new_slots if isinstance(other, _Reserved)],
                       (canvas.layout_rows, canvas.layout_cols))
