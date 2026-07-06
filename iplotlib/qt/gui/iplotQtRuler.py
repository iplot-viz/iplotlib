from string import ascii_uppercase
from typing import Dict, List, Tuple

import pandas as pd
from PySide6.QtCore import QEvent, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QBrush, QColor, QKeySequence, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QButtonGroup, QCheckBox, QColorDialog, QComboBox,
                                QFrame, QHBoxLayout, QHeaderView, QLabel, QMessageBox, QPushButton, QRadioButton,
                                QScrollArea, QStackedWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

import iplotLogging.setupLogger as Sl
from iplotlib.core.plot import PlotXY
from iplotlib.core.ruler import Ruler, contrast_text_color

logger = Sl.get_logger(__name__)


class _NumericTableItem(QTableWidgetItem):
    """Sort by the numeric value stored as UserRole, not by the displayed text."""

    def __lt__(self, other):
        a = self.data(Qt.ItemDataRole.UserRole)
        b = other.data(Qt.ItemDataRole.UserRole)
        if a is None or b is None:
            return super().__lt__(other)
        return a < b


class _CheckableComboBox(QComboBox):
    """Combo box whose items carry independent check marks. The popup stays open
    while toggling and the (read-only) field summarises the checked items."""

    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setModel(QStandardItemModel(self))
        self.setEditable(True)
        self.lineEdit().setReadOnly(True)
        self.view().viewport().installEventFilter(self)
        # Open the popup from a click on the field, not only on the arrow.
        self.lineEdit().installEventFilter(self)

    def add_checkable_item(self, text: str, checked: bool):
        item = QStandardItem(text)
        item.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
        item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        self.model().appendRow(item)
        self._update_text()

    def checked_flags(self) -> List[bool]:
        model = self.model()
        return [model.item(i).checkState() == Qt.CheckState.Checked
                for i in range(model.rowCount())]

    def set_checked(self, index: int, checked: bool):
        item = self.model().item(index)
        if item is None:
            return
        item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        self._update_text()
        self.changed.emit()

    def eventFilter(self, obj, event):
        if obj is self.lineEdit() and event.type() == QEvent.Type.MouseButtonPress:
            self.showPopup()
            return True
        # Toggle the item under the cursor in place of the default select-and-close,
        # so several options can be checked without reopening the popup.
        if obj is self.view().viewport() and event.type() == QEvent.Type.MouseButtonRelease:
            index = self.view().indexAt(event.position().toPoint())
            if index.isValid():
                item = self.model().itemFromIndex(index)
                self.set_checked(index.row(), item.checkState() != Qt.CheckState.Checked)
                return True
        return super().eventFilter(obj, event)

    def _update_text(self):
        model = self.model()
        count = model.rowCount()
        checked = [model.item(i).text() for i in range(count)
                   if model.item(i).checkState() == Qt.CheckState.Checked]
        if not checked:
            text = "None"
        elif len(checked) == count:
            text = "All"
        else:
            text = ", ".join(checked)
        self.lineEdit().setText(text)


