"""Tests for the IplotQtCrosshair window (issue #130).

The frozen-crosshair window reuses the ruler table chrome but presents a
different content model: Time + one value column per signal, with a show/hide
toggle for those columns and time+per-signal deltas. These tests pin that the
per-signal layout is built correctly and that the reused identity/selection
plumbing keeps working with the shifted column indices.
"""

import os
import unittest

from PySide6.QtCore import Qt

from iplotlib.qt.gui.iplotQtCrosshair import IplotQtCrosshair
from iplotlib.qt.testing import ensure_qapp

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')


class IplotQtCrosshairWindowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = ensure_qapp()

    def setUp(self):
        self.window = IplotQtCrosshair()

    def tearDown(self):
        self.window.close()

    def test_window_starts_empty(self):
        self.assertEqual(self.window.table.rowCount(), 0)
        self.assertEqual(self.window.windowTitle(), "Crosshairs window")

    def test_name_and_plot_columns_stay_at_0_and_1(self):
        # Inherited identity/selection slots depend on these fixed positions.
        self.assertEqual(IplotQtCrosshair.COL_NAME, 0)
        self.assertEqual(IplotQtCrosshair.COL_PLOT, 1)
        self.assertEqual(IplotQtCrosshair.COL_TIME, 2)

    def test_per_signal_columns_are_built_from_row_values(self):
        self.window.add_row('A', (1, 1), (2.5, 0.0), '#FFFFFF',
                            signal_values={'sig1': 10.0, 'sig2': 20.0})
        headers = [self.window.table.horizontalHeaderItem(c).text()
                   for c in range(self.window.table.columnCount())]
        self.assertEqual(headers[:3], ['Crosshair', 'Plot', 'Time'])
        self.assertIn('sig1', headers)
        self.assertIn('sig2', headers)
        # Time cell carries the frozen x as sortable numeric data.
        self.assertEqual(self.window.table.item(0, IplotQtCrosshair.COL_TIME)
                         .data(Qt.ItemDataRole.UserRole), 2.5)

    def test_signal_columns_are_union_across_rows(self):
        self.window.add_row('A', (1, 1), (1.0, 0.0), '#FFFFFF', signal_values={'sig1': 1.0})
        self.window.add_row('B', (2, 1), (2.0, 0.0), '#FFFFFF', signal_values={'sig2': 2.0})
        headers = [self.window.table.horizontalHeaderItem(c).text()
                   for c in range(self.window.table.columnCount())]
        self.assertIn('sig1', headers)
        self.assertIn('sig2', headers)

    def test_toggle_hides_and_shows_signal_columns(self):
        self.window.add_row('A', (1, 1), (1.0, 0.0), '#FFFFFF', signal_values={'sig1': 1.0})
        sig_col = self.window._signal_col(0)
        self.assertFalse(self.window.table.isColumnHidden(sig_col))
        self.window._toggle_signal_columns()
        self.assertTrue(self.window.table.isColumnHidden(sig_col))
        self.window._toggle_signal_columns()
        self.assertFalse(self.window.table.isColumnHidden(sig_col))

    def test_missing_signal_value_leaves_blank_cell(self):
        self.window.add_row('A', (1, 1), (1.0, 0.0), '#FFFFFF', signal_values={'sig1': 1.0})
        self.window.add_row('B', (2, 1), (2.0, 0.0), '#FFFFFF', signal_values={'sig2': 2.0})
        # Row 'A' has no sig2 -> that cell must be empty, not an error.
        a_row = next(r for r in range(self.window.table.rowCount())
                     if self.window.table.item(r, IplotQtCrosshair.COL_NAME).text() == 'A')
        headers = [self.window.table.horizontalHeaderItem(c).text()
                   for c in range(self.window.table.columnCount())]
        sig2_col = headers.index('sig2')
        self.assertEqual(self.window.table.item(a_row, sig2_col).text(), '')

    def test_signal_column_is_tinted_with_the_curve_color(self):
        self.window.add_row('A', (1, 1), (1.0, 0.0), '#FFFFFF',
                            signal_values={'sig1': {'value': 10.0, 'color': '#123456'}})
        headers = [self.window.table.horizontalHeaderItem(c).text()
                   for c in range(self.window.table.columnCount())]
        sig_col = headers.index('sig1')
        header_item = self.window.table.horizontalHeaderItem(sig_col)
        self.assertEqual(header_item.background().color().name(), '#123456')
        self.assertEqual(self.window.table.item(0, sig_col).background().color().name(), '#123456')

    def test_axis_formatted_text_is_shown_when_present(self):
        self.window.add_row('A', (1, 1), (1.0, 0.0), '#FFFFFF',
                            signal_values={'sig1': {'value': 12.3456789, 'text': '12.3 kA'}})
        headers = [self.window.table.horizontalHeaderItem(c).text()
                   for c in range(self.window.table.columnCount())]
        sig_col = headers.index('sig1')
        self.assertEqual(self.window.table.item(0, sig_col).text(), '12.3 kA')

    def test_plain_float_signal_value_still_supported(self):
        # Backward-compatible: a bare number degrades to value-only, no tint.
        self.window.add_row('A', (1, 1), (1.0, 0.0), '#FFFFFF', signal_values={'sig1': 7.5})
        headers = [self.window.table.horizontalHeaderItem(c).text()
                   for c in range(self.window.table.columnCount())]
        sig_col = headers.index('sig1')
        self.assertEqual(self.window.table.item(0, sig_col).text(), '7.5')

    def test_signal_deltas_are_numeric_differences(self):
        self.window.add_row('A', (1, 1), (1.0, 0.0), '#FFFFFF', signal_values={'sig1': 10.0})
        self.window.add_row('B', (2, 1), (2.0, 0.0), '#FFFFFF', signal_values={'sig1': 25.0})
        # table rows for A and B after sort
        rows = {self.window.table.item(r, IplotQtCrosshair.COL_NAME).text(): r
                for r in range(self.window.table.rowCount())}
        deltas = dict(self.window._signal_deltas(rows['A'], rows['B']))
        self.assertAlmostEqual(deltas['sig1'], 15.0)

    def test_remove_row_by_name_still_works_with_signal_columns(self):
        self.window.add_row('A', (1, 1), (1.0, 0.0), '#FFFFFF', signal_values={'sig1': 1.0})
        self.window.add_row('B', (2, 1), (2.0, 0.0), '#FFFFFF', signal_values={'sig1': 2.0})
        self.window.remove_row_by_name('A', (1, 1))
        names = {self.window.table.item(r, IplotQtCrosshair.COL_NAME).text()
                 for r in range(self.window.table.rowCount())}
        self.assertEqual(names, {'B'})


class IplotQtCrosshairCompareViewTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = ensure_qapp()

    def setUp(self):
        self.window = IplotQtCrosshair()
        # A at t=1, B at t=2 so the chronological Δ is B − A.
        self.window.add_row('A', (1, 1), (1.0, 0.0), '#FFFFFF',
                            signal_values={'sig1': {'value': 10.0, 'color': '#111111'},
                                           'sig2': {'value': 5.0, 'color': '#222222'}})
        self.window.add_row('B', (1, 1), (2.0, 0.0), '#FFFFFF',
                            signal_values={'sig1': {'value': 30.0, 'color': '#111111'},
                                           'sig2': {'value': 1.0, 'color': '#222222'}})
        self.window.columns_radio.setChecked(True)  # switch to Compare

    def tearDown(self):
        self.window.close()

    def _compare_table(self):
        return self.window.columns_layout.itemAt(0).widget()

    def _headers(self, table):
        return [table.horizontalHeaderItem(c).text() for c in range(table.columnCount())]

    def _row_of(self, table, signal):
        for r in range(table.rowCount()):
            if table.item(r, 0).text() == signal:
                return r
        return -1

    def test_compare_transposes_signals_to_rows_and_crosshairs_to_columns(self):
        table = self._compare_table()
        headers = self._headers(table)
        self.assertEqual(headers[0], 'Signal')
        self.assertIn('A', headers)
        self.assertIn('B', headers)
        self.assertTrue(any('Δ' in h for h in headers))
        self.assertEqual(table.rowCount(), 2)  # one row per signal

    def test_delta_column_is_last_minus_first(self):
        table = self._compare_table()
        delta_col = table.columnCount() - 1
        r = self._row_of(table, 'sig1')
        self.assertEqual(table.item(r, delta_col).text(), '20')  # 30 − 10

    def test_compare_bar_visible_only_in_compare(self):
        self.assertFalse(self.window._compare_bar.isHidden())
        self.window.rows_radio.setChecked(True)  # back to List
        self.assertTrue(self.window._compare_bar.isHidden())

    def test_sort_by_delta_descending_orders_rows_by_change(self):
        # sig1 Δ = +20, sig2 Δ = −4  -> descending puts sig1 first.
        idx = self.window.sort_combo.findData('Δ')
        self.window.sort_combo.setCurrentIndex(idx)
        table = self._compare_table()
        self.assertEqual(table.item(0, 0).text(), 'sig1')

    def test_filter_hides_non_matching_signal_rows(self):
        self.window.filter_edit.setText('sig2')
        table = self._compare_table()
        labels = {table.item(r, 0).text() for r in range(table.rowCount())}
        self.assertEqual(labels, {'sig2'})

    def test_delta_uses_first_and_last_present_values(self):
        # Each crosshair only carries its own plot's signals, so a signal is
        # usually present in a subset of the columns. Δ must span the present
        # readings, not columns 0 and -1 (which would blank out).
        w = IplotQtCrosshair()
        try:
            w.add_row('A', (1, 1), (1.0, 0.0), '#FFFFFF', signal_values={'sigX': {'value': 100.0}})
            w.add_row('B', (2, 1), (2.0, 0.0), '#FFFFFF', signal_values={'sigY': {'value': 10.0}})
            w.add_row('C', (2, 1), (3.0, 0.0), '#FFFFFF', signal_values={'sigY': {'value': 25.0}})
            w.columns_radio.setChecked(True)
            table = w.columns_layout.itemAt(0).widget()
            delta_col = table.columnCount() - 1
            rows = {table.item(r, 0).text(): r for r in range(table.rowCount())}
            self.assertEqual(table.item(rows['sigY'], delta_col).text(), '15')  # 25 − 10
            self.assertEqual(table.item(rows['sigX'], delta_col).text(), '')    # single reading
        finally:
            w.close()

    def test_colour_cells_toggle_shades_value_cells(self):
        self.window.colour_check.setChecked(True)
        table = self._compare_table()
        r = self._row_of(table, 'sig1')
        # sig1 has values 10 and 30 -> the higher one gets a stronger wash.
        a_alpha = table.item(r, 1).background().color().alpha()
        b_alpha = table.item(r, 2).background().color().alpha()
        self.assertGreater(b_alpha, a_alpha)


if __name__ == '__main__':
    unittest.main()
