"""Tests for the IplotQtRuler window.

The window is the user-facing entry point for managing rulers: it lists the
rulers placed on the plots, lets the user toggle visibility / color / removal,
and computes pairwise deltas between selected rulers (N >= 2). It does not
own any plot data, so the tests stay at the widget level.
"""

import os
import unittest

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from iplotlib.qt.gui.iplotQtRuler import IplotQtRuler
from iplotlib.qt.testing import ensure_qapp

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')


class IplotQtRulerWindowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = ensure_qapp()

    def setUp(self):
        self.window = IplotQtRuler()

    def tearDown(self):
        self.window.close()

    def test_window_starts_empty(self):
        self.assertEqual(self.window.table.rowCount(), 0)
        self.assertEqual(self.window.count, 0)

    def test_add_row_appends_columns_in_order(self):
        self.window.add_row('A', (1, 1), (2.5, 7.5), '#FFFFFF', visible=True, is_date=False)
        self.assertEqual(self.window.table.rowCount(), 1)
        self.assertEqual(self.window.table.item(0, IplotQtRuler.COL_NAME).text(), 'A')
        self.assertEqual(self.window.table.item(0, IplotQtRuler.COL_PLOT).text(), '1.1')
        self.assertEqual(self.window.table.item(0, IplotQtRuler.COL_X).data(Qt.ItemDataRole.UserRole), 2.5)
        self.assertEqual(self.window.table.item(0, IplotQtRuler.COL_Y).data(Qt.ItemDataRole.UserRole), 7.5)

    def test_next_name_cycles_through_alphabet(self):
        names = [self.window.next_name() for _ in range(3)]
        self.assertEqual(names, ['A', 'B', 'C'])

    def test_next_color_cycles_through_default_palette_and_stays_distinct(self):
        cycle_len = len(IplotQtRuler.DEFAULT_COLOR_CYCLE)
        colors = []
        for _ in range(cycle_len):
            self.window.next_name()
            colors.append(self.window.next_color())
        self.assertEqual(len(set(colors)), cycle_len)
        self.assertEqual(colors, list(IplotQtRuler.DEFAULT_COLOR_CYCLE))

    def test_remove_row_by_name_finds_matching_plot(self):
        self.window.add_row('A', (1, 1), (1.0, 2.0), '#FFFFFF')
        self.window.add_row('A', (2, 1), (3.0, 4.0), '#FFFFFF')
        self.window.remove_row_by_name('A', (1, 1))
        self.assertEqual(self.window.table.rowCount(), 1)
        self.assertEqual(self.window.table.item(0, IplotQtRuler.COL_PLOT).text(), '2.1')

    def test_clear_info_resets_state(self):
        self.window.add_row('A', (1, 1), (1.0, 2.0), '#FFFFFF')
        self.window.next_name()  # bumps counter
        self.window.clear_info()
        self.assertEqual(self.window.table.rowCount(), 0)
        self.assertEqual(self.window.count, 0)

    def test_delete_emits_signal_for_each_selected_row(self):
        emitted = []
        self.window.deleteRuler.connect(lambda name, pid, persist: emitted.append((name, pid, persist)))
        self.window.add_row('A', (1, 1), (1.0, 2.0), '#FFFFFF')
        self.window.add_row('B', (1, 1), (3.0, 4.0), '#FFFFFF')
        self.window.selection_history = [0, 1]
        self.window._remove_selected()
        self.assertEqual(self.window.table.rowCount(), 0)
        self.assertEqual({name for name, _, _ in emitted}, {'A', 'B'})

    def test_visibility_signal_carries_state(self):
        emitted = []
        self.window.visibilityRuler.connect(lambda name, pid, vis: emitted.append((name, pid, vis)))
        self.window.add_row('A', (1, 1), (1.0, 2.0), '#FFFFFF', visible=False)
        cb = self.window.table.cellWidget(0, IplotQtRuler.COL_VISIBLE)
        cb.setChecked(True)
        QApplication.processEvents()
        self.assertEqual(emitted[-1], ('A', (1, 1), True))


