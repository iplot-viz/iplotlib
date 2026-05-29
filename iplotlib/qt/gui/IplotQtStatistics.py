import csv

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox, QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, \
    QTableWidgetItem, QHeaderView, QAbstractItemView, QPushButton, QMenu, QSpinBox, QLabel, QFrame

import iplotLogging.setupLogger as Sl
from pyqtgraph import PlotItem

from iplotlib.core import PlotXYWithSlider, PlotContourWithSlider
from iplotlib.impl.matplotlib.dateFormatter import NanosecondDateFormatter as MPLDateFormatter
from iplotlib.impl.pyqtgraph.dateFormatter import NanosecondDateFormatter as PGDateFormatter

logger = Sl.get_logger(__name__)


class NumericTableWidgetItem(QTableWidgetItem):
    """
    Custom QTableWidgetItem that sorts by numeric value stored in UserRole
    """

    def __lt__(self, other):
        self_data = self.data(Qt.ItemDataRole.UserRole)
        other_data = other.data(Qt.ItemDataRole.UserRole)

        # Handle None values
        if self_data is None and other_data is None:
            return False
        if self_data is None:
            return True
        if other_data is None:
            return False

        # Handle tuples (for envelope data: first, last columns)
        val_self_data = self_data[0] if isinstance(self_data, tuple) else self_data
        val_other_data = other_data[0] if isinstance(other_data, tuple) else other_data

        return val_self_data < val_other_data


