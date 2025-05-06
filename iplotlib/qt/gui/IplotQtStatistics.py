import numpy as np
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem, QHeaderView, \
    QAbstractItemView, QPushButton, QMenu
import iplotLogging.setupLogger as Sl

logger = Sl.get_logger(__name__)


class IplotQtStatistics(QWidget):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.resize(1050, 500)
        self.setWindowTitle("Statistics table")

        self.column_names = ['Min', 'Avg', 'Max', 'First', 'Last', 'Samples']

        # Marker table creation
        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(self.column_names)

        # Disable cell modification
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)

        # Row selection for the table
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)

        # Adjust column width dynamically
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        # header.setStretchLastSection(True)

        # Layout
        main_v_layout = QVBoxLayout()
        top_v_layout = QVBoxLayout()
        top_layout_with_button = QHBoxLayout()

        # Button and menu to toggle column visibility
        self.column_menu_button = QPushButton("Hide/Show Columns")
        self.column_menu = QMenu()

        for i, name in enumerate(self.column_names):
            action = QAction(name, self)
            action.setCheckable(True)
            action.setChecked(True)
            action.toggled.connect(lambda checked, col=i: self.table.setColumnHidden(col, not checked))
            self.column_menu.addAction(action)

        self.column_menu_button.setMenu(self.column_menu)

        # Add button and table to layout
        top_layout_with_button.addWidget(self.column_menu_button)
        top_layout_with_button.addStretch()

        top_v_layout.addLayout(top_layout_with_button)
        top_v_layout.addWidget(self.table)

        main_v_layout.addLayout(top_v_layout)
        self.setLayout(main_v_layout)

    def fill_table(self, info_stats: list):
        self.table.setRowCount(0)
        signal_labels = []
        for idx, signal_impl in enumerate(info_stats):
            signal = signal_impl[0]
            impl_plot = signal_impl[1]

            # Insert row
            self.table.insertRow(idx)

            # The rows correspond to the signals and their corresponding stacks
            stack = f"{signal.parent.id[0]}.{signal.parent.id[1]}.{signal.id}"
            signal_name = f"{signal.label}, {stack}"
            signal_labels.append(signal_name)

            if signal.data_store[2].size > 0 and signal.data_store[3].size > 0:
                # Envelope case
                line = signal.lines[0][0]
                x_data = line.get_xdata()
                lo, hi = impl_plot.get_xlim()
                y_min = np.array(signal.data_store[1])
                y_max = np.array(signal.data_store[2])
                y_mean = np.array(signal.data_store[3])
                y_min_displayed = y_min[((x_data > lo) & (x_data < hi))]
                y_max_displayed = y_max[((x_data > lo) & (x_data < hi))]
                y_mean_displayed = y_mean[((x_data > lo) & (x_data < hi))]

                if np.size(y_min_displayed) > 0:
                    min_data = QTableWidgetItem(f"{np.min(y_min_displayed)}")
                    avg_data = QTableWidgetItem(f"{np.mean(y_mean_displayed)}")
                    max_data = QTableWidgetItem(f"{np.max(y_max_displayed)}")
                    first_data = QTableWidgetItem(
                        f"({y_min_displayed[0]}, {y_mean_displayed[0]}, {y_max_displayed[0]})")
                    last_data = QTableWidgetItem(
                        f"({y_min_displayed[-1]}, {y_mean_displayed[-1]}, {y_max_displayed[-1]})")
                    points_data = QTableWidgetItem(f"{np.size(y_mean)}")
                    self.table.setItem(idx, 0, min_data)
                    self.table.setItem(idx, 1, avg_data)
                    self.table.setItem(idx, 2, max_data)
                    self.table.setItem(idx, 3, first_data)
                    self.table.setItem(idx, 4, last_data)
                    self.table.setItem(idx, 5, points_data)
                else:
                    # Indicate that there is no data
                    points_data = QTableWidgetItem(f"{np.size(y_min_displayed)}")
                    self.table.setItem(idx, 5, points_data)

            else:
                # Base case
                line = signal.lines[0][0]
                x_data = line.get_xdata()
                y_data = line.get_ydata()
                lo, hi = impl_plot.get_xlim()
                y_displayed = y_data[((x_data > lo) & (x_data < hi))]

                if np.size(y_displayed) > 0:
                    min_data = QTableWidgetItem(f"{np.min(y_displayed)[0]}")
                    avg_data = QTableWidgetItem(f"{np.mean(y_displayed)[0]}")
                    max_data = QTableWidgetItem(f"{np.max(y_displayed)[0]}")
                    first_data = QTableWidgetItem(f"{y_displayed[0]}")
                    last_data = QTableWidgetItem(f"{y_displayed[-1]}")
                    points_data = QTableWidgetItem(f"{np.size(y_displayed)}")
                    self.table.setItem(idx, 0, min_data)
                    self.table.setItem(idx, 1, avg_data)
                    self.table.setItem(idx, 2, max_data)
                    self.table.setItem(idx, 3, first_data)
                    self.table.setItem(idx, 4, last_data)
                    self.table.setItem(idx, 5, points_data)

                else:
                    # Indicate that there is no data
                    points_data = QTableWidgetItem(f"{np.size(y_displayed)}")
                    self.table.setItem(idx, 5, points_data)

        if signal_labels:
            self.table.setVerticalHeaderLabels(signal_labels)
