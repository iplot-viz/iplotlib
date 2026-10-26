"""Unit tests for the arrangement of the plots on the grid of a canvas (moving and resizing plots, laying them out on a
grid picked for them)."""

import unittest

from iplotlib.core.axis import LinearAxis
from iplotlib.core.canvas import Canvas
from iplotlib.core.layout import Arrangement, Slot, arrange, current, grid_size, laid_out, moved, resized, slots_of
from iplotlib.core.plot import PlotXY, PlotXYWithSlider
from iplotlib.core.ruler import Ruler
from iplotlib.core.signal import SignalXY


def _canvas(places: dict, rows: int = None, cols: int = None) -> Canvas:
    """A canvas built as MINT builds one: each column lists its plots down to its last one, with None where no plot
    starts. `places` gives (row, col, row_span, col_span) by plot title, counting from 0."""
    rows = rows or max(row + row_span for row, _, row_span, _ in places.values())
    cols = cols or max(col + col_span for _, col, _, col_span in places.values())
    canvas = Canvas(rows=rows, cols=cols)
    columns = [dict() for _ in range(cols)]
    for title, (row, col, row_span, col_span) in places.items():
        columns[col][row] = PlotXY(plot_title=title, row=row + 1, col=col + 1, row_span=row_span, col_span=col_span)
    canvas.plots = [[column.get(row) for row in range(max(column) + 1)] if column else [] for column in columns]
    return canvas


def _plot(canvas: Canvas, title: str):
    return next(plot for plot, _ in slots_of(canvas) if plot.plot_title == title)


def _places(arrangement: Arrangement) -> dict:
    return {plot.plot_title: (slot.row, slot.col, slot.row_span, slot.col_span) for plot, slot in arrangement.slots}


def _changes(arrangement: Arrangement) -> set:
    return {((before.row, before.col), (after.row, after.col)) for before, after in arrangement.changes}


COLUMN = {'A': (0, 0, 1, 1), 'B': (1, 0, 1, 1), 'C': (2, 0, 1, 1), 'D': (3, 0, 1, 1)}


class TestReadTheGrid(unittest.TestCase):

    def test_the_slots_and_the_grid_of_a_canvas(self):
        canvas = _canvas({'A': (0, 0, 2, 1), 'B': (0, 1, 1, 1), 'C': (1, 1, 1, 1)})

        self.assertEqual(_places(current(canvas)), {'A': (0, 0, 2, 1), 'B': (0, 1, 1, 1), 'C': (1, 1, 1, 1)})
        self.assertEqual(grid_size(canvas), (2, 2))

    def test_the_grid_covers_a_plot_that_spans_beyond_the_rows_of_the_canvas(self):
        canvas = _canvas({'A': (0, 0, 3, 1)}, rows=1)

        self.assertEqual(grid_size(canvas), (3, 1))