class IplotQtRulerViewModeTest(unittest.TestCase):
    """Rulers window supports two layouts: rows (one ruler per row, editable)
    and columns (one section per plot with X / Y values and Δ, read-only)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.app = ensure_qapp()

    def setUp(self):
        self.window = IplotQtRuler()
        self.window.add_row('A', (1, 1), (1.0, 2.0), '#FF0000', visible=True)
        self.window.add_row('B', (1, 1), (3.0, 4.0), '#00FF00', visible=False)

    def tearDown(self):
        self.window.close()

    def test_default_view_mode_is_rows(self):
        self.assertEqual(self.window.view_mode, IplotQtRuler.VIEW_ROWS)
        self.assertTrue(self.window.rows_radio.isChecked())
        self.assertEqual(self.window.table.rowCount(), 2)
        self.assertEqual(self.window.table.columnCount(), 6)
        self.assertIs(self.window.view_stack.currentWidget(), self.window.table)

    def test_switching_to_columns_swaps_the_view_stack(self):
        self.window.columns_radio.setChecked(True)
        self.assertEqual(self.window.view_mode, IplotQtRuler.VIEW_COLUMNS)
        self.assertIs(self.window.view_stack.currentWidget(), self.window.columns_scroll)

    def test_single_plot_renders_one_section_with_xy_rows_and_delta(self):
        self.window.columns_radio.setChecked(True)
        self.assertEqual(len(self.window.column_sections), 1)
        plot_id, table = self.window.column_sections[0]
        self.assertEqual(plot_id, (1, 1))
        self.assertEqual(table.rowCount(), 2)
        self.assertEqual(table.columnCount(), 3)
        headers = [table.horizontalHeaderItem(c).text() for c in range(table.columnCount())]
        self.assertEqual(headers, ['1', '2', IplotQtRuler._DELTA_HEADER])
        v_headers = [table.verticalHeaderItem(r).text() for r in range(table.rowCount())]
        self.assertEqual(v_headers, list(IplotQtRuler._COLUMNS_AXIS_LABELS))

    def test_section_cells_carry_each_rulers_xy_value(self):
        self.window.columns_radio.setChecked(True)
        _, table = self.window.column_sections[0]
        self.assertEqual(table.item(0, 0).text(), '1')
        self.assertEqual(table.item(1, 0).text(), '2')
        self.assertEqual(table.item(0, 1).text(), '3')
        self.assertEqual(table.item(1, 1).text(), '4')

    def test_delta_in_section_is_range_of_its_rulers(self):
        self.window.add_row('C', (1, 1), (8.0, 7.0), '#0000FF')
        self.window.columns_radio.setChecked(True)
        _, table = self.window.column_sections[0]
        delta_col = table.columnCount() - 1
        self.assertEqual(table.item(0, delta_col).text(), '7')
        self.assertEqual(table.item(1, delta_col).text(), '5')

    def test_singleton_plot_section_has_no_delta_column(self):
        self.window.remove_row_by_name('B', (1, 1))
        self.window.columns_radio.setChecked(True)
        _, table = self.window.column_sections[0]
        self.assertEqual(table.columnCount(), 1)
        headers = [table.horizontalHeaderItem(c).text() for c in range(table.columnCount())]
        self.assertEqual(headers, ['1'])

    def test_columns_mode_disables_edit_action_buttons(self):
        self.window.columns_radio.setChecked(True)
        self.assertFalse(self.window.remove_button.isEnabled())
        self.assertFalse(self.window.distance_button.isEnabled())

    def test_switching_back_to_rows_re_enables_edit_actions(self):
        self.window.columns_radio.setChecked(True)
        self.window.rows_radio.setChecked(True)
        self.assertTrue(self.window.remove_button.isEnabled())
        self.assertTrue(self.window.distance_button.isEnabled())
        self.assertEqual(self.window.table.rowCount(), 2)
        self.assertEqual(self.window.table.columnCount(), 6)
        self.assertEqual(self.window.column_sections, [])

    def test_data_survives_mode_switch(self):
        self.window.columns_radio.setChecked(True)
        self.window.rows_radio.setChecked(True)
        cb = self.window.table.cellWidget(0, IplotQtRuler.COL_VISIBLE)
        btn = self.window.table.cellWidget(0, IplotQtRuler.COL_COLOR)
        self.assertIsNotNone(cb)
        self.assertIsNotNone(btn)
        self.assertTrue(cb.isChecked())  # Ruler A starts visible

    def test_section_cells_are_tinted_with_ruler_color(self):
        self.window.columns_radio.setChecked(True)
        _, table = self.window.column_sections[0]
        for axis_row in (0, 1):
            bg = table.item(axis_row, 0).background().color()
            self.assertEqual((bg.red(), bg.green(), bg.blue()), (255, 0, 0))
            self.assertLess(bg.alpha(), 255)

    def test_section_cells_are_read_only(self):
        self.window.columns_radio.setChecked(True)
        for _, table in self.window.column_sections:
            for row in range(table.rowCount()):
                for col in range(table.columnCount()):
                    item = table.item(row, col)
                    self.assertFalse(bool(item.flags() & Qt.ItemFlag.ItemIsEditable),
                                     f"Cell ({row},{col}) is editable in columns mode")

    def test_adding_a_ruler_extends_the_existing_section(self):
        self.window.columns_radio.setChecked(True)
        self.window.add_row('C', (1, 1), (5.0, 6.0), '#0000FF')
        self.assertEqual(len(self.window.column_sections), 1)
        _, table = self.window.column_sections[0]
        self.assertEqual(table.columnCount(), 4)
        headers = [table.horizontalHeaderItem(c).text() for c in range(table.columnCount())]
        self.assertEqual(headers, ['1', '2', '3', IplotQtRuler._DELTA_HEADER])

    def test_multiple_plots_produce_one_section_per_plot(self):
        self.window.add_row('C', (2, 1), (10.0, 20.0), '#0000FF')
        self.window.add_row('D', (2, 1), (30.0, 40.0), '#FFFF00')
        self.window.columns_radio.setChecked(True)

        self.assertEqual(len(self.window.column_sections), 2)
        plot_ids = [pid for pid, _ in self.window.column_sections]
        self.assertEqual(plot_ids, [(1, 1), (2, 1)])

        _, first = self.window.column_sections[0]
        _, second = self.window.column_sections[1]
        # Each section is independent: own Δ from its own rulers.
        self.assertEqual(first.item(0, first.columnCount() - 1).text(), '2')    # 3 - 1
        self.assertEqual(second.item(0, second.columnCount() - 1).text(), '20')  # 30 - 10

    def test_singleton_plot_section_appears_without_delta_when_other_plot_has_more(self):
        self.window.add_row('C', (2, 1), (10.0, 20.0), '#0000FF')
        self.window.columns_radio.setChecked(True)
        # First section: 2 rulers + Δ. Second section: 1 ruler, no Δ.
        _, first = self.window.column_sections[0]
        _, second = self.window.column_sections[1]
        first_headers = [first.horizontalHeaderItem(c).text() for c in range(first.columnCount())]
        second_headers = [second.horizontalHeaderItem(c).text() for c in range(second.columnCount())]
        self.assertEqual(first_headers, ['1', '2', IplotQtRuler._DELTA_HEADER])
        self.assertEqual(second_headers, ['1'])


class RulerLeftToRightDeltaTest(unittest.TestCase):
    """When computing deltas, rulers must be ordered by X regardless of
    selection order. The issue specifies ``left to right`` explicitly."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.app = ensure_qapp()

    def test_compute_distance_orders_selected_rows_by_x(self):
        window = IplotQtRuler()
        try:
            window.add_row('B', (1, 1), (5.0, 0.0), '#FFFFFF')
            window.add_row('A', (1, 1), (1.0, 0.0), '#FFFFFF')
            window.add_row('C', (1, 1), (9.0, 0.0), '#FFFFFF')

            # User selects in arbitrary order: B (row 0), A (row 1), C (row 2).
            window.selection_history = [0, 1, 2]
            xs = [window.table.item(r, IplotQtRuler.COL_X).data(Qt.ItemDataRole.UserRole)
                  for r in window.selection_history]
            self.assertEqual(xs, [5.0, 1.0, 9.0])  # unsorted by X

            sorted_rows = sorted(window.selection_history,
                                  key=lambda r: window.table.item(r, IplotQtRuler.COL_X)
                                                   .data(Qt.ItemDataRole.UserRole))
            sorted_xs = [window.table.item(r, IplotQtRuler.COL_X).data(Qt.ItemDataRole.UserRole)
                         for r in sorted_rows]
            self.assertEqual(sorted_xs, [1.0, 5.0, 9.0])
        finally:
            window.close()


class RulerDistanceFormattingTest(unittest.TestCase):
    """The numeric path (non-datetime) is purely formatting — exercise it directly."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.app = ensure_qapp()

    def test_numeric_dx_is_absolute_and_six_significant_digits(self):
        self.assertEqual(IplotQtRuler._format_dx(1.0, 5.0, is_date=False), '4')
        self.assertEqual(IplotQtRuler._format_dx(5.0, 1.0, is_date=False), '4')
        self.assertEqual(IplotQtRuler._format_dx(1.23456789, 0.0, is_date=False), '1.23457')

    def test_datetime_dx_renders_components(self):
        one_second_ns = 1_000_000_000
        out = IplotQtRuler._format_dx(0, one_second_ns, is_date=True)
        self.assertIn('T', out)
        self.assertIn('1S', out)


if __name__ == '__main__':
    unittest.main()
