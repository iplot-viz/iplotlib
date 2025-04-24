import numpy as np
from PySide6.QtWidgets import QWidget, QVBoxLayout, QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView
import iplotLogging.setupLogger as Sl
from iplotlib.core import SignalXY

logger = Sl.get_logger(__name__)


class IplotQtStatistics(QWidget):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.resize(1050, 500)
        self.setWindowTitle("Statistics table")

        self.markers = []
        self.signals = []
        self.selection_history = []
        self.count = 0
        self.markers_visible = False

        # Marker table creation
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(['Min', 'Avg', 'Max', 'First', 'Last'])

        # Disable cell modification
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)

        # Row selection for the table
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)

        # Adjust column width dynamically
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        # header.setStretchLastSection(True)

        # Connect selection event
        # self.table.selectionModel().selectionChanged.connect(self.update_selection_history)

        # Layout
        main_v_layout = QVBoxLayout()
        top_v_layout = QVBoxLayout()
        top_v_layout.addWidget(self.table)

        main_v_layout.addLayout(top_v_layout)
        self.setLayout(main_v_layout)

    def fill_table(self, signals: list):
        self.table.setRowCount(0)
        signal_labels = []
        for idx, signal in enumerate(signals):
            if isinstance(signal, SignalXY):
                # Insert row
                self.table.insertRow(idx)

                # The rows correspond to the signals and their corresponding stacks
                stack = f"{signal.parent.id[0]}.{signal.parent.id[1]}.{signal.id}"
                signal_name = f"{signal.label}, {stack}"
                signal_labels.append(signal_name)

                # Envelope case
                if signal.data_store[2].size > 0 and signal.data_store[3].size > 0:
                    y_min = np.array(signal.data_store[1])
                    y_max = np.array(signal.data_store[2])
                    y_mean = np.array(signal.data_store[3])

                    min_data = QTableWidgetItem(f"{np.min(y_min)}")
                    avg_data = QTableWidgetItem(f"{np.mean(y_mean)}")
                    max_data = QTableWidgetItem(f"{np.max(y_max)}")
                    first_data = QTableWidgetItem(f"({y_min[0]}, {y_mean[0]}, {y_max[0]})")
                    last_data = QTableWidgetItem(f"({y_min[-1]}, {y_mean[-1]}, {y_max[-1]})")
                    self.table.setItem(idx, 0, min_data)
                    self.table.setItem(idx, 1, avg_data)
                    self.table.setItem(idx, 2, max_data)
                    self.table.setItem(idx, 3, first_data)
                    self.table.setItem(idx, 4, last_data)

                else:
                    min_data = QTableWidgetItem(f"{np.min(signal.y_data)[0]}")
                    avg_data = QTableWidgetItem(f"{np.mean(signal.y_data)[0]}")
                    max_data = QTableWidgetItem(f"{np.max(signal.y_data)[0]}")
                    first_data = QTableWidgetItem(f"{signal.y_data[0]}")
                    last_data = QTableWidgetItem(f"{signal.y_data[-1]}")
                    self.table.setItem(idx, 0, min_data)
                    self.table.setItem(idx, 1, avg_data)
                    self.table.setItem(idx, 2, max_data)
                    self.table.setItem(idx, 3, first_data)
                    self.table.setItem(idx, 4, last_data)

        self.table.setVerticalHeaderLabels(signal_labels)