class TestMoveInItsColumn(unittest.TestCase):

    def test_a_plot_moved_up_goes_before_the_plot_dropped_on_and_the_others_keep_their_order(self):
        canvas = _canvas(COLUMN)

        arrangement = moved(canvas, _plot(canvas, 'D'), 0, 0)

        self.assertEqual(_places(arrangement), {'D': (0, 0, 1, 1), 'A': (1, 0, 1, 1), 'B': (2, 0, 1, 1),
                                                'C': (3, 0, 1, 1)})
        self.assertEqual((arrangement.rows, arrangement.cols), (4, 1))

    def test_a_plot_moved_down_goes_after_the_plot_dropped_on(self):
        canvas = _canvas(COLUMN)

        arrangement = moved(canvas, _plot(canvas, 'A'), 2, 0)

        self.assertEqual(_places(arrangement), {'B': (0, 0, 1, 1), 'C': (1, 0, 1, 1), 'A': (2, 0, 1, 1),
                                                'D': (3, 0, 1, 1)})
        self.assertEqual(_changes(arrangement), {((0, 0), (2, 0)), ((1, 0), (0, 0)), ((2, 0), (1, 0))})

    def test_a_plot_dropped_on_itself_changes_nothing(self):
        canvas = _canvas({'A': (0, 0, 2, 1), 'B': (2, 0, 1, 1)})

        self.assertIsNone(moved(canvas, _plot(canvas, 'A'), 1, 0))

    def test_the_plots_keep_their_heights(self):
        canvas = _canvas({'A': (0, 0, 1, 1), 'P': (1, 0, 2, 1), 'B': (3, 0, 1, 1)})

        arrangement = moved(canvas, _plot(canvas, 'P'), 0, 0)

        self.assertEqual(_places(arrangement), {'P': (0, 0, 2, 1), 'A': (2, 0, 1, 1), 'B': (3, 0, 1, 1)})

    def test_a_row_with_no_plot_moves_as_the_plots_do(self):
        canvas = _canvas({'A': (0, 0, 1, 1), 'B': (2, 0, 1, 1)})

        arrangement = moved(canvas, _plot(canvas, 'B'), 1, 0)

        self.assertEqual(_places(arrangement), {'A': (0, 0, 1, 1), 'B': (1, 0, 1, 1)})
        self.assertEqual(_changes(arrangement), {((2, 0), (1, 0))})

    def test_a_plot_dropped_on_an_empty_row_of_its_column_lands_there(self):
        canvas = _canvas({'A': (0, 0, 1, 1), 'B': (1, 0, 1, 1), 'C': (0, 1, 1, 1), 'D': (1, 1, 1, 1),
                          'E': (2, 1, 1, 1)})

        arrangement = moved(canvas, _plot(canvas, 'A'), 2, 0)

        self.assertEqual(_places(arrangement)['A'], (2, 0, 1, 1))
        self.assertEqual(_places(arrangement)['B'], (0, 0, 1, 1))
        self.assertEqual(_changes(arrangement), {((0, 0), (2, 0)), ((1, 0), (0, 0))})
        self.assertEqual((arrangement.rows, arrangement.cols), (3, 2))

    def test_the_only_plot_of_a_column_moves_down_its_column(self):
        canvas = _canvas({'A': (0, 0, 1, 1), 'B': (0, 1, 2, 1)})

        arrangement = moved(canvas, _plot(canvas, 'A'), 1, 0)

        self.assertEqual(_places(arrangement), {'A': (1, 0, 1, 1), 'B': (0, 1, 2, 1)})

    def test_plots_spanning_the_same_columns_reorder_together(self):
        canvas = _canvas({'A': (0, 0, 1, 2), 'B': (1, 0, 1, 2)})

        arrangement = moved(canvas, _plot(canvas, 'B'), 0, 1)

        self.assertEqual(_places(arrangement), {'B': (0, 0, 1, 2), 'A': (1, 0, 1, 2)})