class IplotQtStatistics(QWidget):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.resize(1050, 500)
        self.setWindowTitle("Statistics table")

        self.canvas_columns: int = 1

        self.column_names = ['Signal name', 'Min', 'Avg', 'Max', 'First', 'Last', 'Samples', 'First Time', 'Last Time']

        # Marker table creation
        self.table = QTableWidget()
        self.table.setColumnCount(9)
        self.table.setHorizontalHeaderLabels(self.column_names)

        # Disable cell modification
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)

        # Cell selection with multi-select support
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)

        # Context menu
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_context_menu)

        # Enable sorting by clicking on column headers
        self.table.setSortingEnabled(True)

        # Adjust column width dynamically to fit content
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(True)

        # Alternating row colors
        self.table.setAlternatingRowColors(True)

        # Layout
        main_v_layout = QVBoxLayout()
        top_v_layout = QVBoxLayout()
        top_layout_with_button = QHBoxLayout()

        # Button and menu to toggle column visibility
        self.column_menu_button = QPushButton("Hide/Show Columns")
        self.column_menu = QMenu()

        for i, name in enumerate(self.column_names[1:], start=1):
            action = QAction(name, self)
            action.setCheckable(True)
            action.setChecked(True)
            action.toggled.connect(lambda checked, col=i: self.table.setColumnHidden(col, not checked))
            self.column_menu.addAction(action)

        self.column_menu_button.setMenu(self.column_menu)

        # Add button to adjust decimals
        self.decimals = QLabel("Number of decimals: ")
        self.adjust_decimals = QSpinBox()
        self.adjust_decimals.setRange(2, 17)
        self.adjust_decimals.setValue(2)
        self.decimal_digits = self.adjust_decimals.value()
        self.apply_decimals_button = QPushButton("Apply")
        self.apply_decimals_button.clicked.connect(self.update_table_format)

        # Export CSV button
        self.export_csv_button = QPushButton("Export CSV")
        self.export_csv_button.clicked.connect(self._export_csv)

        # Add button and table to layout
        top_layout_with_button.addWidget(self.column_menu_button)
        top_layout_with_button.addWidget(self.decimals)
        top_layout_with_button.addWidget(self.adjust_decimals)
        top_layout_with_button.addWidget(self.apply_decimals_button)
        top_layout_with_button.addWidget(self.export_csv_button)
        top_layout_with_button.addStretch()

        # Add controllers to vertical layout
        top_v_layout.addLayout(top_layout_with_button)

        # Add separator
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        separator.setLineWidth(1)
        top_v_layout.addWidget(separator)

        # Add table to vertical layout
        top_v_layout.addWidget(self.table)

        main_v_layout.addLayout(top_v_layout)
        self.setLayout(main_v_layout)

    def set_canvas_columns(self, n: int):
        """Inform the table how many columns the canvas grid has so the plot
        identifier shown in the Signal name column matches the Stack convention
        used in the variables config (single number when one column, row.col
        when several)."""
        self.canvas_columns = max(1, int(n))

    def _format_plot_id(self, plot_id) -> str:
        if self.canvas_columns <= 1:
            return f"{plot_id[0]}"
        return f"{plot_id[0]}.{plot_id[1]}"

    def _format_float(self, value):
        """
            Format float: show as integer if no decimals
        """
        return int(value) if value.is_integer() else value

    def _create_item(self, value):
        """
        Creates NumericTableWidgetItem and set data with formatting applied
        """
        digits = self.decimal_digits

        def fmt(val):
            return f"{val:.{digits}f}" if not float(val).is_integer() else str(int(val))

        if isinstance(value, tuple):
            val = f"({', '.join(fmt(v) for v in value)})"
            item = NumericTableWidgetItem(val)
            item.setData(Qt.ItemDataRole.UserRole, value)
        else:
            scalar = float(value)
            item = NumericTableWidgetItem(fmt(scalar))
            item.setData(Qt.ItemDataRole.UserRole, scalar)

        return item

    def _create_timestamp_item(self, timestamp, is_date, impl_plot):
        """
        Creates NumericTableWidgetItem for timestamp with proper formatting
        """
        if is_date:
            # Use the appropriate formatter based on backend
            if isinstance(impl_plot, PlotItem):
                formatter = PGDateFormatter(orientation='bottom')
            else:
                formatter = MPLDateFormatter(ax_idx=0)

            # Format the timestamp
            formatted = formatter.date_fmt(int(timestamp), formatter.YEAR, formatter.NANOSECOND, postfix_end=True)
            item = NumericTableWidgetItem(formatted)
        else:
            # Relative time (pulse) - data is in seconds
            item = NumericTableWidgetItem(f"{timestamp:.9f} s")

        item.setData(Qt.ItemDataRole.UserRole, timestamp)
        return item

    def _set_stats(self, idx, min_data, avg_data, max_data, first, last, samples, first_time, last_time, is_date,
                   impl_plot):
        """
            Set statistics row
        """
        self.table.setItem(idx, 1, self._create_item(min_data))
        self.table.setItem(idx, 2, self._create_item(avg_data))
        self.table.setItem(idx, 3, self._create_item(max_data))
        self.table.setItem(idx, 4, self._create_item(first))
        self.table.setItem(idx, 5, self._create_item(last))
        self.table.setItem(idx, 6, self._create_item(samples))
        self.table.setItem(idx, 7, self._create_timestamp_item(first_time, is_date, impl_plot))
        self.table.setItem(idx, 8, self._create_timestamp_item(last_time, is_date, impl_plot))

    def fill_table(self, info_stats: list):
        """
            Fill the statistics table with data for each signal.

            ``info_stats`` items are ``(signal, impl_plot, plot_id)`` tuples;
            ``plot_id`` is the (row, col) position of the signal's plot in the
            canvas grid, used to label the signal name with the same Stack
            convention shown in the variables config.
        """
        self.table.setRowCount(0)
        self._current_info_stats = info_stats
        idx = 0

        for signal, impl_plot, plot_id in info_stats:
            lines = signal.lines
            stack = self._format_plot_id(plot_id)
            has_envelope = signal.data_store[2].size > 0 and signal.data_store[3].size > 0

            for line in lines:
                # Insert new row
                self.table.insertRow(idx)

                # Add Statistics to the table
                if has_envelope > 0:
                    line = line[0]

                    # Differentiate methods
                    if isinstance(impl_plot, PlotItem):
                        x_data = line.getData()[0]
                        lo, hi = impl_plot.getViewBox().viewRange()[0]
                        y_lo, y_hi = impl_plot.getViewBox().viewRange()[1]
                        signal_name = f"{line.name()}, {stack}"
                    else:
                        x_data = line.get_xdata()
                        lo, hi = impl_plot.get_xlim()
                        y_lo, y_hi = impl_plot.get_ylim()
                        signal_name = f"{line.get_label()}, {stack}"

                    # The rows correspond to the signals and their corresponding stacks
                    self.table.setItem(idx, 0, QTableWidgetItem(signal_name))

                    x_data = np.asarray(x_data)
                    y_min = np.array(signal.data_store[1])
                    y_max = np.array(signal.data_store[2])
                    y_mean = np.array(signal.data_store[3])

                    # Filter values
                    mask = ((x_data >= lo) & (x_data <= hi) &
                            (y_min >= y_lo) & (y_min <= y_hi) &
                            (y_mean >= y_lo) & (y_mean <= y_hi) &
                            (y_max >= y_lo) & (y_max <= y_hi))

                    y_min_displayed = y_min[mask]
                    y_max_displayed = y_max[mask]
                    y_mean_displayed = y_mean[mask]
                    samples = y_mean_displayed.size

                    if samples > 0:
                        # NumPy scalars → float
                        min_val = np.min(y_min_displayed).item()
                        avg_val = np.mean(y_mean_displayed).item()
                        max_val = np.max(y_max_displayed).item()
                        first = (y_min_displayed[0].item(), y_mean_displayed[0].item(), y_max_displayed[0].item())
                        last = (y_min_displayed[-1].item(), y_mean_displayed[-1].item(), y_max_displayed[-1].item())

                        plot = signal.parent()

                        # Set timestamps
                        if isinstance(plot, (PlotXYWithSlider, PlotContourWithSlider)):
                            x_displayed = signal.time
                            init_val = plot.slider_last_min
                            end_val = plot.slider_last_val if plot.slider_last_val != 0 else plot.slider_last_max
                            is_date = bool(min(x_displayed) > (1 << 53) and max(x_displayed) < (1 << 62))
                        else:
                            x_displayed = x_data[mask]
                            init_val = 0
                            end_val = -1
                            is_date = plot.axes[0].is_date

                        if len(x_displayed) > 0:
                            first_time_raw = x_displayed[init_val].item()
                            last_time_raw = x_displayed[end_val].item()

                            # Apply inverse transformation if there's an offset
                            if hasattr(impl_plot, '_ipl_cache_item'):
                                ci = impl_plot._ipl_cache_item
                                offset = ci.offsets.get(0, 0) if hasattr(ci, 'offsets') else 0
                                if offset == 100_000:
                                    first_time = first_time_raw * offset
                                    last_time = last_time_raw * offset
                                elif offset != 0:
                                    first_time = first_time_raw + offset
                                    last_time = last_time_raw + offset
                                else:
                                    first_time = first_time_raw
                                    last_time = last_time_raw
                            else:
                                first_time = first_time_raw
                                last_time = last_time_raw
                        else:
                            first_time = 0
                            last_time = 0

                        # Set statistics
                        self._set_stats(idx, min_val, avg_val, max_val, first, last, samples, first_time, last_time,
                                        is_date, impl_plot)
                    else:
                        # Indicate that there is no data
                        self.table.setItem(idx, 6, self._create_item(samples))

                else:
                    # Base case
                    # Differentiate methods
                    if isinstance(impl_plot, PlotItem):
                        x_data = line.getData()[0] if line.getData()[0] is not None else []
                        y_data = line.getData()[1] if line.getData()[1] is not None else []
                        lo, hi = impl_plot.getViewBox().viewRange()[0]
                        y_lo, y_hi = impl_plot.getViewBox().viewRange()[1]
                        signal_name = f"{line.name()}, {stack}"
                    else:
                        x_data = line.get_xdata()
                        y_data = line.get_ydata()
                        lo, hi = impl_plot.get_xlim()
                        y_lo, y_hi = impl_plot.get_ylim()
                        signal_name = f"{line.get_label()}, {stack}"

                    # The rows correspond to the signals and their corresponding stacks
                    self.table.setItem(idx, 0, QTableWidgetItem(signal_name))

                    x_data = np.asarray(x_data)
                    y_data = np.asarray(y_data)

                    # Filter values
                    if (len(x_data), len(y_data)) != (0, 0):
                        mask = ((x_data >= lo) & (x_data <= hi) & (y_data >= y_lo) & (y_data <= y_hi))
                        y_displayed = y_data[mask]
                        samples = y_displayed.size
                    else:
                        samples = 0

                    if samples > 0:
                        # NumPy scalars → float
                        min_val = np.min(y_displayed).item()
                        avg_val = np.mean(y_displayed).item()
                        max_val = np.max(y_displayed).item()
                        first_val = y_displayed[0].item()
                        last_val = y_displayed[-1].item()

                        plot = signal.parent()

                        # Set timestamps
                        if isinstance(plot, (PlotXYWithSlider, PlotContourWithSlider)):
                            x_displayed = signal.time
                            init_val = plot.slider_last_min
                            end_val = plot.slider_last_val if plot.slider_last_val != 0 else plot.slider_last_max
                            is_date = bool(min(x_displayed) > (1 << 53) and max(x_displayed) < (1 << 62))
                        else:
                            x_displayed = x_data[mask]
                            init_val = 0
                            end_val = -1
                            is_date = plot.axes[0].is_date

                        if len(x_displayed) > 0:
                            first_time_raw = x_displayed[init_val].item()
                            last_time_raw = x_displayed[end_val].item()

                            # Apply inverse transformation if there's an offset
                            if hasattr(impl_plot, '_ipl_cache_item'):
                                ci = impl_plot._ipl_cache_item
                                offset = ci.offsets.get(0, 0) if hasattr(ci, 'offsets') else 0
                                if offset == 100_000:
                                    first_time = first_time_raw * offset
                                    last_time = last_time_raw * offset
                                elif offset != 0:
                                    first_time = first_time_raw + offset
                                    last_time = last_time_raw + offset
                                else:
                                    first_time = first_time_raw
                                    last_time = last_time_raw
                            else:
                                first_time = first_time_raw
                                last_time = last_time_raw
                        else:
                            first_time = 0
                            last_time = 0

                        # Set statistics
                        self._set_stats(idx, min_val, avg_val, max_val, first_val, last_val, samples, first_time,
                                        last_time, is_date, impl_plot)
                    else:
                        # Indicate that there is no data
                        self.table.setItem(idx, 6, self._create_item(samples))

                idx += 1

        # Apply formatting with the current decimal setting
        self.update_table_format()

        # Adjust columns to content
        self.adjust_columns()

    def adjust_columns(self):
        """
        Adjust column widths to fit their contents
        """
        for column in range(self.table.columnCount()):
            self.table.resizeColumnToContents(column)

    def update_table_format(self):
        """
            Updates the float value format based on the selected number of decimals
        """
        self.decimal_digits = self.adjust_decimals.value()
        rows = self.table.rowCount()
        cols = self.table.columnCount()

        for row in range(rows):
            for col in range(1, cols):
                # Skip timestamp columns
                if col in [7, 8]:
                    continue
                item = self.table.item(row, col)
                if item is not None:
                    data = item.data(Qt.ItemDataRole.UserRole)

                    # Format tuple of value in case of envelope
                    if isinstance(data, tuple):
                        text_parts = []
                        for val in data:
                            if not float(val).is_integer():
                                text_parts.append(f"{val:.{self.decimal_digits}f}")
                            else:
                                text_parts.append(f"{int(val)}")
                        text = f"({', '.join(text_parts)})"
                        item.setText(text)

                    # Format single float value
                    elif isinstance(data, (int, float)):
                        if not float(data).is_integer():
                            item.setText(f"{data:.{self.decimal_digits}f}")
                        else:
                            item.setText(str(int(data)))

    def keyPressEvent(self, event):
        if event.matches(QKeySequence.StandardKey.Copy):
            self._copy_selection()
        else:
            super().keyPressEvent(event)

    def _copy_selection(self):
        """Copy selected cells to clipboard as tab-separated text."""
        selection = self.table.selectedIndexes()
        if not selection:
            return

        rows = sorted(set(idx.row() for idx in selection))
        cols = sorted(set(idx.column() for idx in selection))

        lines = []
        # Include headers if multiple columns selected
        if len(cols) > 1:
            headers = [self.column_names[c] for c in cols]
            lines.append('\t'.join(headers))

        for row in rows:
            cells = []
            for col in cols:
                item = self.table.item(row, col)
                cells.append(item.text() if item else '')
            lines.append('\t'.join(cells))

        QApplication.clipboard().setText('\n'.join(lines))

    def _export_csv(self):
        """Export visible columns of the table to a CSV file."""
        filename, _ = QFileDialog.getSaveFileName(self, "Export Statistics as CSV", "", "CSV Files (*.csv)")
        if not filename:
            return
        if not filename.lower().endswith('.csv'):
            filename += '.csv'

        visible_cols = [c for c in range(self.table.columnCount()) if not self.table.isColumnHidden(c)]

        try:
            with open(filename, 'w', newline='', encoding='utf-8-sig') as f:
                writer = csv.writer(f, delimiter=';')
                writer.writerow([self.column_names[c] for c in visible_cols])
                for row in range(self.table.rowCount()):
                    row_data = []
                    for col in visible_cols:
                        item = self.table.item(row, col)
                        row_data.append(item.text() if item else '')
                    writer.writerow(row_data)
            logger.info(f"Exported statistics to {filename}")
        except Exception as e:
            logger.error(f"Failed to export CSV: {e}")
            QMessageBox.critical(self, "Export Error", f"Cannot export to file: {filename}\n{e}")

    def _show_context_menu(self, pos):
        """Right-click context menu with Copy and Export CSV."""
        menu = QMenu(self)
        copy_action = menu.addAction("Copy")
        copy_action.setShortcut(QKeySequence.StandardKey.Copy)
        export_action = menu.addAction("Export CSV")

        action = menu.exec(self.table.viewport().mapToGlobal(pos))
        if action == copy_action:
            self._copy_selection()
        elif action == export_action:
            self._export_csv()
