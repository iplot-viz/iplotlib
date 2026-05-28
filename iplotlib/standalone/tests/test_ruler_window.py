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
