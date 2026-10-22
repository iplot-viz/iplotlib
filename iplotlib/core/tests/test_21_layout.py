"""Unit tests for the arrangement of the plots on the grid of a canvas (moving and resizing plots)."""

import unittest

from iplotlib.core.canvas import Canvas
from iplotlib.core.layout import Arrangement, Slot, arrange, current, grid_size, moved, resized, slots_of
from iplotlib.core.plot import PlotXY


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


if __name__ == '__main__':
    unittest.main()