class TestMoveElsewhere(unittest.TestCase):

    def test_a_plot_dropped_on_a_plot_of_another_column_trades_places_with_it(self):
        canvas = _canvas({'A': (0, 0, 1, 1), 'B': (1, 0, 1, 1), 'C': (0, 1, 1, 1), 'D': (1, 1, 1, 1)})

        arrangement = moved(canvas, _plot(canvas, 'A'), 1, 1)

        self.assertEqual(_places(arrangement), {'A': (1, 1, 1, 1), 'B': (1, 0, 1, 1), 'C': (0, 1, 1, 1),
                                                'D': (0, 0, 1, 1)})
        self.assertEqual(_changes(arrangement), {((0, 0), (1, 1)), ((1, 1), (0, 0))})

    def test_plots_that_trade_places_take_the_size_of_each_other(self):
        canvas = _canvas({'A': (0, 0, 2, 1), 'C': (0, 1, 1, 1), 'D': (1, 1, 1, 1)})

        arrangement = moved(canvas, _plot(canvas, 'A'), 0, 1)

        self.assertEqual(_places(arrangement), {'A': (0, 1, 1, 1), 'C': (0, 0, 2, 1), 'D': (1, 1, 1, 1)})
        self.assertEqual((arrangement.rows, arrangement.cols), (2, 2))

    def test_a_plot_dropped_on_empty_cells_takes_them(self):
        canvas = _canvas({'A': (0, 0, 1, 1), 'B': (1, 0, 1, 1), 'C': (0, 1, 1, 1)})

        arrangement = moved(canvas, _plot(canvas, 'A'), 1, 1)

        self.assertEqual(_places(arrangement), {'A': (1, 1, 1, 1), 'B': (1, 0, 1, 1), 'C': (0, 1, 1, 1)})
        self.assertEqual(_changes(arrangement), {((0, 0), (1, 1))})

    def test_a_plot_lands_where_it_was_grabbed(self):
        canvas = _canvas({'A': (0, 0, 2, 1), 'B': (2, 0, 1, 1)}, cols=2)

        arrangement = moved(canvas, _plot(canvas, 'A'), 2, 1, grab_row=1)

        self.assertEqual(_places(arrangement)['A'], (1, 1, 2, 1))

    def test_a_plot_that_does_not_fit_in_the_empty_cells_stays(self):
        canvas = _canvas({'A': (0, 0, 2, 1), 'C': (0, 1, 1, 1), 'D': (2, 1, 1, 1)}, rows=3)

        self.assertIsNone(moved(canvas, _plot(canvas, 'A'), 1, 1))

    def test_a_column_that_a_plot_covers_in_part_takes_no_reordering(self):
        canvas = _canvas({'A': (0, 0, 1, 2), 'B': (1, 0, 1, 1), 'C': (1, 1, 1, 1)})

        arrangement = moved(canvas, _plot(canvas, 'B'), 0, 0)

        self.assertEqual(_places(arrangement), {'A': (1, 0, 1, 1), 'B': (0, 0, 1, 2), 'C': (1, 1, 1, 1)})

    def test_the_grid_keeps_the_rows_it_has_beyond_its_plots(self):
        canvas = _canvas({'A': (0, 0, 1, 1), 'B': (1, 0, 1, 1)}, rows=4)

        arrangement = moved(canvas, _plot(canvas, 'A'), 1, 0)

        self.assertEqual((arrangement.rows, arrangement.cols), (4, 1))


class TestResize(unittest.TestCase):

    def test_a_taller_plot_moves_the_plots_below_it_down(self):
        canvas = _canvas({'A': (0, 0, 1, 1), 'B': (1, 0, 1, 1), 'C': (2, 0, 1, 1)})

        arrangement = resized(canvas, _plot(canvas, 'B'), 2, 1)

        self.assertEqual(_places(arrangement), {'A': (0, 0, 1, 1), 'B': (1, 0, 2, 1), 'C': (3, 0, 1, 1)})
        self.assertEqual((arrangement.rows, arrangement.cols), (4, 1))

    def test_a_shorter_plot_moves_the_plots_below_it_up(self):
        canvas = _canvas({'A': (0, 0, 1, 1), 'B': (1, 0, 2, 1), 'C': (3, 0, 1, 1)})

        arrangement = resized(canvas, _plot(canvas, 'B'), 1, 1)

        self.assertEqual(_places(arrangement), {'A': (0, 0, 1, 1), 'B': (1, 0, 1, 1), 'C': (2, 0, 1, 1)})
        self.assertEqual((arrangement.rows, arrangement.cols), (3, 1))

    def test_rows_with_no_plot_below_move_with_the_plots(self):
        canvas = _canvas({'A': (0, 0, 1, 1), 'C': (2, 0, 1, 1)})

        arrangement = resized(canvas, _plot(canvas, 'A'), 2, 1)

        self.assertEqual(_places(arrangement), {'A': (0, 0, 2, 1), 'C': (3, 0, 1, 1)})
        self.assertEqual(_changes(arrangement), {((0, 0), (0, 0)), ((2, 0), (3, 0))})

    def test_a_taller_last_plot_takes_the_rows_left_below_its_column(self):
        canvas = _canvas({'A': (0, 0, 1, 1), 'B': (1, 0, 1, 1), 'C': (0, 1, 1, 1), 'D': (1, 1, 1, 1),
                          'E': (2, 1, 1, 1)})

        arrangement = resized(canvas, _plot(canvas, 'B'), 2, 1)

        self.assertEqual(_places(arrangement)['B'], (1, 0, 2, 1))
        self.assertEqual((arrangement.rows, arrangement.cols), (3, 2))

    def test_a_wider_plot_takes_only_empty_cells(self):
        canvas = _canvas({'A': (0, 0, 1, 1), 'B': (1, 0, 1, 1), 'C': (0, 1, 1, 1)})

        self.assertIsNone(resized(canvas, _plot(canvas, 'A'), 1, 2))
        self.assertEqual(_places(resized(canvas, _plot(canvas, 'B'), 1, 2))['B'], (1, 0, 1, 2))

    def test_a_plot_does_not_grow_beyond_the_grid_where_it_moves_no_plots(self):
        canvas = _canvas({'A': (0, 0, 1, 1), 'B': (1, 0, 1, 1), 'C': (0, 1, 1, 1)})

        self.assertIsNone(resized(canvas, _plot(canvas, 'B'), 1, 3))

    def test_the_same_size_changes_nothing(self):
        canvas = _canvas(COLUMN)

        self.assertIsNone(resized(canvas, _plot(canvas, 'B'), 1, 1))


