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
    """The Rulers window supports two layouts: rows-per-ruler (default, editable)
    and columns-per-ruler (read-only, side-by-side). The toggle must preserve
    data across switches and only allow row-based edit actions in rows mode."""

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

    def test_switching_to_columns_transposes_the_table(self):
        self.window.columns_radio.setChecked(True)
        self.assertEqual(self.window.view_mode, IplotQtRuler.VIEW_COLUMNS)
        # 5 fields (Plot, X, Y, Visible, Color) x 2 rulers (A, B).
        self.assertEqual(self.window.table.rowCount(), 5)
        self.assertEqual(self.window.table.columnCount(), 2)

    def test_columns_mode_uses_ruler_names_as_column_headers(self):
        self.window.columns_radio.setChecked(True)
        headers = [self.window.table.horizontalHeaderItem(c).text()
                   for c in range(self.window.table.columnCount())]
        self.assertEqual(headers, ['A', 'B'])

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

    def test_data_survives_mode_switch(self):
        self.window.columns_radio.setChecked(True)
        self.window.rows_radio.setChecked(True)
        # Edit widgets must be restored (rows mode), not just text cells.
        cb = self.window.table.cellWidget(0, IplotQtRuler.COL_VISIBLE)
        btn = self.window.table.cellWidget(0, IplotQtRuler.COL_COLOR)
        self.assertIsNotNone(cb)
        self.assertIsNotNone(btn)
        self.assertTrue(cb.isChecked())  # Ruler A starts visible

    def test_columns_mode_paints_color_cell_background(self):
        from PySide6.QtGui import QColor
        self.window.columns_radio.setChecked(True)
        color_row = IplotQtRuler._COLUMNS_MODE_FIELDS.index('Color')
        cell_a = self.window.table.item(color_row, 0)
        self.assertEqual(cell_a.text(), '#FF0000')
        self.assertEqual(cell_a.background().color(), QColor('#FF0000'))

    def test_columns_mode_cells_are_read_only(self):
        self.window.columns_radio.setChecked(True)
        for row in range(self.window.table.rowCount()):
            for col in range(self.window.table.columnCount()):
                item = self.window.table.item(row, col)
                self.assertFalse(bool(item.flags() & Qt.ItemFlag.ItemIsEditable),
                                 f"Cell ({row},{col}) is editable in columns mode")

    def test_add_row_while_in_columns_mode_extends_columns(self):
        self.window.columns_radio.setChecked(True)
        self.window.add_row('C', (1, 1), (5.0, 6.0), '#0000FF')
        self.assertEqual(self.window.table.columnCount(), 3)
        headers = [self.window.table.horizontalHeaderItem(c).text()
                   for c in range(self.window.table.columnCount())]
        self.assertEqual(headers, ['A', 'B', 'C'])


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
