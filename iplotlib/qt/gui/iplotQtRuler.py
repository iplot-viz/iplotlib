from string import ascii_uppercase

import pandas as pd
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QColorDialog, QHBoxLayout, QHeaderView, QMessageBox,
                                QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

import iplotLogging.setupLogger as Sl

logger = Sl.get_logger(__name__)


class IplotQtRuler(QWidget):
    """Ruler manager window. Lists rulers per plot with X/Y values, color and deltas."""

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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.resize(850, 500)
        self.setWindowTitle("Rulers window")

        self.selection_history = []
        self.count = 0

        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(['Ruler', 'Plot', 'X value', 'Y value', 'Visible', 'Color'])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setStretchLastSection(True)

        self.table.selectionModel().selectionChanged.connect(self._update_selection_history)

        self.remove_button = QPushButton("Remove ruler")
        self.distance_button = QPushButton("Compute distance")
        self.remove_button.pressed.connect(self._remove_selected)
        self.distance_button.pressed.connect(self._compute_distance)

        main_layout = QVBoxLayout()
        main_layout.addWidget(self.table)
        buttons = QHBoxLayout()
        buttons.addWidget(self.remove_button)
        buttons.addWidget(self.distance_button)
        main_layout.addLayout(buttons)
        self.setLayout(main_layout)

    def next_name(self) -> str:
        name = ascii_uppercase[self.count % len(ascii_uppercase)]
        self.count += 1
        return name

    def next_color(self) -> str:
        return self.DEFAULT_COLOR_CYCLE[(self.count - 1) % len(self.DEFAULT_COLOR_CYCLE)] \
            if self.count > 0 else self.DEFAULT_COLOR_CYCLE[0]

    def add_row(self, name: str, plot_id, xy, color: str, visible: bool = True, is_date: bool = False):
        row = self.table.rowCount()
        self.table.insertRow(row)

        name_item = QTableWidgetItem(name)
        name_item.setData(Qt.ItemDataRole.UserRole, is_date)
        self.table.setItem(row, self.COL_NAME, name_item)

        plot_item = QTableWidgetItem(f"{plot_id[0]}.{plot_id[1]}")
        plot_item.setData(Qt.ItemDataRole.UserRole, plot_id)
        self.table.setItem(row, self.COL_PLOT, plot_item)

        x_text = str(pd.Timestamp(xy[0])) if is_date else f"{xy[0]:.6g}"
        x_item = QTableWidgetItem(x_text)
        x_item.setData(Qt.ItemDataRole.UserRole, xy[0])
        self.table.setItem(row, self.COL_X, x_item)

        y_item = QTableWidgetItem(f"{xy[1]:.6g}")
        y_item.setData(Qt.ItemDataRole.UserRole, xy[1])
        self.table.setItem(row, self.COL_Y, y_item)

        visible_cb = QCheckBox()
        visible_cb.setChecked(visible)
        visible_cb.stateChanged.connect(
            lambda state, cb=visible_cb: self._on_visibility_changed(self.table.indexAt(cb.pos()).row(), state))
        self.table.setCellWidget(row, self.COL_VISIBLE, visible_cb)

        color_btn = QPushButton("Select color")
        color_btn.setStyleSheet(f"background-color: {color}; border: 1px solid black")
        color_btn.clicked.connect(
            lambda _=False, btn=color_btn: self._on_color_clicked(self.table.indexAt(btn.pos()).row(), btn))
        self.table.setCellWidget(row, self.COL_COLOR, color_btn)

    def remove_row_by_name(self, name: str, plot_id):
        target = tuple(plot_id)
        for row in range(self.table.rowCount()):
            stored = self.table.item(row, self.COL_PLOT).data(Qt.ItemDataRole.UserRole)
            if self.table.item(row, self.COL_NAME).text() == name and tuple(stored) == target:
                self.table.removeRow(row)
                return

    def clear_info(self):
        self.table.setRowCount(0)
        self.selection_history.clear()
        self.count = 0

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
        self.visibilityRuler.emit(name, plot_id, visible)

    def _on_color_clicked(self, row: int, button: QPushButton):
        current = button.palette().button().color()
        new_color = QColorDialog.getColor(current, self)
        if not new_color.isValid():
            return
        color = new_color.name()
        button.setStyleSheet(f"background-color: {color}; border: 1px solid black")
        name, plot_id = self._row_metadata(row)
        self.colorRuler.emit(name, plot_id, color)

    def _remove_selected(self):
        for row in sorted(self.selection_history, reverse=True):
            name, plot_id = self._row_metadata(row)
            self.deleteRuler.emit(name, plot_id, True)
            self.table.removeRow(row)
        self.selection_history.clear()

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