class TestReservedSlots(unittest.TestCase):
    """Slots an application reserves for plots it does not draw now, such as those whose data could not be read."""

    def test_a_reserved_slot_in_the_column_of_a_plot_moves_as_a_plot_does(self):
        canvas = _canvas({'A': (0, 0, 1, 1), 'B': (3, 0, 1, 1)})

        arrangement = moved(canvas, _plot(canvas, 'B'), 0, 0, reserved=[Slot(1, 0, 2, 1)])

        self.assertEqual(_places(arrangement), {'B': (0, 0, 1, 1), 'A': (1, 0, 1, 1)})
        self.assertEqual(arrangement.reserved, [Slot(2, 0, 2, 1)])
        self.assertEqual(_changes(arrangement), {((3, 0), (0, 0)), ((0, 0), (1, 0)), ((1, 0), (2, 0))})
        # Nothing is drawn in a reserved slot: the grid ends with the plots.
        self.assertEqual((arrangement.rows, arrangement.cols), (2, 1))

    def test_a_plot_dropped_on_a_reserved_slot_trades_places_with_it(self):
        canvas = _canvas({'A': (0, 0, 2, 1), 'C': (0, 1, 1, 1)})

        arrangement = moved(canvas, _plot(canvas, 'A'), 1, 1, reserved=[Slot(1, 1)])

        self.assertEqual(_places(arrangement), {'A': (1, 1, 1, 1), 'C': (0, 1, 1, 1)})
        self.assertEqual(arrangement.reserved, [Slot(0, 0, 2, 1)])
        self.assertEqual(_changes(arrangement), {((0, 0), (1, 1)), ((1, 1), (0, 0))})

    def test_a_plot_does_not_move_over_a_reserved_slot(self):
        canvas = _canvas({'A': (0, 0, 2, 1), 'C': (0, 1, 1, 1), 'D': (2, 0, 1, 1)})

        self.assertEqual(_places(moved(canvas, _plot(canvas, 'A'), 1, 1))['A'], (1, 1, 2, 1))
        self.assertIsNone(moved(canvas, _plot(canvas, 'A'), 1, 1, reserved=[Slot(2, 1)]))

    def test_a_plot_does_not_grow_over_a_reserved_slot(self):
        canvas = _canvas({'A': (0, 0, 1, 1), 'C': (0, 1, 1, 1), 'W': (2, 0, 1, 2)})

        self.assertEqual(_places(resized(canvas, _plot(canvas, 'C'), 2, 1))['C'], (0, 1, 2, 1))
        self.assertIsNone(resized(canvas, _plot(canvas, 'C'), 2, 1, reserved=[Slot(1, 1)]))

    def test_a_taller_plot_moves_a_reserved_slot_below_it_down(self):
        canvas = _canvas({'A': (0, 0, 1, 1), 'C': (2, 0, 1, 1)})

        arrangement = resized(canvas, _plot(canvas, 'A'), 2, 1, reserved=[Slot(1, 0)])

        self.assertEqual(_places(arrangement), {'A': (0, 0, 2, 1), 'C': (3, 0, 1, 1)})
        self.assertEqual(arrangement.reserved, [Slot(2, 0)])
        self.assertEqual(_changes(arrangement), {((0, 0), (0, 0)), ((1, 0), (2, 0)), ((2, 0), (3, 0))})

    def test_a_reserved_slot_left_where_it_is_takes_no_room(self):
        canvas = _canvas({'A': (0, 0, 1, 1), 'B': (1, 0, 1, 1)})

        arrangement = moved(canvas, _plot(canvas, 'B'), 0, 0, reserved=[Slot(2, 0)])

        self.assertEqual(_places(arrangement), {'B': (0, 0, 1, 1), 'A': (1, 0, 1, 1)})
        self.assertEqual(arrangement.reserved, [Slot(2, 0)])
        self.assertEqual(_changes(arrangement), {((1, 0), (0, 0)), ((0, 0), (1, 0))})
        self.assertEqual((arrangement.rows, arrangement.cols), (2, 1))

    def test_a_reserved_slot_that_shares_cells_with_a_plot_or_another_reserved_slot_stays_out(self):
        canvas = _canvas({'A': (0, 0, 2, 1), 'B': (2, 0, 1, 1)})

        kept = current(canvas, reserved=[Slot(1, 0), Slot(3, 0, 2, 1), Slot(4, 0)]).reserved

        self.assertEqual(kept, [Slot(3, 0, 2, 1)])


