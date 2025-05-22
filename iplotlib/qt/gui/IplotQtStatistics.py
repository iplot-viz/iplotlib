import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem, QHeaderView, \
    QAbstractItemView, QPushButton, QMenu, QSpinBox, QLabel, QFrame

import iplotLogging.setupLogger as Sl

logger = Sl.get_logger(__name__)


class IplotQtStatistics(QWidget):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.resize(1050, 500)
        self.setWindowTitle("Statistics table")

        self.column_names = ['Signal name', 'Min', 'Avg', 'Max', 'First', 'Last', 'Samples']

        # Marker table creation
        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels(self.column_names)

        # Disable cell modification
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)

        # Row selection for the table
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)

        # Adjust column width dynamically
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)

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
            item.setData(Qt.UserRole, value)
        elif isinstance(value, tuple):
            val = f"({', '.join(fmt(v) for v in value)})"
            item = QTableWidgetItem(val)
            item.setData(Qt.UserRole, value)
        else:
            item = QTableWidgetItem(fmt(value))
            item.setData(Qt.UserRole, float(value))

        return item

    def _set_stats(self, idx, min_data, avg_data, max_data, first, last, samples):
        """
            Set statistic row
        """
        self.table.setItem(idx, 1, self._create_item(min_data))
        self.table.setItem(idx, 2, self._create_item(avg_data))
        self.table.setItem(idx, 3, self._create_item(max_data))
        self.table.setItem(idx, 4, self._create_item(first))
        self.table.setItem(idx, 5, self._create_item(last))
        self.table.setItem(idx, 6, self._create_item(samples))

    def fill_table(self, info_stats: list):
        """
            Fill the statistics table with data for each signal
        """
        self.table.setRowCount(0)
        self._current_info_stats = info_stats

        for idx, (signal, impl_plot) in enumerate(info_stats):
            # Insert new row
            self.table.insertRow(idx)

            # The rows correspond to the signals and their corresponding stacks
            stack = f"{signal.parent.id[0]}.{signal.parent.id[1]}.{signal.id}"
            signal_name = f"{signal.label}, {stack}"
            self.table.setItem(idx, 0, QTableWidgetItem(signal_name))

            # Add Statistics to the table
            has_envelope = signal.data_store[2].size > 0 and signal.data_store[3].size > 0
            line = signal.lines[0][0]
            x_data = line.get_xdata()
            lo, hi = impl_plot.get_xlim()

            if has_envelope > 0:
                y_min = np.array(signal.data_store[1])
                y_max = np.array(signal.data_store[2])
                y_mean = np.array(signal.data_store[3])

                # Filter values
                mask = (x_data > lo) & (x_data < hi)
                y_min_displayed = y_min[mask]
                y_max_displayed = y_max[mask]
                y_mean_displayed = y_mean[mask]
                samples = np.size(y_mean_displayed)

                if samples > 0:
                    min_val, avg_val, max_val = np.min(y_min_displayed), np.mean(y_mean_displayed), np.max(
                        y_max_displayed)
                    first = (y_min_displayed[0], y_mean_displayed[0], y_max_displayed[0])
                    last = (y_min_displayed[-1], y_mean_displayed[-1], y_max_displayed[-1])
                    self._set_stats(idx, min_val, avg_val, max_val, first, last, samples)
                else:
                    # Indicate that there is no data
                    self.table.setItem(idx, 6, self._create_item(samples))

            else:
                # Base case
                y_data = line.get_ydata()
                y_displayed = y_data[((x_data > lo) & (x_data < hi))]
                samples = np.size(y_displayed)

                if samples > 0:
                    min_val, avg_val, max_val = np.min(y_displayed)[0], np.mean(y_displayed)[0], np.max(y_displayed)[0]
                    first_val, last_val = y_displayed[0], y_displayed[-1]
                    samples = np.size(y_displayed)

                    self._set_stats(idx, min_val, avg_val, max_val, first_val, last_val, samples)
                else:
                    # Indicate that there is no data
                    self.table.setItem(idx, 6, self._create_item(samples))
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
                item = self.table.item(row, col)
                if item is not None:
                    data = item.data(Qt.UserRole)

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
