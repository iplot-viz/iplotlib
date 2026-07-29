import csv
import re
from contextlib import contextmanager
from string import ascii_uppercase
from typing import Dict, List, Set, Tuple

import pandas as pd
from PySide6.QtCore import QEvent, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QBrush, QColor, QKeySequence, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QButtonGroup, QCheckBox, QColorDialog, QComboBox,
                                QDialog, QFileDialog, QFrame, QHBoxLayout, QHeaderView, QLabel, QMenu, QMessageBox,
                                QPushButton, QRadioButton, QScrollArea, QStackedWidget, QStyle,
                                QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

import iplotLogging.setupLogger as Sl
from iplotlib.core.plot import PlotXY
from iplotlib.core.ruler import Ruler, contrast_text_color
# Same duration rendering the statistics table uses, so time deltas read alike.
from iplotlib.impl.matplotlib.dateFormatter import _fmt_duration
from iplotlib.qt.utils.icon_loader import create_icon

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

    def showPopup(self):
        # The popup is as wide as the field, which a narrow table column squeezes
        # until the item text elides; its contents also need the check indicator.
        view = self.view()
        view.setMinimumWidth(view.sizeHintForColumn(0) + 2 * view.frameWidth())
        super().showPopup()

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
    # One column per signal starts here; the trailing control columns shift
    # with the number of signals (see the COL_* properties below).
    SIG_COL_BASE = 4

    # Independent toggles shown in the Labels column, in check order.
    LABEL_TOGGLES = ['Ruler label', 'Val label']

    # Signal palette reversed so a ruler rarely matches the signals it crosses.
    DEFAULT_COLOR_CYCLE = list(reversed(PlotXY._color_cycle))

    VIEW_ROWS = 'rows'
    VIEW_COLUMNS = 'columns'

    _COLUMNS_AXIS_LABELS = ['X', 'Y']
    _DELTA_HEADER = 'Δ'

    # Wrap point for signal-name headers: long names grow vertically instead
    # of being truncated.
    _WRAP_WIDTH = 18

    @property
    def COL_VISIBLE(self) -> int:
        return self.SIG_COL_BASE + len(self._signal_labels)

    @property
    def COL_LABEL(self) -> int:
        return self.COL_VISIBLE + 1

    @property
    def COL_COLOR(self) -> int:
        return self.COL_VISIBLE + 2

    @property
    def COL_FONT_COLOR(self) -> int:
        return self.COL_VISIBLE + 3

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
        # (plot_id, table, {signal label -> table row}) per plot section.
        self.column_sections: List[Tuple[Tuple[int, int], QTableWidget, Dict[str, int]]] = []
        self._signal_labels: List[str] = []
        self._hidden_signals: Set[str] = set()
        self._distance_dialog: QDialog = None
        # Sort criterion chosen by the user. The table is rebuilt on every ruler
        # update, so it must be restored afterwards or the view snaps back.
        self._sort_column = self.COL_NAME
        self._sort_order = Qt.SortOrder.AscendingOrder
        self._rendering = False
        self._bulk_depth = 0

        self.rows_radio = QRadioButton("Rows")
        self.rows_radio.setToolTip("One row per ruler. Editable.")
        self.rows_radio.setChecked(True)
        self.columns_radio = QRadioButton("Columns")
        self.columns_radio.setToolTip("One section per plot with X / Y values and Δ. Read-only.")
        view_group = QButtonGroup(self)
        view_group.addButton(self.rows_radio)
        view_group.addButton(self.columns_radio)
        self.rows_radio.toggled.connect(self._on_view_mode_changed)

        self.signals_button = QPushButton("Hide/Show signals")
        self.signals_button.setToolTip("Choose which signal value columns are shown.")
        self.signals_menu = QMenu(self.signals_button)
        self.signals_button.setMenu(self.signals_menu)

        view_layout = QHBoxLayout()
        view_layout.addWidget(QLabel("Layout:"))
        view_layout.addWidget(self.rows_radio)
        view_layout.addWidget(self.columns_radio)
        view_layout.addStretch()
        view_layout.addWidget(self.signals_button)

        self.table = QTableWidget()
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.selectionModel().selectionChanged.connect(self._update_selection_history)
        self.table.horizontalHeader().sortIndicatorChanged.connect(self._on_sort_indicator_changed)
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
        self.export_button = QPushButton("Export to CSV")
        self.copy_button = QPushButton(create_icon('copy'), "Copy table")
        self.copy_button.setToolTip("Copy the current table to the clipboard.")
        self.remove_button.pressed.connect(self._remove_selected)
        self.distance_button.pressed.connect(self._compute_distance)
        self.export_button.pressed.connect(self._export_csv)
        self.copy_button.pressed.connect(self._copy_current_view)

        main_layout = QVBoxLayout()
        main_layout.addLayout(view_layout)
        main_layout.addWidget(self.view_stack)
        buttons = QHBoxLayout()
        buttons.addWidget(self.remove_button)
        buttons.addWidget(self.distance_button)
        buttons.addWidget(self.export_button)
        buttons.addWidget(self.copy_button)
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
                show_val_label: bool = True, signal_values: Dict[str, float] = None,
                x_is_time: bool = False):
        self._rows.append({
            'name': name,
            'plot_id': tuple(plot_id),
            'xy': (xy[0], xy[1]),
            'color': color,
            'visible': visible,
            'is_date': is_date,
            # Dates are time too; x_is_time additionally covers relative-time axes.
            'x_is_time': bool(x_is_time) or bool(is_date),
            'font_color': font_color,
            'show_label': show_label,
            'show_val_label': show_val_label,
            'signal_values': dict(signal_values or {}),
        })
        # Sorting must be off during insertion; re-render to handle both modes uniformly.
        self._render_table()

    def remove_row_by_name(self, name: str):
        """Drop every row of ruler *name*: a ruler drawn on several plots owns a
        row per plot and is deleted as a whole."""
        remaining = [r for r in self._rows if r['name'] != name]
        if len(remaining) == len(self._rows):
            return
        self._rows = remaining
        # A removed ruler can retire signal columns; re-render keeps the header
        # set and the signals menu consistent. The rebuild drops the visual
        # selection, so the history must go with it.
        self.selection_history.clear()
        self._render_table()

    def update_ruler_rows(self, name: str, rows: List[Dict]):
        """Refresh ruler *name* after it is dragged on the canvas, from one
        ``{'plot_id', 'xy', 'signal_values'}`` entry per plot it spans, so the
        plots it is mirrored onto follow with their own values and not only the
        one it was grabbed from."""
        by_plot = {tuple(entry['plot_id']): entry for entry in rows}
        for row in self._rows:
            if row['name'] != name:
                continue
            entry = by_plot.get(row['plot_id'])
            if entry is None:
                continue
            row['xy'] = (entry['xy'][0], entry['xy'][1])
            row['signal_values'] = dict(entry.get('signal_values') or {})
        self._render_table()

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

    def _on_sort_indicator_changed(self, column: int, order):
        """Remember the column the user sorted by so rebuilds can restore it."""
        if self._rendering:
            return
        self._sort_column = column
        self._sort_order = order

    @contextmanager
    def bulk_update(self):
        """Group several row changes into one rebuild: every change rebuilds the
        whole view, and a ruler spanning N plots adds N rows."""
        self._bulk_depth += 1
        try:
            yield
        finally:
            self._bulk_depth -= 1
            if not self._bulk_depth:
                self._render_table()

    def _render_table(self):
        """Rebuild the active view from ``self._rows``."""
        if self._bulk_depth:
            return
        # Rebuilding moves the sort indicator around; those moves are not the
        # user's choice and must not overwrite the remembered criterion.
        self._rendering = True
        try:
            self._rebuild_view()
        finally:
            self._rendering = False

    def _rebuild_view(self):
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

        self._signal_labels = self._collect_signal_labels()
        self._hidden_signals &= set(self._signal_labels)
        self._rebuild_signals_menu()

        if self.view_mode == self.VIEW_ROWS:
            self.view_stack.setCurrentWidget(self.table)
            self._render_rows()
            edit_enabled = True
        else:
            self.view_stack.setCurrentWidget(self.columns_scroll)
            self._render_column_sections()
            # Deferred so it runs after each section's own height fit-up.
            QTimer.singleShot(0, self._fit_columns_view_height)
            edit_enabled = False

        self._apply_signal_visibility()
        self.remove_button.setEnabled(edit_enabled)
        self.distance_button.setEnabled(edit_enabled)

        self.table.selectionModel().selectionChanged.connect(self._update_selection_history)

    def _collect_signal_labels(self) -> List[str]:
        """Union of the signal labels of every ruler, in first-appearance order."""
        labels: List[str] = []
        for row in self._rows:
            for label in (row.get('signal_values') or {}):
                if label not in labels:
                    labels.append(label)
        return labels

    @classmethod
    def _wrap_label(cls, label: str) -> str:
        """Soft-wrap a long signal name at its natural separators so headers
        grow vertically instead of truncating the name."""
        width = cls._WRAP_WIDTH
        # Keep each separator with the fragment it terminates.
        parts = [p for p in re.split(r'(?<=[-_:.\s])', label) if p]
        lines: List[str] = []
        current = ''
        for part in parts:
            while len(part) > width:
                if current:
                    lines.append(current)
                    current = ''
                lines.append(part[:width])
                part = part[width:]
            if current and len(current) + len(part) > width:
                lines.append(current)
                current = part
            else:
                current += part
        if current:
            lines.append(current)
        return '\n'.join(lines)

    def _rebuild_signals_menu(self):
        self.signals_menu.clear()
        for label in self._signal_labels:
            action = QAction(label, self.signals_menu)
            action.setCheckable(True)
            action.setChecked(label not in self._hidden_signals)
            action.toggled.connect(
                lambda checked, lbl=label: self._on_signal_toggled(lbl, checked))
            self.signals_menu.addAction(action)
        self.signals_button.setEnabled(bool(self._signal_labels))

    def _on_signal_toggled(self, label: str, visible: bool):
        if visible:
            self._hidden_signals.discard(label)
        else:
            self._hidden_signals.add(label)
        self._apply_signal_visibility()

    def _apply_signal_visibility(self):
        """Show/hide signal columns (rows view) or signal rows (columns view)
        in place, so the open menu keeps its actions alive."""
        if self.view_mode == self.VIEW_ROWS:
            for i, label in enumerate(self._signal_labels):
                self.table.setColumnHidden(self.SIG_COL_BASE + i,
                                           label in self._hidden_signals)
        else:
            for _, table, sig_rows in self.column_sections:
                for label, row_idx in sig_rows.items():
                    table.setRowHidden(row_idx, label in self._hidden_signals)
                # Hidden rows contribute zero height; re-fit the fixed height.
                self._fit_section_height(table)

    def _render_rows(self):
        self.table.setSortingEnabled(False)
        self.table.setColumnCount(self.SIG_COL_BASE + len(self._signal_labels) + 4)
        headers = (['Ruler', 'Plot', 'X value', 'Y value'] + list(self._signal_labels)
                   + ['Visible', 'Labels', 'Color', 'Font color'])
        self.table.setHorizontalHeaderLabels(headers)
        for i, label in enumerate(self._signal_labels):
            item = QTableWidgetItem(self._wrap_label(label))
            item.setToolTip(label)
            self.table.setHorizontalHeaderItem(self.SIG_COL_BASE + i, item)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(False)

        for row_idx, row in enumerate(self._rows):
            self.table.insertRow(row_idx)
            self._populate_row_cells(row_idx, row)

        self.table.setSortingEnabled(True)
        column = self._sort_column if self._sort_column < self.table.columnCount() else self.COL_NAME
        self.table.sortItems(column, self._sort_order)
        self.table.horizontalHeader().setSortIndicator(column, self._sort_order)
        self.table.resizeColumnsToContents()
        # Fitting a column to its contents leaves its title no room for the sort
        # indicator, which the header draws inside the section.
        indicator = header.style().pixelMetric(QStyle.PixelMetric.PM_HeaderMarkSize, None, header)
        for col in range(self.table.columnCount()):
            self.table.setColumnWidth(col, max(self.table.columnWidth(col) + indicator,
                                               header.defaultSectionSize()))

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

        y_item = _NumericTableItem('' if y is None else f"{y:.6g}")
        y_item.setData(Qt.ItemDataRole.UserRole, y)
        self.table.setItem(row_idx, self.COL_Y, y_item)

        values = row.get('signal_values') or {}
        for i, label in enumerate(self._signal_labels):
            value = values.get(label)
            values_item = _NumericTableItem('' if value is None else f"{value:.6g}")
            values_item.setData(Qt.ItemDataRole.UserRole, value)
            values_item.setFlags(values_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row_idx, self.SIG_COL_BASE + i, values_item)

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
            section, table, sig_rows = self._build_plot_section(plot_id, rulers)
            self.columns_layout.insertWidget(stretch_idx, section)
            stretch_idx += 1
            self.column_sections.append((plot_id, table, sig_rows))

    def _build_plot_section(self, plot_id: Tuple[int, int],
                             rulers: List[Dict]) -> Tuple[QWidget, QTableWidget, Dict[str, int]]:
        section = QWidget()
        layout = QVBoxLayout(section)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        title = QLabel(f"Plot {self._format_plot_id(plot_id)}")
        title.setStyleSheet("font-weight: bold;")
        layout.addWidget(title)

        n_deltas = max(0, len(rulers) - 1)
        col_count = len(rulers) + n_deltas

        # One row per signal of this plot's rulers, in the global label order.
        sig_labels = [label for label in self._signal_labels
                      if any(label in (r.get('signal_values') or {}) for r in rulers)]
        # A plot the rulers are only mirrored onto has no Y reading of its own,
        # so it drops the Y row instead of repeating the owner's value.
        axis_labels = [label for label in self._COLUMNS_AXIS_LABELS
                       if label != 'Y' or any(r['xy'][1] is not None for r in rulers)]
        sig_rows = {label: len(axis_labels) + i
                    for i, label in enumerate(sig_labels)}

        table = QTableWidget(len(axis_labels) + len(sig_labels), col_count)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        table.setVerticalHeaderLabels(axis_labels
                                      + [self._wrap_label(label) for label in sig_labels])
        for label, row_idx in sig_rows.items():
            table.verticalHeaderItem(row_idx).setToolTip(label)
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

        has_y = 'Y' in axis_labels
        col_idx = 0
        for i, r in enumerate(rulers):
            values = r.get('signal_values') or {}
            if i > 0:
                prev = rulers[i - 1]
                prev_values = prev.get('signal_values') or {}
                self._set_plain_cell(table, 0, col_idx, self._format_consecutive_dx(prev, r))
                if has_y:
                    self._set_plain_cell(table, 1, col_idx,
                                         self._format_delta(prev['xy'][1], r['xy'][1]))
                for label, row_idx in sig_rows.items():
                    v1, v2 = prev_values.get(label), values.get(label)
                    self._set_plain_cell(table, row_idx, col_idx, self._format_delta(v1, v2))
                col_idx += 1
            self._set_axis_cell(table, 0, col_idx, self._format_x(r), r['color'])
            if has_y:
                self._set_axis_cell(table, 1, col_idx, f"{r['xy'][1]:.6g}", r['color'])
            for label, row_idx in sig_rows.items():
                value = values.get(label)
                self._set_axis_cell(table, row_idx, col_idx,
                                    '' if value is None else f"{value:.6g}", r['color'])
            col_idx += 1

        table.resizeColumnsToContents()
        # Wrapped (multi-line) signal names need taller rows or the extra
        # lines clip; the section height sums row heights, so it follows.
        v_header = table.verticalHeader()
        for row_idx in range(table.rowCount()):
            table.setRowHeight(row_idx, max(table.rowHeight(row_idx),
                                            v_header.sectionSizeHint(row_idx)))
        table.setFixedHeight(self._section_table_height(table))
        layout.addWidget(table)
        # A horizontal scrollbar (shown when a plot has many ruler columns) would
        # overlap the last row; grow the fixed height by it once the layout has
        # settled and the scrollbar's visibility is known.
        QTimer.singleShot(0, lambda: self._fit_section_height(table))
        return section, table, sig_rows

    def _fit_columns_view_height(self):
        """Grow the window (never shrink it) until the Columns view shows every
        plot section without a vertical scrollbar, capped to the screen's
        available height."""
        if self.view_mode != self.VIEW_COLUMNS:
            return
        inner = self.columns_scroll.widget()
        if inner is None:
            return
        missing = inner.sizeHint().height() - self.columns_scroll.viewport().height()
        if missing <= 0:
            return
        new_height = self.height() + missing
        screen = self.screen()
        if screen is not None:
            new_height = min(new_height, screen.availableGeometry().height() - 60)
        if new_height > self.height():
            self.resize(self.width(), new_height)

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
            for _, table, _ in self.column_sections:
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
    def _format_delta(first, second) -> str:
        """Signed difference, blank when either side has no reading."""
        if first is None or second is None:
            return ''
        return f"{second - first:.6g}"

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
        rows = sorted({i.row() for i in indexes if not table.isRowHidden(i.row())})
        cols = sorted({i.column() for i in indexes if not table.isColumnHidden(i.column())})
        lines = ['\t'.join(self._cell_text(table, r, c) for c in cols) for r in rows]
        QApplication.clipboard().setText('\n'.join(lines))

    def _copy_current_view(self):
        """Copy the visible table(s) of the active layout, headers included."""
        if self.view_mode == self.VIEW_ROWS:
            self._copy_whole_qtable(self.table)
            return
        blocks = []
        for plot_id, table, _ in self.column_sections:
            lines = [f"Plot {self._format_plot_id(plot_id)}"]
            cols = [c for c in range(table.columnCount()) if not table.isColumnHidden(c)]
            rows = [r for r in range(table.rowCount()) if not table.isRowHidden(r)]
            lines.append('\t'.join([''] + [self._header_text(table.horizontalHeaderItem(c))
                                           for c in cols]))
            for r in rows:
                row_label = self._header_text(table.verticalHeaderItem(r))
                lines.append('\t'.join([row_label]
                                       + [self._cell_text(table, r, c) for c in cols]))
            blocks.append('\n'.join(lines))
        QApplication.clipboard().setText('\n\n'.join(blocks))

    def _copy_whole_qtable(self, table: QTableWidget):
        cols = [c for c in range(table.columnCount()) if not table.isColumnHidden(c)]
        rows = [r for r in range(table.rowCount()) if not table.isRowHidden(r)]
        lines = ['\t'.join(self._header_text(table.horizontalHeaderItem(c)) for c in cols)]
        for r in rows:
            lines.append('\t'.join(self._cell_text(table, r, c) for c in cols))
        QApplication.clipboard().setText('\n'.join(lines))

    @staticmethod
    def _header_text(item) -> str:
        """Single-line header text; wrapped signal names copy as the full name
        kept in their tooltip."""
        if item is None:
            return ''
        if '\n' in item.text():
            return item.toolTip() or item.text().replace('\n', '')
        return item.text()

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

    def _export_csv(self):
        """Write the per-ruler table (all rulers, every column) to a spreadsheet
        file: a semicolon-separated ``.scsv`` by default (mint's convention, so it
        opens cleanly where the comma is the decimal separator) or a comma
        ``.csv``."""
        if not self._rows:
            QMessageBox.information(self, "Export rulers", "There are no rulers to export.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export rulers", "rulers.scsv",
            "Semicolon-separated values (*.scsv);;CSV (*.csv)")
        if not path:
            return
        if not path.lower().endswith(('.scsv', '.csv')):
            path += '.scsv'
        delimiter = ',' if path.lower().endswith('.csv') else ';'
        headers = (['Ruler', 'Plot', 'X value', 'Y value'] + list(self._signal_labels)
                   + ['Visible', 'Labels', 'Color', 'Font color'])
        try:
            with open(path, 'w', newline='', encoding='utf-8') as fh:
                writer = csv.writer(fh, delimiter=delimiter)
                writer.writerow(headers)
                for r in sorted(self._rows, key=lambda row: row['name']):
                    values = r.get('signal_values') or {}
                    value_cells = ['' if values.get(label) is None else f"{values[label]:.6g}"
                                   for label in self._signal_labels]
                    writer.writerow([
                        r['name'], self._format_plot_id(r['plot_id']), self._format_x(r),
                        '' if r['xy'][1] is None else f"{r['xy'][1]:.6g}", *value_cells,
                        str(r['visible']).lower(), self._labels_summary(r),
                        r['color'], r['font_color'],
                    ])
        except OSError as exc:
            logger.error(f"Failed to export rulers to CSV: {exc}")
            QMessageBox.warning(self, "Export to CSV", f"Could not write the file:\n{exc}")

    def _labels_summary(self, row: Dict) -> str:
        """Same summary the Labels combo shows, rebuilt from the model for export."""
        checked = [toggle for toggle, on in
                   zip(self.LABEL_TOGGLES, (row['show_label'], row['show_val_label'])) if on]
        if not checked:
            return "None"
        if len(checked) == len(self.LABEL_TOGGLES):
            return "All"
        return ", ".join(checked)

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
        # Visibility belongs to the ruler, not to one of the plots it spans.
        for r in self._rows:
            if r['name'] == name:
                r['visible'] = visible
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
        # Colours belong to the ruler, so they reach every plot it spans.
        for r in self._rows:
            if r['name'] == name:
                r[key] = color
        signal.emit(name, plot_id, color)

    def _remove_selected(self):
        # Resolve identities BEFORE deletion so visual rows stay valid until we drop them.
        identities = [self._row_metadata(row) for row in self.selection_history]
        removed: Set[str] = set()
        for name, plot_id in identities:
            # Selecting two rows of the same ruler must delete it once.
            if name in removed:
                continue
            removed.add(name)
            self.deleteRuler.emit(name, plot_id, True)
        self._rows = [r for r in self._rows if r['name'] not in removed]
        self.selection_history.clear()
        self._render_table()

    def _compute_distance(self):
        if len(self.selection_history) < 2:
            self._warn("Select at least 2 rulers to compute deltas.")
            return

        # Deltas span plots too (e.g. two stacked plots sharing the time axis):
        # dx is the time distance between rulers, dy the value difference.
        entries = []
        for view_row in self.selection_history:
            name, plot_id = self._row_metadata(view_row)
            idx = self._find_row_index(name, plot_id)
            if idx >= 0:
                entries.append(self._rows[idx])
        entries.sort(key=lambda r: r['xy'][0])

        sig_labels = [label for label in self._signal_labels
                      if label not in self._hidden_signals
                      and any(label in (e.get('signal_values') or {}) for e in entries)]
        headers = ['Rulers', 'ΔX', 'ΔY'] + [f"Δ {label}" for label in sig_labels]

        data_rows = []
        for r1, r2 in zip(entries[:-1], entries[1:]):
            y1, y2 = r1['xy'][1], r2['xy'][1]
            cells = [f"{r1['name']} → {r2['name']}",
                     self._format_dx(r1['xy'][0], r2['xy'][0], r1['is_date'],
                                     r1.get('x_is_time', False)),
                     '' if y1 is None or y2 is None else f"{abs(y2 - y1):.6g}"]
            values1 = r1.get('signal_values') or {}
            values2 = r2.get('signal_values') or {}
            for label in sig_labels:
                v1, v2 = values1.get(label), values2.get(label)
                cells.append(f"{abs(v2 - v1):.6g}" if v1 is not None and v2 is not None else '')
            data_rows.append(cells)

        # ASCII-safe log line: cp1252 console handlers choke on Δ/→.
        log_text = '\n'.join('\t'.join(cells) for cells in [headers] + data_rows)
        logger.info(log_text.replace('Δ', 'd').replace('→', '->'))
        self._show_distance_dialog(headers, data_rows)

    def _show_distance_dialog(self, headers: List[str], data_rows: List[List[str]]):
        """Non-modal deltas table the user can keep at hand, select from and
        copy (button, context menu or Ctrl+C)."""
        if self._distance_dialog is not None:
            self._distance_dialog.close()

        dialog = QDialog(self)
        dialog.setWindowTitle("Ruler deltas")
        layout = QVBoxLayout(dialog)

        table = QTableWidget(len(data_rows), len(headers), dialog)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        table.verticalHeader().setVisible(False)
        table.setHorizontalHeaderLabels(headers)
        # Signal delta headers wrap like the signal columns do.
        for col, header_text in enumerate(headers):
            if col >= 3:
                item = QTableWidgetItem(self._wrap_label(header_text))
                item.setToolTip(header_text[len('Δ '):])
                table.setHorizontalHeaderItem(col, item)
        for row_idx, cells in enumerate(data_rows):
            for col_idx, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                if col_idx:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                table.setItem(row_idx, col_idx, item)
        table.resizeColumnsToContents()
        self._install_copy_action(table)
        layout.addWidget(table)

        buttons = QHBoxLayout()
        copy_button = QPushButton(create_icon('copy'), "Copy")
        copy_button.setToolTip("Copy the whole table to the clipboard.")
        copy_button.pressed.connect(lambda: self._copy_whole_qtable(table))
        close_button = QPushButton("Close")
        close_button.pressed.connect(dialog.close)
        buttons.addStretch()
        buttons.addWidget(copy_button)
        buttons.addWidget(close_button)
        layout.addLayout(buttons)

        width = min(900, table.horizontalHeader().length() + 60)
        height = min(500, table.verticalHeader().length()
                     + table.horizontalHeader().height() + 110)
        dialog.resize(max(360, width), max(160, height))
        dialog.show()
        self._distance_dialog = dialog
        self._distance_table = table

    @classmethod
    def _format_consecutive_dx(cls, prev_row: Dict, row: Dict) -> str:
        sign = '-' if row['xy'][0] < prev_row['xy'][0] else ''
        return sign + cls._format_dx(prev_row['xy'][0], row['xy'][0],
                                     prev_row['is_date'],
                                     prev_row.get('x_is_time', False))

    @classmethod
    def _format_dx(cls, x1, x2, is_date: bool, x_is_time: bool = False) -> str:
        """|Δx| as plain text; time axes read ``<seconds> s (<duration>)`` with
        the same duration format the statistics table uses."""
        if is_date:
            # Date axes carry nanoseconds since the epoch.
            return cls._format_time_delta(abs(x2 - x1) / 1e9)
        if x_is_time:
            # Relative-time axes carry seconds.
            return cls._format_time_delta(abs(x2 - x1))
        return f"{abs(x2 - x1):.6g}"

    @staticmethod
    def _format_time_delta(seconds: float) -> str:
        return f"{seconds:.6g} s ({_fmt_duration(int(round(seconds * 1e9)), 1)})"

    def _warn(self, msg: str):
        box = QMessageBox()
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Rulers")
        box.setText(msg)
        logger.warning(msg)
        box.exec_()