class TestArrange(unittest.TestCase):

    def test_the_canvas_takes_the_arrangement_as_an_application_would_build_it(self):
        canvas = _canvas({'A': (0, 0, 1, 1), 'B': (1, 0, 1, 1), 'C': (0, 1, 1, 1)})
        a, b, c = (_plot(canvas, title) for title in 'ABC')

        arrange(canvas, moved(canvas, a, 1, 1))

        self.assertEqual(canvas.plots, [[None, b], [c, a]])
        self.assertEqual((canvas.rows, canvas.cols), (2, 2))
        self.assertEqual((a.row, a.col, a.row_span, a.col_span), (2, 2, 1, 1))

    def test_a_column_with_no_plot_left_is_empty(self):
        canvas = _canvas({'A': (0, 0, 1, 1), 'B': (0, 1, 1, 1)}, rows=2)
        a, b = _plot(canvas, 'A'), _plot(canvas, 'B')

        arrange(canvas, moved(canvas, a, 1, 1))

        self.assertEqual(canvas.plots, [[], [b, a]])
        self.assertEqual((canvas.rows, canvas.cols), (2, 2))

    def test_plots_that_trade_places_take_the_spans_of_each_other(self):
        canvas = _canvas({'A': (0, 0, 1, 1), 'B': (0, 1, 2, 1)})
        a, b = _plot(canvas, 'A'), _plot(canvas, 'B')

        arrange(canvas, moved(canvas, b, 0, 0))

        self.assertEqual(canvas.plots, [[b], [a]])
        self.assertEqual((b.row, b.col, b.row_span, b.col_span), (1, 1, 1, 1))
        self.assertEqual((a.row, a.col, a.row_span, a.col_span), (1, 2, 2, 1))

    def test_going_back_restores_the_canvas(self):
        canvas = _canvas(COLUMN)
        before = current(canvas)
        plots = [list(column) for column in canvas.plots]

        arrange(canvas, resized(canvas, _plot(canvas, 'B'), 3, 1))
        arrange(canvas, before)

        self.assertEqual(canvas.plots, plots)
        self.assertEqual((canvas.rows, canvas.cols), (4, 1))
        self.assertEqual([(plot.row, plot.row_span) for plot in plots[0]], [(1, 1), (2, 1), (3, 1), (4, 1)])


def _stacked(canvas: Canvas, stacks: dict = None) -> Canvas:
    """The canvas with a signal in each stack of each plot, and a Y axis for each stack: one stack, or as many as
    `stacks` gives by plot title."""
    for plot, _ in slots_of(canvas):
        count = (stacks or {}).get(plot.plot_title, 1)
        plot.axes = [LinearAxis(), [LinearAxis() for _ in range(count)]]
        for stack in range(1, count + 1):
            plot.add_signal(SignalXY(label=f'{plot.plot_title}{stack}'), stack=stack)
    return canvas


def _offsets(arrangement: Arrangement) -> set:
    return {((before.row, before.col, before.stack_offset), (after.row, after.col, after.stack_offset))
            for before, after in arrangement.changes}