class IplotQtRuler(QWidget):
    """Ruler manager window with two layouts: rows (one ruler per row, editable)
    and columns (one ruler per column with X/Y axis rows and Δ, read-only)."""

    deleteRuler = Signal(object, object, object)               # name, plot_id, persist
    visibilityRuler = Signal(object, object, bool)             # name, plot_id, visible
    colorRuler = Signal(object, object, object)                # name, plot_id, color
    fontColorRuler = Signal(object, object, object)            # name, plot_id, color
    labelVisibilityRuler = Signal(object, object, bool, bool)  # name, plot_id, show_label, show_val_label

    COL_NAME = 0
    COL_PLOT = 1
    COL_X = 2
    COL_Y = 3
    COL_VISIBLE = 4
    COL_LABEL = 5
    COL_COLOR = 6
    COL_FONT_COLOR = 7

    # Independent toggles shown in the Labels column, in check order.
    LABEL_TOGGLES = ['Ruler label', 'Val label']

    # Signal palette reversed so a ruler rarely matches the signals it crosses.
    DEFAULT_COLOR_CYCLE = list(reversed(PlotXY._color_cycle))

    VIEW_ROWS = 'rows'
    VIEW_COLUMNS = 'columns'

    _COLUMNS_AXIS_LABELS = ['X', 'Y']
    _DELTA_HEADER = 'Δ'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.resize(850, 500)
        self.setWindowTitle("Rulers window")
        # Add minimize/maximize controls to the window.
        self.setWindowFlags(self.windowFlags()
                            | Qt.WindowMinimizeButtonHint
                            | Qt.WindowMaximizeButtonHint)

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
        self._install_copy_action(self.table)

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
                visible: bool = True, is_date: bool = False,
                font_color: str = Ruler.font_color, show_label: bool = True,
                show_val_label: bool = True):
        self._rows.append({
            'name': name,
            'plot_id': tuple(plot_id),
            'xy': (xy[0], xy[1]),
            'color': color,
            'visible': visible,
            'is_date': is_date,
            'font_color': font_color,
            'show_label': show_label,
            'show_val_label': show_val_label,
        })
        # Sorting must be off during insertion; re-render to handle both modes uniformly.
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

    def update_row_xy(self, name: str, plot_id, xy: Tuple[float, float]):
        """Update a ruler row's (x, y) after it is dragged on the canvas."""
        target = tuple(plot_id)
        for row in self._rows:
            if row['name'] == name and row['plot_id'] == target:
                row['xy'] = (xy[0], xy[1])
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
        self.table.setSortingEnabled(False)
        self.table.setColumnCount(8)
        self.table.setHorizontalHeaderLabels(['Ruler', 'Plot', 'X value', 'Y value',
                                              'Visible', 'Labels', 'Color', 'Font color'])
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(False)

        for row_idx, row in enumerate(self._rows):
            self.table.insertRow(row_idx)
            self._populate_row_cells(row_idx, row)

        self.table.resizeColumnsToContents()
        # Add padding so the sort-indicator arrow does not clip the header text.
        sort_arrow_pad = 24
        for col in range(self.table.columnCount()):
            self.table.setColumnWidth(col, self.table.columnWidth(col) + sort_arrow_pad)
        self.table.setSortingEnabled(True)
        self.table.sortItems(self.COL_NAME, Qt.SortOrder.AscendingOrder)

    def _populate_row_cells(self, row_idx: int, row: Dict):
        name_item = QTableWidgetItem(row['name'])
        name_item.setData(Qt.ItemDataRole.UserRole, row['is_date'])
        self.table.setItem(row_idx, self.COL_NAME, name_item)

        plot_item = QTableWidgetItem(self._format_plot_id(row['plot_id']))
        plot_item.setData(Qt.ItemDataRole.UserRole, row['plot_id'])
        self.table.setItem(row_idx, self.COL_PLOT, plot_item)

        x, y = row['xy']
        x_text = str(pd.Timestamp(x)) if row['is_date'] else f"{x:.6g}"
        x_item = _NumericTableItem(x_text)
        x_item.setData(Qt.ItemDataRole.UserRole, x)
        self.table.setItem(row_idx, self.COL_X, x_item)

        y_item = _NumericTableItem(f"{y:.6g}")
        y_item.setData(Qt.ItemDataRole.UserRole, y)
        self.table.setItem(row_idx, self.COL_Y, y_item)

        visible_cb = QCheckBox()
        visible_cb.setChecked(row['visible'])
        visible_cb.stateChanged.connect(
            lambda state, cb=visible_cb: self._on_visibility_changed(self.table.indexAt(cb.pos()).row(), state))
        self.table.setCellWidget(row_idx, self.COL_VISIBLE, visible_cb)

        label_combo = _CheckableComboBox()
        label_combo.add_checkable_item(self.LABEL_TOGGLES[0], row['show_label'])
        label_combo.add_checkable_item(self.LABEL_TOGGLES[1], row['show_val_label'])
        label_combo.changed.connect(
            lambda cb=label_combo: self._on_label_mode_changed(self.table.indexAt(cb.pos()).row(), cb))
        self.table.setCellWidget(row_idx, self.COL_LABEL, label_combo)

        color_btn = self._make_color_button(row['color'], self._on_color_clicked)
        self.table.setCellWidget(row_idx, self.COL_COLOR, color_btn)

        font_btn = self._make_color_button(row['font_color'], self._on_font_color_clicked)
        self.table.setCellWidget(row_idx, self.COL_FONT_COLOR, font_btn)

    def _make_color_button(self, color: str, on_click) -> QPushButton:
        btn = QPushButton("Select color")
        self._paint_color_button(btn, color)
        btn.clicked.connect(
            lambda _=False, b=btn: on_click(self.table.indexAt(b.pos()).row(), b))
        return btn

    @staticmethod
    def _contrast_text_color(color: str) -> str:
        """Black label on light backgrounds, white on dark ones (YIQ luminance)."""
        c = QColor(color)
        return contrast_text_color((c.red(), c.green(), c.blue()))

    @classmethod
    def _paint_color_button(cls, button: QPushButton, color: str):
        text = cls._contrast_text_color(color)
        button.setStyleSheet(f"background-color: {color}; color: {text}; border: 1px solid black")
        # The stylesheet cannot be read back; keep the color for clipboard export.
        button.setProperty('color', color)

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
        for plot_id in sorted(groups.keys()):
            # Columns read left-to-right by ascending X so the Δ between neighbours is meaningful.
            rulers = sorted(groups[plot_id], key=lambda r: r['xy'][0])
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

        n_deltas = max(0, len(rulers) - 1)
        col_count = len(rulers) + n_deltas

        table = QTableWidget(len(self._COLUMNS_AXIS_LABELS), col_count)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        table.setVerticalHeaderLabels(list(self._COLUMNS_AXIS_LABELS))
        self._install_copy_action(table)

        headers = []
        for i, r in enumerate(rulers):
            if i > 0:
                headers.append(self._DELTA_HEADER)
            headers.append(r['name'])
        table.setHorizontalHeaderLabels(headers)
        h_header = table.horizontalHeader()
        h_header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        h_header.setStretchLastSection(False)

        col_idx = 0
        for i, r in enumerate(rulers):
            if i > 0:
                prev = rulers[i - 1]
                is_date = prev['is_date']
                self._set_plain_cell(table, 0, col_idx,
                                     self._format_consecutive_dx(prev['xy'][0], r['xy'][0], is_date))
                self._set_plain_cell(table, 1, col_idx, f"{r['xy'][1] - prev['xy'][1]:.6g}")
                col_idx += 1
            self._set_axis_cell(table, 0, col_idx, self._format_x(r), r['color'])
            self._set_axis_cell(table, 1, col_idx, f"{r['xy'][1]:.6g}", r['color'])
            col_idx += 1

        table.resizeColumnsToContents()
        table.setFixedHeight(self._section_table_height(table))
        layout.addWidget(table)
        # A horizontal scrollbar (shown when a plot has many ruler columns) would
        # overlap the Y row; grow the fixed height by it once the layout has
        # settled and the scrollbar's visibility is known.
        QTimer.singleShot(0, lambda: self._fit_section_height(table))
        return section, table

    def _fit_section_height(self, table: QTableWidget):
        try:
            scrollbar = table.horizontalScrollBar()
            extra = scrollbar.height() if scrollbar.isVisible() else 0
            table.setFixedHeight(self._section_table_height(table) + extra)
        except RuntimeError:
            pass  # table destroyed by a re-render before the timer fired

    def resizeEvent(self, event):
        # Shrinking the window can bring up a section's horizontal scrollbar, which
        # would otherwise overlap the Y row; re-fit each section to its new width.
        super().resizeEvent(event)
        if self.view_mode == self.VIEW_COLUMNS:
            for _, table in self.column_sections:
                self._fit_section_height(table)

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

    def _install_copy_action(self, table: QTableWidget):
        """Ctrl+C / context-menu copy of the selection as tab-separated text."""
        action = QAction("Copy", table)
        action.setShortcut(QKeySequence.StandardKey.Copy)
        action.setShortcutContext(Qt.ShortcutContext.WidgetShortcut)
        action.triggered.connect(lambda: self._copy_table_selection(table))
        table.addAction(action)
        table.setContextMenuPolicy(Qt.ContextMenuPolicy.ActionsContextMenu)

    def _copy_table_selection(self, table: QTableWidget):
        indexes = table.selectedIndexes()
        if not indexes:
            return
        rows = sorted({i.row() for i in indexes})
        cols = sorted({i.column() for i in indexes})
        lines = ['\t'.join(self._cell_text(table, r, c) for c in cols) for r in rows]
        QApplication.clipboard().setText('\n'.join(lines))

    @staticmethod
    def _cell_text(table: QTableWidget, row: int, col: int) -> str:
        item = table.item(row, col)
        if item is not None:
            return item.text()
        widget = table.cellWidget(row, col)
        if isinstance(widget, QCheckBox):
            return str(widget.isChecked()).lower()
        if isinstance(widget, QComboBox):
            return widget.currentText()
        if isinstance(widget, QPushButton):
            return widget.property('color') or ''
        return ''

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

    def _find_row_index(self, name: str, plot_id: Tuple[int, int]) -> int:
        for idx, r in enumerate(self._rows):
            if r['name'] == name and r['plot_id'] == plot_id:
                return idx
        return -1

    def _on_visibility_changed(self, row: int, state):
        visible = state == Qt.CheckState.Checked.value
        name, plot_id = self._row_metadata(row)
        idx = self._find_row_index(name, plot_id)
        if idx >= 0:
            self._rows[idx]['visible'] = visible
        self.visibilityRuler.emit(name, plot_id, visible)

    def _on_label_mode_changed(self, row: int, combo: '_CheckableComboBox'):
        show_label, show_val_label = combo.checked_flags()
        name, plot_id = self._row_metadata(row)
        idx = self._find_row_index(name, plot_id)
        if idx >= 0:
            self._rows[idx]['show_label'] = show_label
            self._rows[idx]['show_val_label'] = show_val_label
        self.labelVisibilityRuler.emit(name, plot_id, show_label, show_val_label)

    def _on_color_clicked(self, row: int, button: QPushButton):
        self._pick_color(row, button, 'color', self.colorRuler)

    def _on_font_color_clicked(self, row: int, button: QPushButton):
        self._pick_color(row, button, 'font_color', self.fontColorRuler)

    def _pick_color(self, row: int, button: QPushButton, key: str, signal):
        current = button.palette().button().color()
        new_color = QColorDialog.getColor(current, self)
        if not new_color.isValid():
            return
        color = new_color.name()
        self._paint_color_button(button, color)
        name, plot_id = self._row_metadata(row)
        idx = self._find_row_index(name, plot_id)
        if idx >= 0:
            self._rows[idx][key] = color
        signal.emit(name, plot_id, color)

    def _remove_selected(self):
        # Resolve identities BEFORE deletion so visual rows stay valid until we drop them.
        identities = [self._row_metadata(row) for row in self.selection_history]
        for name, plot_id in identities:
            self.deleteRuler.emit(name, plot_id, True)
            idx = self._find_row_index(name, plot_id)
            if idx >= 0:
                del self._rows[idx]
        self.selection_history.clear()
        self._render_table()

    def _compute_distance(self):
        if len(self.selection_history) < 2:
            self._warn("Select at least 2 rulers to compute deltas.")
            return

        # Deltas span plots too (e.g. two stacked plots sharing the time axis):
        # dx is the time distance between rulers, dy the value difference.
        rows = list(self.selection_history)
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

    @classmethod
    def _format_consecutive_dx(cls, x_prev, x_curr, is_date: bool) -> str:
        if not is_date:
            return f"{x_curr - x_prev:.6g}"
        sign = '-' if x_curr < x_prev else ''
        return sign + cls._format_dx(x_prev, x_curr, is_date)

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
