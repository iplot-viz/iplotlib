"""Frozen-crosshair manager window (issue #130).

A frozen crosshair is a *time cursor*: unlike a ruler (a point-to-point (x, y)
measurement), it snapshots the value of every signal at the frozen time. This
window therefore reuses the ruler table's chrome -- sortable table, interactive
column resize, Ctrl+C / context-menu copy, CSV/SCSV export -- but presents a
different content model:

  Crosshair | Plot | Time | <one column per signal> | Visible | Labels | Color | Font color

The signal-value columns can be hidden as a block (the issue's show/hide button).
Two layouts are offered:

  List    - one row per crosshair (the model view above), with the per-signal
            controls (Visible / Labels / Color / Remove).
  Compare - signals as rows, one column per crosshair plus a Δ (last − first)
            column, with a filter box, sort-by-value and an optional low→high
            heatmap. This scales to many signals (vertical scroll) and answers
            "which signal moved between two instants".

All ruler rendering is inherited untouched; this class only overrides the row and
column layouts, so it cannot affect the rulers window.
"""

import csv
from typing import Dict, List, Optional

import pandas as pd
from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QFileDialog, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QMessageBox, QPushButton, QTableWidget,
                               QTableWidgetItem, QWidget)

import iplotLogging.setupLogger as Sl
from iplotlib.qt.gui.iplotQtRuler import IplotQtRuler, _CheckableComboBox, _NumericTableItem

logger = Sl.get_logger(__name__)