class TestLayOut(unittest.TestCase):

    def test_the_plots_fill_the_columns_one_after_the_other(self):
        canvas = _canvas(COLUMN)

        arrangement = laid_out(canvas, 2, 2)

        self.assertEqual(_places(arrangement), {'A': (0, 0, 1, 1), 'B': (1, 0, 1, 1), 'C': (0, 1, 1, 1),
                                                'D': (1, 1, 1, 1)})
        self.assertEqual((arrangement.rows, arrangement.cols, arrangement.layout), (2, 2, (2, 2)))
        self.assertEqual(_changes(arrangement), {((2, 0), (0, 1)), ((3, 0), (1, 1))})

    def test_the_plots_keep_the_order_they_have_down_the_columns_and_lose_their_spans(self):
        canvas = _canvas({'A': (0, 1, 1, 1), 'B': (0, 0, 2, 1), 'C': (2, 0, 1, 1)})

        arrangement = laid_out(canvas, 3, 1)

        self.assertEqual(_places(arrangement), {'B': (0, 0, 1, 1), 'C': (1, 0, 1, 1), 'A': (2, 0, 1, 1)})

    def test_the_cells_left_over_stay_and_the_canvas_keeps_the_grid(self):
        canvas = _canvas({'A': (0, 0, 1, 1), 'B': (1, 0, 1, 1)})

        arrange(canvas, laid_out(canvas, 3, 2))

        self.assertEqual(_titles(canvas), [['A', 'B'], []])
        self.assertEqual((canvas.rows, canvas.cols, canvas.layout_rows, canvas.layout_cols), (3, 2, 3, 2))

    def test_a_grid_picked_for_the_plots_keeps_its_columns_when_a_plot_leaves_the_last_one(self):
        canvas = _canvas({'A': (0, 0, 1, 1), 'B': (0, 2, 1, 1)}, rows=2, cols=3)
        canvas.layout_rows, canvas.layout_cols = 2, 3

        arrangement = moved(canvas, _plot(canvas, 'B'), 1, 0)

        self.assertEqual(_places(arrangement), {'A': (0, 0, 1, 1), 'B': (1, 0, 1, 1)})
        self.assertEqual((arrangement.rows, arrangement.cols, arrangement.layout), (2, 3, (2, 3)))

    def test_the_plots_beyond_the_last_cell_join_its_plot_as_stacks_below_its_own(self):
        canvas = _stacked(_canvas(COLUMN), {'B': 2})
        b = _plot(canvas, 'B')

        arrangement = laid_out(canvas, 1, 2)

        joined = next(plot for plot, slot in arrangement.slots if slot == Slot(0, 1))
        self.assertEqual(_places(arrangement), {'A': (0, 0, 1, 1), 'B': (0, 1, 1, 1)})
        self.assertEqual({stack: [signal.label for signal in signals] for stack, signals in joined.signals.items()},
                         {1: ['B1'], 2: ['B2'], 3: ['C1'], 4: ['D1']})
        self.assertEqual(len(joined.axes[1]), 4)
        self.assertIs(joined.axes[0], b.axes[0])
        self.assertEqual(_offsets(arrangement), {((1, 0, 0), (0, 1, 0)), ((2, 0, 0), (0, 1, 2)),
                                                 ((3, 0, 0), (0, 1, 3))})
        # The plots joined are left as they were.
        self.assertEqual(sorted(b.signals), [1, 2])
        self.assertTrue(all(signal.parent() is b for signals in b.signals.values() for signal in signals))

    def test_the_joined_plot_takes_the_signals_and_going_back_gives_them_back(self):
        canvas = _stacked(_canvas(COLUMN))
        before = current(canvas)
        plots = [plot for plot, _ in slots_of(canvas)]

        arrange(canvas, laid_out(canvas, 1, 2))
        joined = canvas.plots[1][0]
        self.assertTrue(all(signal.parent() is joined for signals in joined.signals.values() for signal in signals))
        self.assertTrue(all(axis.parent() is joined for axis in joined.axes[1]))

        arrange(canvas, before)
        self.assertEqual(_titles(canvas), [['A', 'B', 'C', 'D']])
        for plot in plots:
            self.assertTrue(all(signal.parent() is plot for signals in plot.signals.values() for signal in signals))
            self.assertTrue(all(axis.parent() is plot for axis in [plot.axes[0]] + plot.axes[1]))
        self.assertEqual((canvas.layout_rows, canvas.layout_cols), (None, None))

    def test_the_stacks_the_application_keeps_for_a_plot_but_does_not_draw_keep_their_numbers(self):
        canvas = _stacked(_canvas(COLUMN))

        # The application keeps three stacks for B, which draws its first one only.
        arrangement = laid_out(canvas, 1, 2, stacks={(1, 0): 3, (2, 0): 1})

        joined = next(plot for plot, slot in arrangement.slots if slot == Slot(0, 1))
        self.assertEqual({stack: [signal.label for signal in signals] for stack, signals in joined.signals.items()},
                         {1: ['B1'], 4: ['C1'], 5: ['D1']})
        self.assertEqual(_offsets(arrangement), {((1, 0, 0), (0, 1, 0)), ((2, 0, 0), (0, 1, 3)),
                                                 ((3, 0, 0), (0, 1, 4))})

    def test_the_joined_plot_takes_the_rulers_and_the_legends_moved_of_each_plot_with_its_stacks(self):
        canvas = _stacked(_canvas(COLUMN), {'B': 2})
        b, c = _plot(canvas, 'B'), _plot(canvas, 'C')
        b.add_ruler(Ruler(name='A', xy=(1.0, 0.0)))
        c.add_ruler(Ruler(name='A', xy=(2.0, 0.0)))
        c.add_ruler(Ruler(name='B', xy=(3.0, 0.0)))
        b.legend_anchor, c.legend_anchor = {'2': [0.1, 0.2]}, {'1': [0.3, 0.4]}
        c.legend_collapsed = ['1']

        joined = next(plot for plot, slot in laid_out(canvas, 1, 2).slots if slot == Slot(0, 1))

        self.assertEqual([(ruler.name, ruler.xy[0]) for ruler in joined.rulers], [('A', 1.0), ('B', 3.0)])
        self.assertEqual(joined.legend_anchor, {'2': [0.1, 0.2], '3': [0.3, 0.4]})
        self.assertEqual(joined.legend_collapsed, ['3'])
        # The plots joined are left as they were.
        self.assertEqual((c.legend_anchor, c.legend_collapsed), ({'1': [0.3, 0.4]}, ['1']))
        self.assertEqual([ruler.name for ruler in c.rulers], ['A', 'B'])

    def test_plots_that_cannot_share_an_x_axis_are_not_joined(self):
        canvas = _stacked(_canvas(COLUMN))
        _plot(canvas, 'D').axes[0].is_date = True

        self.assertIsNone(laid_out(canvas, 1, 2))
        self.assertIsNotNone(laid_out(canvas, 2, 2))

    def test_a_plot_with_a_slider_is_not_joined(self):
        canvas = _stacked(_canvas({'A': (0, 0, 1, 1), 'B': (1, 0, 1, 1)}))
        slider = PlotXYWithSlider(plot_title='C', row=3, col=1)
        slider.add_signal(SignalXY(label='C1'))
        canvas.plots[0].append(slider)

        self.assertIsNone(laid_out(canvas, 1, 2))

    def test_a_reserved_slot_takes_a_cell_but_is_not_joined(self):
        canvas = _stacked(_canvas({'A': (0, 0, 1, 1), 'C': (2, 0, 1, 1)}, rows=3, cols=1))

        arrangement = laid_out(canvas, 1, 3, [Slot(1, 0)])

        self.assertEqual(_places(arrangement), {'A': (0, 0, 1, 1), 'C': (0, 2, 1, 1)})
        self.assertEqual(arrangement.reserved, [Slot(0, 1)])
        self.assertIsNone(laid_out(canvas, 1, 2, [Slot(1, 0)]))

    def test_a_canvas_with_no_plot_takes_the_grid(self):
        canvas = Canvas()

        arrange(canvas, laid_out(canvas, 2, 3))

        self.assertEqual((canvas.rows, canvas.cols, canvas.layout_rows, canvas.layout_cols), (2, 3, 2, 3))
        self.assertEqual(canvas.plots, [[], [], []])


def _titles(canvas: Canvas) -> list:
    return [[plot.plot_title if plot is not None else None for plot in column] for column in canvas.plots]


if __name__ == '__main__':
    unittest.main()
