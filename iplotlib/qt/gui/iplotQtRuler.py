from string import ascii_uppercase
from typing import Dict, List, Tuple

import pandas as pd
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QCheckBox, QColorDialog, QFrame, QHBoxLayout,
                                QHeaderView, QLabel, QMessageBox, QPushButton, QRadioButton, QScrollArea,
                                QStackedWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

import iplotLogging.setupLogger as Sl

logger = Sl.get_logger(__name__)


class IplotQtRuler(QWidget):
    """Ruler manager window with two layouts: rows (one ruler per row, editable)
    and columns (one ruler per column with X/Y axis rows and Δ, read-only)."""

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

    _COLUMNS_AXIS_LABELS = ['X', 'Y']
    _DELTA_HEADER = 'Δ'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.resize(850, 500)
        self.setWindowTitle("Rulers window")

        self.selection_history: List[int] = []
        self.count = 0
        self.view_mode = self.VIEW_ROWS
        self._rows: List[Dict] = []
        self.canvas_columns: int = 1
        self.column_sections: List[Tuple[Tuple[int, int], QTableWidget]] = []

        self.rows_radio = QRadioButton("Rows")
        self.rows_radio.setToolTip("One row per ruler. Editable.")
        self.rows_radio.setChecked(True)
        self.columns_radio = QRadioButton("Columns")
        self.columns_radio.setToolTip("One section per plot with X / Y values and Δ. Read-only.")
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

        self.columns_scroll = QScrollArea()
        self.columns_scroll.setWidgetResizable(True)
        self.columns_scroll.setFrameShape(QFrame.Shape.NoFrame)
        columns_inner = QWidget()
        self.columns_layout = QVBoxLayout(columns_inner)
        self.columns_layout.setContentsMargins(4, 4, 4, 4)
        self.columns_layout.setSpacing(12)
        self.columns_layout.addStretch()
        self.columns_scroll.setWidget(columns_inner)

        self.view_stack = QStackedWidget()
        self.view_stack.addWidget(self.table)
        self.view_stack.addWidget(self.columns_scroll)

        self.remove_button = QPushButton("Remove ruler")
        self.distance_button = QPushButton("Compute distance")
        self.remove_button.pressed.connect(self._remove_selected)
        self.distance_button.pressed.connect(self._compute_distance)

        main_layout = QVBoxLayout()
        main_layout.addLayout(view_layout)
        main_layout.addWidget(self.view_stack)
        buttons = QHBoxLayout()
        buttons.addWidget(self.remove_button)
        buttons.addWidget(self.distance_button)
        main_layout.addLayout(buttons)
        self.setLayout(main_layout)

        self._render_table()

    def next_name(self) -> str:
        used = {r['name'] for r in self._rows}
        for letter in ascii_uppercase:
            if letter not in used:
                self.count = max(self.count, ascii_uppercase.index(letter) + 1)
                return letter
        # Fallback when all 26 letters are taken.
        name = ascii_uppercase[self.count % len(ascii_uppercase)]
        self.count += 1
        return name

    def next_color(self, name: str = None) -> str:
        if name and name in ascii_uppercase:
            idx = ascii_uppercase.index(name)
            return self.DEFAULT_COLOR_CYCLE[idx % len(self.DEFAULT_COLOR_CYCLE)]
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
        if self.view_mode == self.VIEW_ROWS and self.table.columnCount() == 6:
            row_idx = len(self._rows) - 1
            self.table.insertRow(row_idx)
            self._populate_row_cells(row_idx, self._rows[-1])
        else:
            self._render_table()

    def remove_row_by_name(self, name: str, plot_id):
        target = tuple(plot_id)
        for i, row in enumerate(self._rows):
            if row['name'] == name and row['plot_id'] == target:
                del self._rows[i]
                if self.view_mode == self.VIEW_ROWS:
                    self.table.removeRow(i)
                    self.selection_history = [r if r < i else r - 1
                                              for r in self.selection_history
                                              if r != i]
                else:
                    self._render_table()
                return

    def clear_info(self):
        self._rows.clear()
        self.selection_history.clear()
        self.count = 0
        self._render_table()

    def set_canvas_columns(self, n: int):
        """Inform the window how many columns the canvas grid has so the Plot
        id can be displayed concisely (just the row when there is a single
        column, full row.col when there are several)."""
        n = max(1, int(n))
        if n != self.canvas_columns:
            self.canvas_columns = n
            self._render_table()

    def _format_plot_id(self, plot_id) -> str:
        if self.canvas_columns <= 1:
            return f"{plot_id[0]}"
        return f"{plot_id[0]}.{plot_id[1]}"

    def _on_view_mode_changed(self):
        self.view_mode = self.VIEW_ROWS if self.rows_radio.isChecked() else self.VIEW_COLUMNS
        self.selection_history.clear()
        self._render_table()

    def _render_table(self):
        """Rebuild the active view from ``self._rows``."""
        # selectionChanged would fire spuriously during rebuild; disconnect briefly.
        try:
            self.table.selectionModel().selectionChanged.disconnect(self._update_selection_history)
        except (RuntimeError, TypeError):
            pass

        self.table.clear()
        self.table.setRowCount(0)
        self.table.setColumnCount(0)
        self.table.verticalHeader().setVisible(False)
        self._clear_column_sections()

        if self.view_mode == self.VIEW_ROWS:
            self.view_stack.setCurrentWidget(self.table)
            self._render_rows()
            edit_enabled = True
        else:
            self.view_stack.setCurrentWidget(self.columns_scroll)
            self._render_column_sections()
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

        plot_item = QTableWidgetItem(self._format_plot_id(row['plot_id']))
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

    def _clear_column_sections(self):
        self.column_sections.clear()
        # Remove every widget before the trailing stretch.
        while self.columns_layout.count() > 1:
            item = self.columns_layout.takeAt(0)
            w = item.widget() if item is not None else None
            if w is not None:
                w.deleteLater()

    def _render_column_sections(self):
        groups: Dict[Tuple[int, int], List[Dict]] = {}
        for r in self._rows:
            groups.setdefault(r['plot_id'], []).append(r)

        stretch_idx = self.columns_layout.count() - 1
        for plot_id, rulers in groups.items():
            section, table = self._build_plot_section(plot_id, rulers)
            self.columns_layout.insertWidget(stretch_idx, section)
            stretch_idx += 1
            self.column_sections.append((plot_id, table))

    def _build_plot_section(self, plot_id: Tuple[int, int],
                             rulers: List[Dict]) -> Tuple[QWidget, QTableWidget]:
        section = QWidget()
        layout = QVBoxLayout(section)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        title = QLabel(f"Plot {self._format_plot_id(plot_id)}")
        title.setStyleSheet("font-weight: bold;")
        layout.addWidget(title)

        show_delta = len(rulers) >= 2
        col_count = len(rulers) + (1 if show_delta else 0)

        table = QTableWidget(len(self._COLUMNS_AXIS_LABELS), col_count)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        table.setVerticalHeaderLabels(list(self._COLUMNS_AXIS_LABELS))

        headers = [str(i + 1) for i in range(len(rulers))]
        if show_delta:
            headers.append(self._DELTA_HEADER)
        table.setHorizontalHeaderLabels(headers)
        h_header = table.horizontalHeader()
        h_header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        h_header.setStretchLastSection(True)

        for col_idx, r in enumerate(rulers):
            self._set_axis_cell(table, 0, col_idx, self._format_x(r), r['color'])
            self._set_axis_cell(table, 1, col_idx, f"{r['xy'][1]:.6g}", r['color'])

        if show_delta:
            xs = [r['xy'][0] for r in rulers]
            ys = [r['xy'][1] for r in rulers]
            is_date = rulers[0]['is_date']
            self._set_plain_cell(table, 0, col_count - 1,
                                 self._format_dx(min(xs), max(xs), is_date))
            self._set_plain_cell(table, 1, col_count - 1, f"{max(ys) - min(ys):.6g}")

        table.setFixedHeight(self._section_table_height(table))
        layout.addWidget(table)
        return section, table

    @staticmethod
    def _section_table_height(table: QTableWidget) -> int:
        rows_height = sum(table.rowHeight(r) for r in range(table.rowCount()))
        frame = 2 * table.frameWidth()
        return table.horizontalHeader().height() + rows_height + frame

    @staticmethod
    def _format_x(row: Dict) -> str:
        x = row['xy'][0]
        return str(pd.Timestamp(x)) if row['is_date'] else f"{x:.6g}"

    @staticmethod
    def _set_axis_cell(table: QTableWidget, axis_row: int, col_idx: int, text: str, color: str):
        item = QTableWidgetItem(text)
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        tint = QColor(color)
        tint.setAlpha(60)
        item.setBackground(QBrush(tint))
        table.setItem(axis_row, col_idx, item)

    @staticmethod
    def _set_plain_cell(table: QTableWidget, axis_row: int, col_idx: int, text: str):
        item = QTableWidgetItem(text)
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        table.setItem(axis_row, col_idx, item)

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
        c = dx.components
        sub_ns = c.milliseconds * 1_000_000 + c.microseconds * 1_000 + c.nanoseconds
        parts = []
        if c.days:
            parts.append(f"{c.days}d")
        if c.hours or parts:
            parts.append(f"{c.hours:02d}h")
        if c.minutes or parts:
            parts.append(f"{c.minutes:02d}m")
        seconds = c.seconds + sub_ns / 1_000_000_000
        parts.append(f"{seconds:09.6f}s" if parts else f"{seconds:.6f}s")
        return " ".join(parts)

    def _warn(self, msg: str):
        box = QMessageBox()
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Rulers")
        box.setText(msg)
        logger.warning(msg)
        box.exec_()
