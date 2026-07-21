"""Tests for the IplotQtRuler window.

The window is the user-facing entry point for managing rulers: it lists the
rulers placed on the plots, lets the user toggle visibility / color / removal,
and computes pairwise deltas between selected rulers (N >= 2). It does not
own any plot data, so the tests stay at the widget level.
"""

import os
import unittest

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QHeaderView

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
        self.assertEqual(self.window.table.item(0, IplotQtRuler.COL_PLOT).text(), '1')
        self.assertEqual(self.window.table.item(0, IplotQtRuler.COL_X).data(Qt.ItemDataRole.UserRole), 2.5)
        self.assertEqual(self.window.table.item(0, IplotQtRuler.COL_Y).data(Qt.ItemDataRole.UserRole), 7.5)

    def test_next_name_cycles_through_alphabet(self):
        names = []
        for _ in range(3):
            n = self.window.next_name()
            self.window.add_row(n, (1, 1), (0.0, 0.0), '#FFFFFF')
            names.append(n)
        self.assertEqual(names, ['A', 'B', 'C'])

    def test_next_name_fills_gaps_after_removal(self):
        for _ in range(3):
            n = self.window.next_name()
            self.window.add_row(n, (1, 1), (0.0, 0.0), '#FFFFFF')
        self.window.remove_row_by_name('B', (1, 1))
        self.assertEqual(self.window.next_name(), 'B')

    def test_next_color_is_stable_per_letter(self):
        palette = IplotQtRuler.DEFAULT_COLOR_CYCLE
        self.assertEqual(self.window.next_color('A'), palette[0])
        self.assertEqual(self.window.next_color('B'), palette[1])
        self.assertEqual(self.window.next_color('J'), palette[9])
        self.assertEqual(self.window.next_color('A'), palette[0])

    def test_remove_row_by_name_finds_matching_plot(self):
        self.window.add_row('A', (1, 1), (1.0, 2.0), '#FFFFFF')
        self.window.add_row('A', (2, 1), (3.0, 4.0), '#FFFFFF')
        self.window.remove_row_by_name('A', (1, 1))
        self.assertEqual(self.window.table.rowCount(), 1)
        self.assertEqual(self.window.table.item(0, IplotQtRuler.COL_PLOT).text(), '2')

    def test_plot_id_drops_column_suffix_for_single_column_canvas(self):
        self.window.set_canvas_columns(1)
        self.window.add_row('A', (3, 1), (1.0, 2.0), '#FFFFFF')
        self.assertEqual(self.window.table.item(0, IplotQtRuler.COL_PLOT).text(), '3')

    def test_plot_id_keeps_column_suffix_when_canvas_has_multiple_columns(self):
        self.window.set_canvas_columns(2)
        self.window.add_row('A', (3, 1), (1.0, 2.0), '#FFFFFF')
        self.window.add_row('B', (1, 2), (3.0, 4.0), '#FFFFFF')
        self.assertEqual(self.window.table.item(0, IplotQtRuler.COL_PLOT).text(), '3.1')
        self.assertEqual(self.window.table.item(1, IplotQtRuler.COL_PLOT).text(), '1.2')

    def test_set_canvas_columns_re_renders_existing_rows(self):
        self.window.add_row('A', (2, 1), (1.0, 2.0), '#FFFFFF')
        self.assertEqual(self.window.table.item(0, IplotQtRuler.COL_PLOT).text(), '2')
        self.window.set_canvas_columns(2)
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
        cb = self.window.table.cellWidget(0, self.window.COL_VISIBLE)
        cb.setChecked(True)
        QApplication.processEvents()
        self.assertEqual(emitted[-1], ('A', (1, 1), True))

    def test_default_palette_reverses_the_signal_palette(self):
        from iplotlib.core.plot import PlotXY
        self.assertEqual(IplotQtRuler.DEFAULT_COLOR_CYCLE, list(reversed(PlotXY._color_cycle)))

    def test_color_button_label_contrasts_with_background(self):
        self.assertEqual(IplotQtRuler._contrast_text_color('#ffffff'), 'black')
        self.assertEqual(IplotQtRuler._contrast_text_color('#ffff00'), 'black')  # yellow
        self.assertEqual(IplotQtRuler._contrast_text_color('#000000'), 'white')
        self.assertEqual(IplotQtRuler._contrast_text_color('#00008b'), 'white')  # dark blue

    def test_add_row_defaults_all_labels_and_white_font(self):
        self.window.add_row('A', (1, 1), (1.0, 2.0), '#FF0000')
        combo = self.window.table.cellWidget(0, self.window.COL_LABEL)
        self.assertEqual(combo.checked_flags(), [True, True])
        self.assertEqual(combo.currentText(), 'All')
        font_btn = self.window.table.cellWidget(0, self.window.COL_FONT_COLOR)
        self.assertEqual(font_btn.property('color'), '#FFFFFF')

    def test_label_toggles_carry_each_flag_independently(self):
        emitted = []
        self.window.labelVisibilityRuler.connect(
            lambda name, pid, show, show_val: emitted.append((name, pid, show, show_val)))
        self.window.add_row('A', (1, 1), (1.0, 2.0), '#FFFFFF')
        combo = self.window.table.cellWidget(0, self.window.COL_LABEL)
        combo.set_checked(0, False)  # uncheck Ruler label
        QApplication.processEvents()
        self.assertEqual(emitted[-1], ('A', (1, 1), False, True))
        self.assertFalse(self.window._rows[0]['show_label'])
        self.assertTrue(self.window._rows[0]['show_val_label'])
        self.assertEqual(combo.currentText(), 'Val label')
        combo.set_checked(1, False)  # uncheck Val label too
        QApplication.processEvents()
        self.assertEqual(emitted[-1], ('A', (1, 1), False, False))
        self.assertEqual(combo.currentText(), 'None')

    def test_copy_rows_view_selection_as_tab_separated_text(self):
        self.window.add_row('A', (1, 1), (2.5, 7.5), '#FF0000')
        self.window.table.selectRow(0)
        self.window._copy_table_selection(self.window.table)
        copied = QApplication.clipboard().text()
        self.assertEqual(copied, 'A\t1\t2.5\t7.5\ttrue\tAll\t#FF0000\t#FFFFFF')

    def test_each_signal_gets_its_own_column(self):
        self.window.add_row('A', (1, 1), (2.5, 7.5), '#FFFFFF',
                            signal_values={'VAR1': 1.2, 'VAR2': 3.4})
        base = IplotQtRuler.SIG_COL_BASE
        headers = [self.window.table.horizontalHeaderItem(base + i).text() for i in (0, 1)]
        self.assertEqual(headers, ['VAR1', 'VAR2'])
        self.assertEqual(self.window.table.item(0, base).text(), '1.2')
        self.assertEqual(self.window.table.item(0, base + 1).text(), '3.4')
        for i in (0, 1):
            item = self.window.table.item(0, base + i)
            self.assertFalse(bool(item.flags() & Qt.ItemFlag.ItemIsEditable))

    def test_signal_columns_union_blank_when_missing(self):
        self.window.add_row('A', (1, 1), (2.5, 7.5), '#FFFFFF', signal_values={'VAR1': 1.2})
        self.window.add_row('B', (2, 1), (3.0, 8.0), '#FFFFFF', signal_values={'VAR2': 5.0})
        base = IplotQtRuler.SIG_COL_BASE
        self.assertEqual(self.window._signal_labels, ['VAR1', 'VAR2'])
        # Row A has no VAR2 and row B no VAR1: those cells stay blank.
        self.assertEqual(self.window.table.item(0, base + 1).text(), '')
        self.assertEqual(self.window.table.item(1, base).text(), '')

    def test_long_signal_names_wrap_in_the_header(self):
        long_name = 'UTIL-S15-VA-RB01:VLV6106-SViPos'
        self.window.add_row('A', (1, 1), (2.5, 7.5), '#FFFFFF',
                            signal_values={long_name: 1.0})
        item = self.window.table.horizontalHeaderItem(IplotQtRuler.SIG_COL_BASE)
        self.assertIn('\n', item.text())
        self.assertEqual(item.text().replace('\n', ''), long_name)
        self.assertEqual(item.toolTip(), long_name)

    def test_update_row_xy_refreshes_signal_values(self):
        self.window.add_row('A', (1, 1), (2.5, 7.5), '#FFFFFF', signal_values={'VAR1': 1.0})
        self.window.update_row_xy('A', (1, 1), (3.0, 8.0), signal_values={'VAR1': 2.0})
        self.assertEqual(self.window._rows[0]['signal_values'], {'VAR1': 2.0})
        self.assertEqual(
            self.window.table.item(0, IplotQtRuler.SIG_COL_BASE).text(), '2')

    def test_hide_show_signals_menu_toggles_the_column(self):
        self.window.add_row('A', (1, 1), (2.5, 7.5), '#FFFFFF',
                            signal_values={'VAR1': 1.2, 'VAR2': 3.4})
        base = IplotQtRuler.SIG_COL_BASE
        actions = self.window.signals_menu.actions()
        self.assertEqual([a.text() for a in actions], ['VAR1', 'VAR2'])
        self.assertTrue(all(a.isChecked() for a in actions))
        actions[0].setChecked(False)
        self.assertTrue(self.window.table.isColumnHidden(base))
        self.assertFalse(self.window.table.isColumnHidden(base + 1))
        # Hidden signals survive a re-render (e.g. another ruler is added).
        self.window.add_row('B', (1, 1), (3.0, 8.0), '#FFFFFF', signal_values={'VAR1': 2.0})
        self.assertTrue(self.window.table.isColumnHidden(base))
        actions = self.window.signals_menu.actions()
        self.assertFalse(actions[0].isChecked())
        actions[0].setChecked(True)
        self.assertFalse(self.window.table.isColumnHidden(base))

    def test_copy_button_copies_whole_table_with_headers(self):
        self.window.add_row('A', (1, 1), (2.5, 7.5), '#FF0000', signal_values={'VAR1': 1.2})
        self.window._copy_current_view()
        lines = QApplication.clipboard().text().split('\n')
        self.assertEqual(lines[0], 'Ruler\tPlot\tX value\tY value\tVAR1\t'
                                   'Visible\tLabels\tColor\tFont color')
        self.assertEqual(lines[1], 'A\t1\t2.5\t7.5\t1.2\ttrue\tAll\t#FF0000\t#FFFFFF')

    def _export_to(self, suffix: str):
        import csv
        import tempfile
        from unittest.mock import patch
        delimiter = ',' if suffix == '.csv' else ';'
        self.window.add_row('A', (1, 1), (2.5, 7.5), '#FF0000', signal_values={'VAR1': 1.2})
        fd, path = tempfile.mkstemp(suffix=suffix)
        os.close(fd)
        try:
            with patch('iplotlib.qt.gui.iplotQtRuler.QFileDialog.getSaveFileName',
                       return_value=(path, '')):
                self.window._export_csv()
            with open(path, newline='', encoding='utf-8') as fh:
                return list(csv.reader(fh, delimiter=delimiter))
        finally:
            os.unlink(path)

    def test_export_scsv_uses_semicolon_and_writes_every_column(self):
        rows = self._export_to('.scsv')
        self.assertEqual(rows[0], ['Ruler', 'Plot', 'X value', 'Y value', 'VAR1',
                                   'Visible', 'Labels', 'Color', 'Font color'])
        self.assertEqual(rows[1], ['A', '1', '2.5', '7.5', '1.2',
                                   'true', 'All', '#FF0000', '#FFFFFF'])

    def test_export_csv_extension_uses_comma(self):
        rows = self._export_to('.csv')
        self.assertEqual(rows[1][:5], ['A', '1', '2.5', '7.5', '1.2'])


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
        self.assertEqual(self.window.table.columnCount(), 8)
        self.assertIs(self.window.view_stack.currentWidget(), self.window.table)

    def test_switching_to_columns_swaps_the_view_stack(self):
        self.window.columns_radio.setChecked(True)
        self.assertEqual(self.window.view_mode, IplotQtRuler.VIEW_COLUMNS)
        self.assertIs(self.window.view_stack.currentWidget(), self.window.columns_scroll)

    def test_single_plot_renders_one_section_with_xy_rows_and_delta(self):
        self.window.columns_radio.setChecked(True)
        self.assertEqual(len(self.window.column_sections), 1)
        plot_id, table, _ = self.window.column_sections[0]
        self.assertEqual(plot_id, (1, 1))
        self.assertEqual(table.rowCount(), 2)
        self.assertEqual(table.columnCount(), 3)
        headers = [table.horizontalHeaderItem(c).text() for c in range(table.columnCount())]
        self.assertEqual(headers, ['A', IplotQtRuler._DELTA_HEADER, 'B'])
        v_headers = [table.verticalHeaderItem(r).text() for r in range(table.rowCount())]
        self.assertEqual(v_headers, list(IplotQtRuler._COLUMNS_AXIS_LABELS))

    def test_section_cells_carry_each_rulers_xy_value(self):
        self.window.columns_radio.setChecked(True)
        _, table, _ = self.window.column_sections[0]
        # Column 0: ruler A; column 1: Δ(B-A); column 2: ruler B.
        self.assertEqual(table.item(0, 0).text(), '1')
        self.assertEqual(table.item(1, 0).text(), '2')
        self.assertEqual(table.item(0, 2).text(), '3')
        self.assertEqual(table.item(1, 2).text(), '4')

    def test_section_shows_one_row_per_signal(self):
        self.window.clear_info()
        self.window.add_row('A', (1, 1), (1.0, 2.0), '#FF0000',
                            signal_values={'S1': 9.0, 'S2': -1.5})
        self.window.columns_radio.setChecked(True)
        _, table, sig_rows = self.window.column_sections[0]
        self.assertEqual(sig_rows, {'S1': 2, 'S2': 3})
        self.assertEqual(table.rowCount(), 4)
        self.assertEqual(table.verticalHeaderItem(2).text(), 'S1')
        self.assertEqual(table.item(2, 0).text(), '9')
        self.assertEqual(table.item(3, 0).text(), '-1.5')

    def test_wrapped_signal_name_row_is_taller_in_columns_view(self):
        self.window.clear_info()
        long_label = 'DIAG-MAGNETICS:CURRENT-SENSOR-42'
        self.window.add_row('A', (1, 1), (1.0, 2.0), '#FF0000',
                            signal_values={long_label: 1.0, 'S1': 2.0})
        self.window.columns_radio.setChecked(True)
        _, table, sig_rows = self.window.column_sections[0]
        self.assertIn('\n', IplotQtRuler._wrap_label(long_label))
        self.assertGreater(table.rowHeight(sig_rows[long_label]),
                           table.rowHeight(sig_rows['S1']))

    def test_columns_view_grows_window_to_fit_sections_without_vertical_scroll(self):
        self.window.clear_info()
        for i in range(6):
            self.window.add_row(chr(ord('A') + i), (i, 1), (1.0 + i, 2.0), '#FF0000',
                                signal_values={'S1': 1.0, 'S2': 2.0, 'S3': 3.0})
        self.window.show()
        initial_height = self.window.height()
        self.window.columns_radio.setChecked(True)
        for _ in range(3):  # flush the deferred section fits, then the window fit
            self.app.processEvents()
        self.assertGreater(self.window.height(), initial_height)
        inner = self.window.columns_scroll.widget()
        fits = inner.sizeHint().height() <= self.window.columns_scroll.viewport().height()
        screen = self.window.screen()
        capped = screen is not None and \
            self.window.height() >= screen.availableGeometry().height() - 60
        self.assertTrue(fits or capped)

    def test_delta_in_section_is_consecutive_difference(self):
        self.window.add_row('C', (1, 1), (8.0, 7.0), '#0000FF')
        self.window.columns_radio.setChecked(True)
        _, table, _ = self.window.column_sections[0]
        # Headers: [A, Δ, B, Δ, C]; Δ(B-A) at col 1, Δ(C-B) at col 3.
        self.assertEqual(table.item(0, 1).text(), '2')   # B.x - A.x = 3 - 1
        self.assertEqual(table.item(1, 1).text(), '2')   # B.y - A.y = 4 - 2
        self.assertEqual(table.item(0, 3).text(), '5')   # C.x - B.x = 8 - 3
        self.assertEqual(table.item(1, 3).text(), '3')   # C.y - B.y = 7 - 4

    def test_delta_in_section_covers_signal_values(self):
        self.window.clear_info()
        self.window.add_row('A', (1, 1), (1.0, 2.0), '#FF0000',
                            signal_values={'S1': 9.0, 'S2': 1.0})
        self.window.add_row('B', (1, 1), (3.0, 4.0), '#00FF00',
                            signal_values={'S1': 4.5})
        self.window.columns_radio.setChecked(True)
        _, table, sig_rows = self.window.column_sections[0]
        # Δ column is index 1; S1 delta = 4.5 - 9 = -4.5, S2 has no pair -> blank.
        self.assertEqual(table.item(sig_rows['S1'], 1).text(), '-4.5')
        self.assertEqual(table.item(sig_rows['S2'], 1).text(), '')

    def test_section_columns_are_user_resizable(self):
        self.window.columns_radio.setChecked(True)
        _, table, _ = self.window.column_sections[0]
        header = table.horizontalHeader()
        self.assertEqual(header.sectionResizeMode(0), QHeaderView.ResizeMode.Interactive)

    def test_copy_columns_view_selection_as_tab_separated_text(self):
        self.window.columns_radio.setChecked(True)
        _, table, _ = self.window.column_sections[0]
        table.selectAll()
        self.window._copy_table_selection(table)
        copied = QApplication.clipboard().text()
        self.assertEqual(copied, '1\t2\t3\n2\t2\t4')

    def test_singleton_plot_section_has_no_delta_column(self):
        self.window.remove_row_by_name('B', (1, 1))
        self.window.columns_radio.setChecked(True)
        _, table, _ = self.window.column_sections[0]
        self.assertEqual(table.columnCount(), 1)
        headers = [table.horizontalHeaderItem(c).text() for c in range(table.columnCount())]
        self.assertEqual(headers, ['A'])

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
        self.assertEqual(self.window.table.columnCount(), 8)
        self.assertEqual(self.window.column_sections, [])

    def test_data_survives_mode_switch(self):
        self.window.columns_radio.setChecked(True)
        self.window.rows_radio.setChecked(True)
        cb = self.window.table.cellWidget(0, self.window.COL_VISIBLE)
        btn = self.window.table.cellWidget(0, self.window.COL_COLOR)
        self.assertIsNotNone(cb)
        self.assertIsNotNone(btn)
        self.assertTrue(cb.isChecked())  # Ruler A starts visible

    def test_section_cells_are_tinted_with_ruler_color(self):
        self.window.columns_radio.setChecked(True)
        _, table, _ = self.window.column_sections[0]
        for axis_row in (0, 1):
            bg = table.item(axis_row, 0).background().color()
            self.assertEqual((bg.red(), bg.green(), bg.blue()), (255, 0, 0))
            self.assertLess(bg.alpha(), 255)

    def test_section_cells_are_read_only(self):
        self.window.columns_radio.setChecked(True)
        for _, table, _ in self.window.column_sections:
            for row in range(table.rowCount()):
                for col in range(table.columnCount()):
                    item = table.item(row, col)
                    self.assertFalse(bool(item.flags() & Qt.ItemFlag.ItemIsEditable),
                                     f"Cell ({row},{col}) is editable in columns mode")

    def test_adding_a_ruler_extends_the_existing_section(self):
        self.window.columns_radio.setChecked(True)
        self.window.add_row('C', (1, 1), (5.0, 6.0), '#0000FF')
        self.assertEqual(len(self.window.column_sections), 1)
        _, table, _ = self.window.column_sections[0]
        # 3 rulers + 2 deltas = 5 columns.
        self.assertEqual(table.columnCount(), 5)
        headers = [table.horizontalHeaderItem(c).text() for c in range(table.columnCount())]
        delta = IplotQtRuler._DELTA_HEADER
        self.assertEqual(headers, ['A', delta, 'B', delta, 'C'])

    def test_multiple_plots_produce_one_section_per_plot(self):
        self.window.add_row('C', (2, 1), (10.0, 20.0), '#0000FF')
        self.window.add_row('D', (2, 1), (30.0, 40.0), '#FFFF00')
        self.window.columns_radio.setChecked(True)

        self.assertEqual(len(self.window.column_sections), 2)
        plot_ids = [pid for pid, _, _ in self.window.column_sections]
        self.assertEqual(plot_ids, [(1, 1), (2, 1)])

        _, first, _ = self.window.column_sections[0]
        _, second, _ = self.window.column_sections[1]
        # Δ column lives between the two ruler columns: index 1 in both sections.
        self.assertEqual(first.item(0, 1).text(), '2')     # B.x - A.x = 3 - 1
        self.assertEqual(second.item(0, 1).text(), '20')   # D.x - C.x = 30 - 10

    def test_singleton_plot_section_appears_without_delta_when_other_plot_has_more(self):
        self.window.add_row('C', (2, 1), (10.0, 20.0), '#0000FF')
        self.window.columns_radio.setChecked(True)
        # First section: A, Δ, B. Second section: C only, no Δ.
        _, first, _ = self.window.column_sections[0]
        _, second, _ = self.window.column_sections[1]
        first_headers = [first.horizontalHeaderItem(c).text() for c in range(first.columnCount())]
        second_headers = [second.horizontalHeaderItem(c).text() for c in range(second.columnCount())]
        self.assertEqual(first_headers, ['A', IplotQtRuler._DELTA_HEADER, 'B'])
        self.assertEqual(second_headers, ['C'])


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

            # Default sort orders by Ruler name (A, B, C), so visual rows hold xs [1, 5, 9].
            xs_visual = [window.table.item(r, IplotQtRuler.COL_X).data(Qt.ItemDataRole.UserRole)
                         for r in range(window.table.rowCount())]
            self.assertEqual(xs_visual, [1.0, 5.0, 9.0])

            # The user may sort by any column afterwards (X ascending here).
            window.table.sortItems(IplotQtRuler.COL_X, Qt.SortOrder.AscendingOrder)
            xs_after_sort = [window.table.item(r, IplotQtRuler.COL_X).data(Qt.ItemDataRole.UserRole)
                             for r in range(window.table.rowCount())]
            self.assertEqual(xs_after_sort, [1.0, 5.0, 9.0])
        finally:
            window.close()