class IplotQtCrosshair(IplotQtRuler):
    """Frozen-crosshair table with a List layout (one row per crosshair) and a
    Compare layout (signals as rows, crosshairs as columns + Δ)."""

    # Leading columns are fixed; the per-signal value columns follow, then the
    # trailing control columns. Keep NAME/PLOT at 0/1 so the inherited identity,
    # selection and edit slots keep working unchanged.
    COL_NAME = 0
    COL_PLOT = 1
    COL_TIME = 2
    _FIXED_LEADING = 3
    _FIXED_TRAILING = ['Visible', 'Labels', 'Color', 'Font color']

    LABEL_TOGGLES = ['Crosshair label', 'Val label']

    # Colour-blind-safe pair for Δ direction (blue up, orange down) and the
    # single hue used for the optional per-row heatmap wash.
    _UP_COLOR = '#1f77b4'
    _DOWN_COLOR = '#d95f02'
    _HEATMAP_HUE = QColor('#1f77b4')

    def __init__(self, *args, **kwargs):
        kwargs.setdefault('noun', 'crosshair')
        # These must exist before super().__init__ triggers the first (empty) render.
        self._signal_columns_hidden = False
        self._signal_labels: List[str] = []
        self._signal_colors: Dict[str, str] = {}
        self._compare_filter = ''
        self._compare_sort_key = None   # None | crosshair name | 'Δ'
        self._compare_sort_desc = True
        self._compare_colour_cells = False
        super().__init__(*args, **kwargs)

        # Two layouts, like the rulers window but with crosshair-specific content:
        #   List    - one row per crosshair, per-signal value columns (management)
        #   Compare - signals as rows, one column per crosshair + a Δ column, with
        #             filter / sort / optional heatmap (scales to many signals and
        #             answers "which signal moved between two instants").
        self.rows_radio.setText("List")
        self.columns_radio.setText("Compare")

        self.toggle_values_button = QPushButton("Hide signal values")
        self.toggle_values_button.setToolTip("Show or hide the per-signal value columns")
        self.toggle_values_button.pressed.connect(self._toggle_signal_columns)
        self._buttons_layout.insertWidget(self._buttons_layout.count() - 1, self.toggle_values_button)

        self._build_compare_bar()

    # ------------------------------------------------------------------
    # Compare view toolbar
    # ------------------------------------------------------------------
    def _build_compare_bar(self):
        """Compact filter / sort / colour bar, shown only in the Compare layout."""
        self._compare_bar = QWidget()
        bar = QHBoxLayout(self._compare_bar)
        bar.setContentsMargins(0, 0, 0, 0)

        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("Filter signals…")
        self.filter_edit.setClearButtonEnabled(True)
        self.filter_edit.textChanged.connect(self._on_compare_control_changed)

        self.sort_combo = QComboBox()
        self.sort_combo.currentIndexChanged.connect(self._on_compare_control_changed)

        self.sort_dir_button = QPushButton("▼")  # ▼ descending by default
        self.sort_dir_button.setFixedWidth(28)
        self.sort_dir_button.setToolTip("Sort direction")
        self.sort_dir_button.clicked.connect(self._toggle_sort_direction)

        self.colour_check = QCheckBox("Colour cells")
        self.colour_check.setToolTip("Shade each signal's values on a low→high scale")
        self.colour_check.toggled.connect(self._on_colour_cells_toggled)

        bar.addWidget(QLabel("Filter:"))
        bar.addWidget(self.filter_edit, 1)
        bar.addWidget(QLabel("Sort by:"))
        bar.addWidget(self.sort_combo)
        bar.addWidget(self.sort_dir_button)
        bar.addSpacing(12)
        bar.addWidget(self.colour_check)

        # Sits between the layout selector and the table stack; hidden in List view.
        self.layout().insertWidget(1, self._compare_bar)
        self._compare_bar.setVisible(False)

    # ------------------------------------------------------------------
    # Column model
    # ------------------------------------------------------------------
    def _collect_signal_labels(self) -> List[str]:
        """Ordered union of the signal labels crossed by the current crosshairs."""
        labels: List[str] = []
        for row in self._rows:
            sv = row.get('signal_values')
            if isinstance(sv, dict):
                for label in sv:
                    if label not in labels:
                        labels.append(label)
        return labels

    @staticmethod
    def _entry_parts(entry):
        """Split a signal-value cell into (numeric value, display text, color).

        The backend passes ``{value, text, color}`` per signal so the column can
        carry the signal's plot colour and the axis-formatted string; a bare
        number (used by unit tests) degrades to value-only."""
        if isinstance(entry, dict):
            return entry.get('value'), entry.get('text'), entry.get('color')
        return entry, None, None

    def _signal_color_map(self) -> Dict[str, str]:
        """Plot colour of each signal, taken from the first crosshair that carries it."""
        colors: Dict[str, str] = {}
        for row in self._rows:
            sv = row.get('signal_values')
            if not isinstance(sv, dict):
                continue
            for label, entry in sv.items():
                if label not in colors:
                    color = self._entry_parts(entry)[2]
                    if color:
                        colors[label] = color
        return colors

    def _color_signal_headers(self):
        """Tint each signal column header with the signal's plot colour so the
        value maps to its curve at a glance (as the crosshair value labels do)."""
        for i, label in enumerate(self._signal_labels):
            color = self._signal_colors.get(label)
            if not color:
                continue
            header_item = QTableWidgetItem(label)
            header_item.setBackground(QBrush(QColor(color)))
            header_item.setForeground(QBrush(QColor(self._contrast_text_color(color))))
            self.table.setHorizontalHeaderItem(self._signal_col(i), header_item)

    def _signal_col(self, i: int) -> int:
        return self._FIXED_LEADING + i

    def _control_cols(self):
        base = self._FIXED_LEADING + len(self._signal_labels)
        return base, base + 1, base + 2, base + 3  # visible, label, color, font

    def _render_rows(self):
        self.table.setSortingEnabled(False)
        self._signal_labels = self._collect_signal_labels()
        headers = [self._Noun, 'Plot', 'Time'] + list(self._signal_labels) + list(self._FIXED_TRAILING)
        self._signal_colors = self._signal_color_map()
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        self._color_signal_headers()
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(False)

        for row_idx, row in enumerate(self._rows):
            self.table.insertRow(row_idx)
            self._populate_row_cells(row_idx, row)

        self.table.resizeColumnsToContents()
        sort_arrow_pad = 24
        for col in range(self.table.columnCount()):
            self.table.setColumnWidth(col, self.table.columnWidth(col) + sort_arrow_pad)
        self.table.setSortingEnabled(True)
        self.table.sortItems(self.COL_NAME, Qt.SortOrder.AscendingOrder)
        self._apply_signal_column_visibility()

    def _populate_row_cells(self, row_idx: int, row: Dict):
        name_item = QTableWidgetItem(row['name'])
        name_item.setData(Qt.ItemDataRole.UserRole, row['is_date'])
        self.table.setItem(row_idx, self.COL_NAME, name_item)

        plot_item = QTableWidgetItem(self._format_plot_id(row['plot_id']))
        plot_item.setData(Qt.ItemDataRole.UserRole, row['plot_id'])
        self.table.setItem(row_idx, self.COL_PLOT, plot_item)

        x = row['xy'][0]
        x_text = str(pd.Timestamp(x)) if row['is_date'] else f"{x:.6g}"
        time_item = _NumericTableItem(x_text)
        time_item.setData(Qt.ItemDataRole.UserRole, x)
        self.table.setItem(row_idx, self.COL_TIME, time_item)

        sv = row.get('signal_values') if isinstance(row.get('signal_values'), dict) else {}
        for i, label in enumerate(self._signal_labels):
            display = self._display_value(sv.get(label))
            item = QTableWidgetItem(display)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            color = self._signal_colors.get(label)
            if color and display:
                tint = QColor(color)
                tint.setAlpha(45)  # light wash so the whole column reads as this signal
                item.setBackground(QBrush(tint))
            self.table.setItem(row_idx, self._signal_col(i), item)

        col_visible, col_label, col_color, col_font = self._control_cols()

        visible_cb = QCheckBox()
        visible_cb.setChecked(row['visible'])
        visible_cb.stateChanged.connect(
            lambda state, cb=visible_cb: self._on_visibility_changed(self.table.indexAt(cb.pos()).row(), state))
        self.table.setCellWidget(row_idx, col_visible, visible_cb)

        label_combo = _CheckableComboBox()
        label_combo.add_checkable_item(self.LABEL_TOGGLES[0], row['show_label'])
        label_combo.add_checkable_item(self.LABEL_TOGGLES[1], row['show_val_label'])
        label_combo.changed.connect(
            lambda cb=label_combo: self._on_label_mode_changed(self.table.indexAt(cb.pos()).row(), cb))
        self.table.setCellWidget(row_idx, col_label, label_combo)

        color_btn = self._make_color_button(row['color'], self._on_color_clicked)
        self.table.setCellWidget(row_idx, col_color, color_btn)

        font_btn = self._make_color_button(row['font_color'], self._on_font_color_clicked)
        self.table.setCellWidget(row_idx, col_font, font_btn)

    def _display_value(self, entry) -> str:
        """Prefer the backend's axis-formatted text (matches the on-plot label);
        fall back to formatting the raw value."""
        value, text, _ = self._entry_parts(entry)
        return text if text is not None else self._format_value(value)

    @staticmethod
    def _format_value(value) -> str:
        if value is None or value == '':
            return ''
        if isinstance(value, str):
            return value
        try:
            return f"{float(value):.6g}"
        except (TypeError, ValueError):
            return str(value)

    # ------------------------------------------------------------------
    # Show / hide the per-signal value columns (issue #130)
    # ------------------------------------------------------------------
    def _apply_signal_column_visibility(self):
        for i in range(len(self._signal_labels)):
            self.table.setColumnHidden(self._signal_col(i), self._signal_columns_hidden)

    def _toggle_signal_columns(self):
        self._signal_columns_hidden = not self._signal_columns_hidden
        self.toggle_values_button.setText(
            "Show signal values" if self._signal_columns_hidden else "Hide signal values")
        self._apply_signal_column_visibility()

    # ------------------------------------------------------------------
    # Compare view: signals as rows, crosshairs as columns (+ Δ)
    # ------------------------------------------------------------------
    def _on_view_mode_changed(self):
        super()._on_view_mode_changed()
        compare = self.view_mode == self.VIEW_COLUMNS
        self._compare_bar.setVisible(compare)
        # "Hide signal values" only applies to the List layout's columns.
        self.toggle_values_button.setVisible(not compare)

    def _on_compare_control_changed(self, *_):
        self._compare_filter = self.filter_edit.text()
        self._compare_sort_key = self.sort_combo.currentData()
        if self.view_mode == self.VIEW_COLUMNS:
            self._render_table()

    def _toggle_sort_direction(self):
        self._compare_sort_desc = not self._compare_sort_desc
        self.sort_dir_button.setText("▼" if self._compare_sort_desc else "▲")
        if self.view_mode == self.VIEW_COLUMNS:
            self._render_table()

    def _on_colour_cells_toggled(self, checked: bool):
        self._compare_colour_cells = checked
        if self.view_mode == self.VIEW_COLUMNS:
            self._render_table()

    def _rebuild_sort_combo(self, crosshairs: List[Dict]):
        """Refresh the Sort-by options (None / each crosshair / Δ) while keeping
        the current choice when it still exists."""
        previous = self._compare_sort_key
        self.sort_combo.blockSignals(True)
        self.sort_combo.clear()
        self.sort_combo.addItem("None", None)
        for ch in crosshairs:
            self.sort_combo.addItem(ch['name'], ch['name'])
        if len(crosshairs) >= 2:
            self.sort_combo.addItem("Δ", 'Δ')
        idx = self.sort_combo.findData(previous)
        self.sort_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self._compare_sort_key = self.sort_combo.currentData()
        self.sort_combo.blockSignals(False)

    @staticmethod
    def _delta(values: List[Optional[float]]) -> Optional[float]:
        """Chronological change between the earliest and latest crosshair that
        actually read this signal. Because each crosshair only carries the
        signals of its own plot, a signal is usually present in a subset of the
        columns; using the first/last *present* values (not columns 0 and -1)
        keeps Δ meaningful instead of blanking out. Needs at least two readings."""
        present = [v for v in values if v is not None]
        if len(present) < 2:
            return None
        return present[-1] - present[0]

    def _compare_signal_order(self, crosshairs: List[Dict], show_delta: bool) -> List[str]:
        key = self._compare_sort_key
        labels = list(self._signal_labels)
        if not key:
            return labels

        def sort_value(label):
            values = [self._entry_parts((ch.get('signal_values') or {}).get(label))[0]
                      for ch in crosshairs]
            v = self._delta(values) if key == 'Δ' else next(
                (val for ch, val in zip(crosshairs, values) if ch['name'] == key), None)
            # Missing values sink to the bottom regardless of direction.
            if v is None:
                return (1, 0.0)
            return (0, -v if self._compare_sort_desc else v)

        return sorted(labels, key=sort_value)

    def _render_column_sections(self):
        self._signal_labels = self._collect_signal_labels()
        self._signal_colors = self._signal_color_map()
        crosshairs = sorted(self._rows, key=lambda r: r['xy'][0])
        self._rebuild_sort_combo(crosshairs)

        show_delta = len(crosshairs) >= 2
        headers = ['Signal'] + [ch['name'] for ch in crosshairs]
        if show_delta:
            headers.append('Δ (last − first)')

        table = QTableWidget()
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setColumnCount(len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        table.setSortingEnabled(False)
        self._install_copy_action(table)

        order = self._compare_signal_order(crosshairs, show_delta)
        needle = self._compare_filter.strip().lower()
        if needle:
            order = [label for label in order if needle in label.lower()]

        table.setRowCount(len(order))
        for r_idx, label in enumerate(order):
            self._fill_compare_row(table, r_idx, label, crosshairs, show_delta)

        table.resizeColumnsToContents()
        # Stretch factor 1 so the table fills the scroll viewport and scrolls its
        # own rows (natural vertical scroll when there are many signals).
        self.columns_layout.insertWidget(self.columns_layout.count() - 1, table, 1)

    def _fill_compare_row(self, table, r_idx, label, crosshairs, show_delta):
        name_item = QTableWidgetItem(label)
        color = self._signal_colors.get(label)
        if color:
            swatch = QColor(color)
            swatch.setAlpha(70)
            name_item.setBackground(QBrush(swatch))
        table.setItem(r_idx, 0, name_item)

        values = []
        for c_idx, ch in enumerate(crosshairs, start=1):
            entry = (ch.get('signal_values') or {}).get(label)
            value = self._entry_parts(entry)[0]
            values.append(value)
            item = QTableWidgetItem(self._display_value(entry))
            item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            table.setItem(r_idx, c_idx, item)

        if self._compare_colour_cells:
            self._shade_row_cells(table, r_idx, values)

        if show_delta:
            d = self._delta(values)
            item = QTableWidgetItem('' if d is None else self._format_value(d))
            item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            if d is not None and d != 0:
                item.setForeground(QBrush(QColor(self._UP_COLOR if d > 0 else self._DOWN_COLOR)))
            table.setItem(r_idx, len(crosshairs) + 1, item)

    def _shade_row_cells(self, table, r_idx, values: List[Optional[float]]):
        """Optional heatmap: wash each value on a low→high single-hue scale within
        this signal's row (sequential, colour-blind safe; exact numbers stay
        readable). Needs at least two numeric values to have a range."""
        nums = [v for v in values if v is not None]
        if len(nums) < 2:
            return
        lo, hi = min(nums), max(nums)
        if hi == lo:
            return
        for c_idx, v in enumerate(values, start=1):
            if v is None:
                continue
            frac = (v - lo) / (hi - lo)
            tint = QColor(self._HEATMAP_HUE)
            tint.setAlpha(int(25 + frac * 110))  # subtle at the low end, stronger at the high
            table.item(r_idx, c_idx).setBackground(QBrush(tint))

    # ------------------------------------------------------------------
    # Deltas: time distance + per-signal value differences
    # ------------------------------------------------------------------
    def _row_dict_for_table_row(self, table_row: int) -> Optional[Dict]:
        name, plot_id = self._row_metadata(table_row)
        idx = self._find_row_index(name, plot_id)
        return self._rows[idx] if idx >= 0 else None

    def _compute_distance(self):
        if len(self.selection_history) < 2:
            self._warn("Select at least 2 crosshairs to compute deltas.")
            return

        rows = list(self.selection_history)
        rows.sort(key=lambda r: self.table.item(r, self.COL_TIME).data(Qt.ItemDataRole.UserRole))
        is_date = self.table.item(rows[0], self.COL_NAME).data(Qt.ItemDataRole.UserRole)

        lines = []
        for r1, r2 in zip(rows[:-1], rows[1:]):
            n1 = self.table.item(r1, self.COL_NAME).text()
            n2 = self.table.item(r2, self.COL_NAME).text()
            x1 = self.table.item(r1, self.COL_TIME).data(Qt.ItemDataRole.UserRole)
            x2 = self.table.item(r2, self.COL_TIME).data(Qt.ItemDataRole.UserRole)
            parts = [f"dt = {self._format_dx(x1, x2, is_date)}"]
            for label, delta in self._signal_deltas(r1, r2):
                parts.append(f"Δ{label} = {delta:.6g}")
            lines.append(f"{n1} -> {n2}: " + ", ".join(parts))

        box = QMessageBox()
        box.setIcon(QMessageBox.Icon.Information)
        box.setWindowTitle("Crosshair deltas")
        box.setText("\n".join(lines))
        logger.info("\n".join(lines))
        box.exec_()

    def _signal_deltas(self, table_row_1: int, table_row_2: int):
        """(label, value2 - value1) for every signal present -- and numeric -- at
        both crosshairs, in column order."""
        d1 = self._row_dict_for_table_row(table_row_1)
        d2 = self._row_dict_for_table_row(table_row_2)
        sv1 = d1.get('signal_values') if d1 and isinstance(d1.get('signal_values'), dict) else {}
        sv2 = d2.get('signal_values') if d2 and isinstance(d2.get('signal_values'), dict) else {}
        deltas = []
        for label in self._signal_labels:
            v1 = self._entry_parts(sv1.get(label))[0]
            v2 = self._entry_parts(sv2.get(label))[0]
            try:
                deltas.append((label, float(v2) - float(v1)))
            except (TypeError, ValueError):
                continue  # signal absent or no data at one of the two crosshairs
        return deltas

    # ------------------------------------------------------------------
    # CSV / SCSV export with the per-signal columns
    # ------------------------------------------------------------------
    def _export_csv(self):
        if not self._rows:
            QMessageBox.information(self, "Export crosshairs", "There are no crosshairs to export.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export crosshairs", "crosshairs.scsv",
            "Semicolon-separated values (*.scsv);;CSV (*.csv)")
        if not path:
            return
        if not path.lower().endswith(('.scsv', '.csv')):
            path += '.scsv'
        delimiter = ',' if path.lower().endswith('.csv') else ';'

        labels = self._collect_signal_labels()
        headers = ['Crosshair', 'Plot', 'Time'] + labels + ['Visible', 'Labels', 'Color', 'Font color']
        try:
            with open(path, 'w', newline='', encoding='utf-8') as fh:
                writer = csv.writer(fh, delimiter=delimiter)
                writer.writerow(headers)
                for r in sorted(self._rows, key=lambda row: row['name']):
                    sv = r.get('signal_values') if isinstance(r.get('signal_values'), dict) else {}
                    writer.writerow(
                        [r['name'], self._format_plot_id(r['plot_id']), self._format_x(r)]
                        + [self._display_value(sv.get(label)) for label in labels]
                        + [str(r['visible']).lower(), self._labels_summary(r), r['color'], r['font_color']])
        except OSError as exc:
            logger.error(f"Failed to export crosshairs to CSV: {exc}")
            QMessageBox.warning(self, "Export to CSV", f"Could not write the file:\n{exc}")
