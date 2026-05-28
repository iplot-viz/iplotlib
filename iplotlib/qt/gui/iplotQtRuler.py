from string import ascii_uppercase
from typing import Dict, List, Tuple

import pandas as pd
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QCheckBox, QColorDialog, QHBoxLayout, QHeaderView,
                                QLabel, QMessageBox, QPushButton, QRadioButton, QTableWidget, QTableWidgetItem,
                                QVBoxLayout, QWidget)

import iplotLogging.setupLogger as Sl

logger = Sl.get_logger(__name__)


class IplotQtRuler(QWidget):
    """Ruler manager window. Lists rulers per plot with X/Y values, color and deltas.

    Two view modes:
      * ``rows`` (default): one row per ruler, fully editable.
      * ``columns``: one column per ruler, read-only — for side-by-side comparison.
    """

    deleteRuler = Signal(object, object, object)               # name, plot_id, persist
    visibilityRuler = Signal(object, object, bool)             # name, plot_id, visible
    colorRuler = Signal(object, object, object)                # name, plot_id, color

    COL_NAME = 0
    COL_PLOT = 1
    COL_X = 2
    COL_Y = 3
    COL_VISIBLE = 4
    COL_COLOR = 5

    DEFAULT_COLOR_CYCLE = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd', '#8c564b',
                            '#e377c2', '#7f7f7f', '#bcbd22', '#17becf']

    VIEW_ROWS = 'rows'
    VIEW_COLUMNS = 'columns'

    # Vertical header labels for columns mode, in display order.
    _COLUMNS_MODE_FIELDS = ['Plot', 'X value', 'Y value', 'Visible', 'Color']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.resize(850, 500)
        self.setWindowTitle("Rulers window")

        self.selection_history: List[int] = []
        self.count = 0
        self.view_mode = self.VIEW_ROWS
        self._rows: List[Dict] = []

        self.rows_radio = QRadioButton("Rows")
        self.rows_radio.setToolTip("One row per ruler. Editable.")
        self.rows_radio.setChecked(True)
        self.columns_radio = QRadioButton("Columns")
        self.columns_radio.setToolTip("One column per ruler. Display only — for side-by-side comparison.")
        view_group = QButtonGroup(self)
        view_group.addButton(self.rows_radio)
        view_group.addButton(self.columns_radio)
        self.rows_radio.toggled.connect(self._on_view_mode_changed)

        view_layout = QHBoxLayout()
        view_layout.addWidget(QLabel("Layout:"))
        view_layout.addWidget(self.rows_radio)
        view_layout.addWidget(self.columns_radio)
        view_layout.addStretch()

        self.table = QTableWidget()
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.selectionModel().selectionChanged.connect(self._update_selection_history)

        self.remove_button = QPushButton("Remove ruler")
        self.distance_button = QPushButton("Compute distance")
        self.remove_button.pressed.connect(self._remove_selected)
        self.distance_button.pressed.connect(self._compute_distance)

        main_layout = QVBoxLayout()
        main_layout.addLayout(view_layout)
        main_layout.addWidget(self.table)
        buttons = QHBoxLayout()
        buttons.addWidget(self.remove_button)
        buttons.addWidget(self.distance_button)
        main_layout.addLayout(buttons)
        self.setLayout(main_layout)

        self._render_table()

    def next_name(self) -> str:
        name = ascii_uppercase[self.count % len(ascii_uppercase)]
        self.count += 1
        return name

    def next_color(self) -> str:
        return self.DEFAULT_COLOR_CYCLE[(self.count - 1) % len(self.DEFAULT_COLOR_CYCLE)] \
            if self.count > 0 else self.DEFAULT_COLOR_CYCLE[0]

    def add_row(self, name: str, plot_id, xy: Tuple[float, float], color: str,
                visible: bool = True, is_date: bool = False):
        self._rows.append({
            'name': name,
            'plot_id': tuple(plot_id),
            'xy': (xy[0], xy[1]),
            'color': color,
            'visible': visible,
            'is_date': is_date,
        })
        self._render_table()

    def remove_row_by_name(self, name: str, plot_id):
        target = tuple(plot_id)
        for i, row in enumerate(self._rows):
            if row['name'] == name and row['plot_id'] == target:
                del self._rows[i]
                self._render_table()
                return

    def clear_info(self):
        self._rows.clear()
        self.selection_history.clear()
        self.count = 0
        self._render_table()

    # View-mode plumbing
    def _on_view_mode_changed(self):
        self.view_mode = self.VIEW_ROWS if self.rows_radio.isChecked() else self.VIEW_COLUMNS
        self.selection_history.clear()
        self._render_table()

    def _render_table(self):
        """Rebuild the QTableWidget from ``self._rows`` according to the current view mode."""
        # selectionChanged would fire spuriously during rebuild; disconnect briefly.
        try:
            self.table.selectionModel().selectionChanged.disconnect(self._update_selection_history)
        except (RuntimeError, TypeError):
            pass

        self.table.clear()
        self.table.setRowCount(0)
        self.table.setColumnCount(0)
        self.table.verticalHeader().setVisible(self.view_mode == self.VIEW_COLUMNS)

        if self.view_mode == self.VIEW_ROWS:
            self._render_rows()
            edit_enabled = True
        else:
            self._render_columns()
            edit_enabled = False

        self.remove_button.setEnabled(edit_enabled)
        self.distance_button.setEnabled(edit_enabled)

        self.table.selectionModel().selectionChanged.connect(self._update_selection_history)

    def _render_rows(self):
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(['Ruler', 'Plot', 'X value', 'Y value', 'Visible', 'Color'])
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setStretchLastSection(True)

        for row_idx, row in enumerate(self._rows):
            self.table.insertRow(row_idx)
            self._populate_row_cells(row_idx, row)

    def _populate_row_cells(self, row_idx: int, row: Dict):
        name_item = QTableWidgetItem(row['name'])
        name_item.setData(Qt.ItemDataRole.UserRole, row['is_date'])
        self.table.setItem(row_idx, self.COL_NAME, name_item)

        plot_item = QTableWidgetItem(f"{row['plot_id'][0]}.{row['plot_id'][1]}")
        plot_item.setData(Qt.ItemDataRole.UserRole, row['plot_id'])
        self.table.setItem(row_idx, self.COL_PLOT, plot_item)

        x, y = row['xy']
        x_text = str(pd.Timestamp(x)) if row['is_date'] else f"{x:.6g}"
        x_item = QTableWidgetItem(x_text)
        x_item.setData(Qt.ItemDataRole.UserRole, x)
        self.table.setItem(row_idx, self.COL_X, x_item)

        y_item = QTableWidgetItem(f"{y:.6g}")
        y_item.setData(Qt.ItemDataRole.UserRole, y)
        self.table.setItem(row_idx, self.COL_Y, y_item)

        visible_cb = QCheckBox()
        visible_cb.setChecked(row['visible'])
        visible_cb.stateChanged.connect(
            lambda state, cb=visible_cb: self._on_visibility_changed(self.table.indexAt(cb.pos()).row(), state))
        self.table.setCellWidget(row_idx, self.COL_VISIBLE, visible_cb)

        color_btn = QPushButton("Select color")
        color_btn.setStyleSheet(f"background-color: {row['color']}; border: 1px solid black")
        color_btn.clicked.connect(
            lambda _=False, btn=color_btn: self._on_color_clicked(self.table.indexAt(btn.pos()).row(), btn))
        self.table.setCellWidget(row_idx, self.COL_COLOR, color_btn)

    def _render_columns(self):
        self.table.setRowCount(len(self._COLUMNS_MODE_FIELDS))
        self.table.setColumnCount(len(self._rows))
        self.table.setVerticalHeaderLabels(self._COLUMNS_MODE_FIELDS)
        self.table.setHorizontalHeaderLabels([row['name'] for row in self._rows])

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setStretchLastSection(True)

        for col_idx, row in enumerate(self._rows):
            self._populate_column_cells(col_idx, row)

    def _populate_column_cells(self, col_idx: int, row: Dict):
        x, y = row['xy']
        x_text = str(pd.Timestamp(x)) if row['is_date'] else f"{x:.6g}"

        values = [
            f"{row['plot_id'][0]}.{row['plot_id'][1]}",
            x_text,
            f"{y:.6g}",
            "Yes" if row['visible'] else "No",
            row['color'],
        ]

        for field_idx, text in enumerate(values):
            item = QTableWidgetItem(text)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(field_idx, col_idx, item)

        # Paint the color cell with the ruler color as background so users can
        # eyeball it without parsing the hex value.
        color_cell = self.table.item(self._COLUMNS_MODE_FIELDS.index('Color'), col_idx)
        qcolor = QColor(row['color'])
        color_cell.setBackground(QBrush(qcolor))
        color_cell.setForeground(QBrush(self._contrast_text_color(qcolor)))

    @staticmethod
    def _contrast_text_color(color: QColor) -> QColor:
        # Pick black or white text depending on the cell background luminance,
        # so the hex code stays readable on any palette entry.
        luminance = 0.299 * color.red() + 0.587 * color.green() + 0.114 * color.blue()
        return QColor('black') if luminance > 140 else QColor('white')

    # Selection-based actions (rows mode only)

    def _update_selection_history(self):
        selected = [idx.row() for idx in self.table.selectionModel().selectedRows()]
        for row in selected:
            if row not in self.selection_history:
                self.selection_history.append(row)
        self.selection_history = [row for row in self.selection_history if row in selected]

    def _row_metadata(self, row: int):
        name = self.table.item(row, self.COL_NAME).text()
        plot_id = self.table.item(row, self.COL_PLOT).data(Qt.ItemDataRole.UserRole)
        # Qt may demote tuples to lists when stored as UserRole data; normalize.
        return name, tuple(plot_id)

    def _on_visibility_changed(self, row: int, state):
        visible = state == Qt.CheckState.Checked.value
        name, plot_id = self._row_metadata(row)
        if 0 <= row < len(self._rows):
            self._rows[row]['visible'] = visible
        self.visibilityRuler.emit(name, plot_id, visible)

    def _on_color_clicked(self, row: int, button: QPushButton):
        current = button.palette().button().color()
        new_color = QColorDialog.getColor(current, self)
        if not new_color.isValid():
            return
        color = new_color.name()
        button.setStyleSheet(f"background-color: {color}; border: 1px solid black")
        name, plot_id = self._row_metadata(row)
        if 0 <= row < len(self._rows):
            self._rows[row]['color'] = color
        self.colorRuler.emit(name, plot_id, color)

    def _remove_selected(self):
        for row in sorted(self.selection_history, reverse=True):
            name, plot_id = self._row_metadata(row)
            self.deleteRuler.emit(name, plot_id, True)
            del self._rows[row]
        self.selection_history.clear()
        self._render_table()

    def _compute_distance(self):
        if len(self.selection_history) < 2:
            self._warn("Select at least 2 rulers to compute deltas.")
            return

        rows = list(self.selection_history)
        plot_id = tuple(self.table.item(rows[0], self.COL_PLOT).data(Qt.ItemDataRole.UserRole))
        if any(tuple(self.table.item(r, self.COL_PLOT).data(Qt.ItemDataRole.UserRole)) != plot_id for r in rows):
            self._warn("All selected rulers must belong to the same plot.")
            return

        rows.sort(key=lambda r: self.table.item(r, self.COL_X).data(Qt.ItemDataRole.UserRole))

        is_date = self.table.item(rows[0], self.COL_NAME).data(Qt.ItemDataRole.UserRole)
        lines = []
        for r1, r2 in zip(rows[:-1], rows[1:]):
            n1 = self.table.item(r1, self.COL_NAME).text()
            n2 = self.table.item(r2, self.COL_NAME).text()
            x1 = self.table.item(r1, self.COL_X).data(Qt.ItemDataRole.UserRole)
            x2 = self.table.item(r2, self.COL_X).data(Qt.ItemDataRole.UserRole)
            y1 = self.table.item(r1, self.COL_Y).data(Qt.ItemDataRole.UserRole)
            y2 = self.table.item(r2, self.COL_Y).data(Qt.ItemDataRole.UserRole)
            dx_str = self._format_dx(x1, x2, is_date)
            dy = abs(y2 - y1)
            lines.append(f"{n1} -> {n2}: dx = {dx_str}, dy = {dy:.6g}")

        box = QMessageBox()
        box.setIcon(QMessageBox.Icon.Information)
        box.setWindowTitle("Ruler deltas")
        box.setText("\n".join(lines))
        logger.info("\n".join(lines))
        box.exec_()

    @staticmethod
    def _format_dx(x1, x2, is_date: bool) -> str:
        if not is_date:
            return f"{abs(x2 - x1):.6g}"
        dx = abs(pd.Timestamp(x2, unit='ns') - pd.Timestamp(x1, unit='ns'))
        parts = []
        if dx.components.days:
            parts.append(f"{dx.components.days}D")
        parts.append(f"T{dx.components.hours}H{dx.components.minutes}M{dx.components.seconds}S")
        if dx.components.milliseconds:
            parts.append(f"+{dx.components.milliseconds}m")
        if dx.components.microseconds:
            parts.append(f"+{dx.components.microseconds}u")
        if dx.components.nanoseconds:
            parts.append(f"+{dx.components.nanoseconds}n")
        return "".join(parts)

    def _warn(self, msg: str):
        box = QMessageBox()
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Rulers")
        box.setText(msg)
        logger.warning(msg)
        box.exec_()