class RulerSortPersistenceTest(unittest.TestCase):
    """The table is rebuilt on every ruler update, so the column the user sorted
    by must survive the rebuild, indicator included."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.app = ensure_qapp()

    def setUp(self):
        self.window = IplotQtRuler()
        # Rulers sit on different plots: X must order across plots, not within.
        self.window.add_row('A', (1, 1), (1.0, 0.0), '#FFFFFF')
        self.window.add_row('B', (2, 1), (9.0, 0.0), '#FFFFFF')
        self.window.add_row('C', (1, 1), (5.0, 0.0), '#FFFFFF')

    def tearDown(self):
        self.window.close()

    def _names(self):
        return [self.window.table.item(r, IplotQtRuler.COL_NAME).text()
                for r in range(self.window.table.rowCount())]

    def test_sort_by_x_survives_a_row_update(self):
        self.window.table.sortByColumn(IplotQtRuler.COL_X, Qt.SortOrder.AscendingOrder)
        self.assertEqual(self._names(), ['A', 'C', 'B'])

        self.window.update_row_xy('B', (2, 1), (9.0, 1.0))

        self.assertEqual(self._names(), ['A', 'C', 'B'])
        header = self.window.table.horizontalHeader()
        self.assertEqual(header.sortIndicatorSection(), IplotQtRuler.COL_X)
        self.assertEqual(header.sortIndicatorOrder(), Qt.SortOrder.AscendingOrder)

    def test_sort_by_x_survives_a_new_ruler(self):
        self.window.table.sortByColumn(IplotQtRuler.COL_X, Qt.SortOrder.DescendingOrder)

        self.window.add_row('D', (1, 1), (7.0, 0.0), '#FFFFFF')

        self.assertEqual(self._names(), ['B', 'D', 'C', 'A'])

    def test_default_sort_is_by_ruler_name(self):
        self.assertEqual(self._names(), ['A', 'B', 'C'])


class RulerComputeDistanceDialogTest(unittest.TestCase):
    """Compute distance opens a copyable table with ΔX / ΔY and one Δ column
    per signal; time-axis ΔX carries the statistics-table duration format."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.app = ensure_qapp()

    def setUp(self):
        self.window = IplotQtRuler()

    def tearDown(self):
        if self.window._distance_dialog is not None:
            self.window._distance_dialog.close()
        self.window.close()

    def _distance_between_first_two(self):
        self.window.selection_history = [0, 1]
        self.window._compute_distance()
        return self.window._distance_table

    def test_distance_table_includes_signal_deltas(self):
        self.window.add_row('A', (1, 1), (1.0, 2.0), '#FFFFFF',
                            signal_values={'S1': 10.0, 'S2': 3.0})
        self.window.add_row('B', (1, 1), (5.0, 6.0), '#FFFFFF',
                            signal_values={'S1': 4.0})
        table = self._distance_between_first_two()
        headers = [table.horizontalHeaderItem(c).text() for c in range(table.columnCount())]
        self.assertEqual(headers, ['Rulers', 'ΔX', 'ΔY', 'Δ S1', 'Δ S2'])
        self.assertEqual(table.item(0, 0).text(), 'A → B')
        self.assertEqual(table.item(0, 1).text(), '4')
        self.assertEqual(table.item(0, 2).text(), '4')
        self.assertEqual(table.item(0, 3).text(), '6')
        self.assertEqual(table.item(0, 4).text(), '')  # S2 has no pair

    def test_distance_dialog_skips_hidden_signals(self):
        self.window.add_row('A', (1, 1), (1.0, 2.0), '#FFFFFF',
                            signal_values={'S1': 10.0, 'S2': 3.0})
        self.window.add_row('B', (1, 1), (5.0, 6.0), '#FFFFFF',
                            signal_values={'S1': 4.0, 'S2': 1.0})
        self.window.signals_menu.actions()[1].setChecked(False)  # hide S2
        table = self._distance_between_first_two()
        headers = [table.horizontalHeaderItem(c).text() for c in range(table.columnCount())]
        self.assertEqual(headers, ['Rulers', 'ΔX', 'ΔY', 'Δ S1'])

    def test_date_axis_dx_reads_seconds_with_duration_in_brackets(self):
        # Date axes carry nanoseconds; Δ = 9.5 s.
        self.window.add_row('A', (1, 1), (0.0, 0.0), '#FFFFFF', is_date=True)
        self.window.add_row('B', (1, 1), (9.5e9, 1.0), '#FFFFFF', is_date=True)
        table = self._distance_between_first_two()
        self.assertEqual(table.item(0, 1).text(), '9.5 s (9s500ms)')

    def test_relative_time_axis_dx_reads_seconds_with_duration_in_brackets(self):
        # Relative-time axes carry seconds; Δ = 3661.5 s.
        self.window.add_row('A', (1, 1), (0.0, 0.0), '#FFFFFF', x_is_time=True)
        self.window.add_row('B', (1, 1), (3661.5, 1.0), '#FFFFFF', x_is_time=True)
        table = self._distance_between_first_two()
        self.assertEqual(table.item(0, 1).text(), '3661.5 s (1h1min1s500ms)')

    def test_plain_numeric_axis_dx_stays_a_plain_number(self):
        self.window.add_row('A', (1, 1), (1.0, 0.0), '#FFFFFF')
        self.window.add_row('B', (1, 1), (5.0, 1.0), '#FFFFFF')
        table = self._distance_between_first_two()
        self.assertEqual(table.item(0, 1).text(), '4')

    def test_distance_dialog_copy_includes_headers_and_rows(self):
        self.window.add_row('A', (1, 1), (1.0, 2.0), '#FFFFFF', signal_values={'S1': 10.0})
        self.window.add_row('B', (1, 1), (5.0, 6.0), '#FFFFFF', signal_values={'S1': 4.0})
        table = self._distance_between_first_two()
        self.window._copy_whole_qtable(table)
        lines = QApplication.clipboard().text().split('\n')
        self.assertEqual(lines[0], 'Rulers\tΔX\tΔY\tΔ S1')
        self.assertEqual(lines[1], 'A → B\t4\t4\t6')

    def test_column_view_delta_x_uses_time_format_for_date_axes(self):
        self.window.add_row('A', (1, 1), (0.0, 0.0), '#FFFFFF', is_date=True)
        self.window.add_row('B', (1, 1), (9.5e9, 1.0), '#FFFFFF', is_date=True)
        self.window.columns_radio.setChecked(True)
        _, table, _ = self.window.column_sections[0]
        self.assertEqual(table.item(0, 1).text(), '9.5 s (9s500ms)')


class RulerDistanceFormattingTest(unittest.TestCase):
    """The numeric path (non-datetime) is purely formatting — exercise it directly."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.app = ensure_qapp()

    def test_numeric_dx_is_absolute_and_six_significant_digits(self):
        self.assertEqual(IplotQtRuler._format_dx(1.0, 5.0, is_date=False), '4')
        self.assertEqual(IplotQtRuler._format_dx(5.0, 1.0, is_date=False), '4')
        self.assertEqual(IplotQtRuler._format_dx(1.23456789, 0.0, is_date=False), '1.23457')

    def test_datetime_dx_reads_seconds_with_duration_in_brackets(self):
        one_second_ns = 1_000_000_000
        out = IplotQtRuler._format_dx(0, one_second_ns, is_date=True)
        self.assertEqual(out, "1 s (1s)")

    def test_datetime_dx_with_days_hours_minutes(self):
        one_day_ns = 86_400 * 1_000_000_000
        five_hours_ns = 5 * 3_600 * 1_000_000_000
        out = IplotQtRuler._format_dx(0, one_day_ns + five_hours_ns + 1_000_000_000, is_date=True)
        self.assertEqual(out, "104401 s (1d5h1s)")


if __name__ == '__main__':
    unittest.main()
