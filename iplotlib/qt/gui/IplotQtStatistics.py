import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem, QHeaderView, \
    QAbstractItemView, QPushButton, QMenu, QSpinBox, QLabel, QFrame

import iplotLogging.setupLogger as Sl
from pyqtgraph import PlotItem

from iplotlib.core import PlotXYWithSlider, PlotContourWithSlider
from iplotlib.impl.matplotlib.dateFormatter import NanosecondDateFormatter as MPLDateFormatter
from iplotlib.impl.pyqtgraph.dateFormatter import NanosecondDateFormatter as PGDateFormatter

logger = Sl.get_logger(__name__)


class IplotQtStatistics(QWidget):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.resize(1050, 500)
        self.setWindowTitle("Statistics table")

        self.column_names = ['Signal name', 'Min', 'Avg', 'Max', 'First', 'Last', 'Samples', 'First Time', 'Last Time']

        # Marker table creation
        self.table = QTableWidget()
        self.table.setColumnCount(9)
        self.table.setHorizontalHeaderLabels(self.column_names)

        # Disable cell modification
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)

        # Row selection for the table
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)

        # Adjust column width dynamically
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)

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
        self.adjust_decimals.setValue(17)
        self.decimal_digits = self.adjust_decimals.value()
        self.apply_decimals_button = QPushButton("Apply")
        self.apply_decimals_button.clicked.connect(self.update_table_format)

        # Add button and table to layout
        top_layout_with_button.addWidget(self.column_menu_button)
        top_layout_with_button.addWidget(self.decimals)
        top_layout_with_button.addWidget(self.adjust_decimals)
        top_layout_with_button.addWidget(self.apply_decimals_button)
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

    def _format_float(self, value):
        """
            Format float: show as integer if no decimals
        """
        return int(value) if value.is_integer() else value

    def _create_item(self, value):
        """
        Creates QTableWidgetItem and set data with formatting applied
        """
        digits = self.decimal_digits

        def fmt(val):
            return f"{val:.{digits}f}" if not float(val).is_integer() else str(int(val))

        if isinstance(value, float):
            item = QTableWidgetItem(fmt(value))
            item.setData(Qt.ItemDataRole.UserRole, value)
        elif isinstance(value, tuple):
            val = f"({', '.join(fmt(v) for v in value)})"
            item = QTableWidgetItem(val)
            item.setData(Qt.ItemDataRole.UserRole, value)
        else:
            item = QTableWidgetItem(fmt(value))
            item.setData(Qt.ItemDataRole.UserRole, float(value))

        return item

    def _create_timestamp_item(self, timestamp, is_date, impl_plot):
        """
        Creates QTableWidgetItem for timestamp with proper formatting
        """
        if is_date:
            # Use the appropriate formatter based on backend
            if isinstance(impl_plot, PlotItem):
                formatter = PGDateFormatter(orientation='bottom')
            else:
                formatter = MPLDateFormatter(ax_idx=0)

            # Format the timestamp to human readable
            formatted = formatter.date_fmt(int(timestamp), formatter.YEAR, formatter.NANOSECOND, postfix_end=True)
            item = QTableWidgetItem(formatted)
        else:
            # Relative time (pulse) - data comes in milliseconds
            seconds = timestamp / 1000.0  # Convert from milliseconds to seconds
            item = QTableWidgetItem(f"{seconds:.9f} s")

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
            Fill the statistics table with data for each signal
        """
        self.table.setRowCount(0)
        self._current_info_stats = info_stats
        idx = 0

        for signal, impl_plot in info_stats:
            lines = signal.lines
            stack = signal.get_stack()
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
                    mask = ((x_data > lo) & (x_data < hi) &
                            (y_min > y_lo) & (y_min < y_hi) &
                            (y_mean > y_lo) & (y_mean < y_hi) &
                            (y_max > y_lo) & (y_max < y_hi))

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
                        mask = ((x_data > lo) & (x_data < hi) & (y_data > y_lo) & (y_data < y_hi))
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
                    else:
                        if not float(data).is_integer():
                            item.setText(f"{data:.{self.decimal_digits}f}")
                        else:
                            item.setText(str(int(data)))
