from string import ascii_uppercase
import pandas as pd
from PySide6.QtWidgets import QWidget, QVBoxLayout, QPushButton, QHBoxLayout, QTableWidget, QTableWidgetItem, \
    QHeaderView, QMessageBox, QAbstractItemView, QCheckBox, QColorDialog
from PySide6.QtCore import Qt, Signal
import iplotLogging.setupLogger as Sl
from iplotlib.core import SignalXY
from iplotlib.core.marker import Marker

logger = Sl.get_logger(__name__)


class IplotQtMarker(QWidget):
    dropMarker = Signal(object, object, object, object, object, object)
    deleteMarker = Signal(object, object, object, object)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.resize(850, 500)
        self.setWindowTitle("Markers window")

        self.markers = []
        self.signals = []
        self.selection_history = []
        self.count = 0
        self.markers_visible = False

        # Marker table creation
        self.table = QTableWidget()
        # self.table = QTableView()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(['Marker', 'Stack', 'Signal name', '(X,Y) values', 'Visible', 'Color'])

        # Disable cell modification
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)

        # Row selection for the table
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)

        # Adjust column width dynamically
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setStretchLastSection(True)

        # Connect selection event
        self.table.selectionModel().selectionChanged.connect(self.update_selection_history)

        # Buttons
        self.remove_button = QPushButton("Remove marker")
        self.compute_dist = QPushButton("Compute distance")

        # Slots
        self.remove_button.pressed.connect(self.remove_markers)
        self.compute_dist.pressed.connect(self.compute_distance)

        # Layout
        main_v_layout = QVBoxLayout()
        top_v_layout = QVBoxLayout()
        top_v_layout.addWidget(self.table)
        bot_h_layout = QHBoxLayout()
        bot_h_layout.addWidget(self.remove_button)
        bot_h_layout.addWidget(self.compute_dist)

        main_v_layout.addLayout(top_v_layout)
        main_v_layout.addLayout(bot_h_layout)
        self.setLayout(main_v_layout)

    def update_selection_history(self):
        selected_rows = [index.row() for index in self.table.selectionModel().selectedRows()]

        # Keep the original selection order
        for row in selected_rows:
            if row not in self.selection_history:
                self.selection_history.append(row)

        # If the user cancels the selection, remove it from the history
        self.selection_history = [row for row in self.selection_history if row in selected_rows]

    def add_marker(self, signal, marker_coordinates):
        """
        Adds to the table the necessary information about the markers
        """

        row_pos = self.table.rowCount()
        self.table.insertRow(row_pos)

        # Add marker
        self.markers.append(marker_coordinates)

        # Add signal
        self.signals.append(signal.uid)

        "Creation of QTableWidgetItem for each column"
        # 1- Marker name
        marker_name = ascii_uppercase[self.count % len(ascii_uppercase)]
        is_date = signal.parent.axes[0].is_date
        marker_data = QTableWidgetItem(marker_name)
        marker_data.setData(Qt.UserRole, is_date)

        # 2- Signal stack
        id_plot = signal.parent.id
        id_signal = signal.id
        marker_id = [id_plot[0], id_plot[1], id_signal]
        stack = f"{id_plot[0]}.{id_plot[1]}.{id_signal}"
        plot_data = QTableWidgetItem(stack)
        plot_data.setData(Qt.UserRole, marker_id)

        # 3- Signal name
        signal_data = QTableWidgetItem(signal.label)
        signal_data.setData(Qt.UserRole, signal.uid)

        # 4- Marker coordinates
        if is_date:
            coord_data = QTableWidgetItem(f"({pd.Timestamp(marker_coordinates[0])}, {marker_coordinates[1]})")
        else:
            coord_data = QTableWidgetItem(f"({marker_coordinates[0]}, {marker_coordinates[1]})")
        coord_data.setData(Qt.UserRole, marker_coordinates)

        # 5- Visibility checkbox
        visible = QCheckBox()
        visible.setChecked(False)
        visible.stateChanged.connect(
            lambda state: self.toggle_marker_visibility(self.table.indexAt(visible.pos()).row(), state))

        # 6- Marker color
        color_button = QPushButton("Select color")
        color_button.setStyleSheet(f"background-color: #FFFFFF; border: 1px solid black")
        color_button.clicked.connect(
            lambda: self.change_marker_color(self.table.indexAt(color_button.pos()).row(), color_button))

        # Finally, create marker instance and add it to signal markers list
        marker = Marker(marker_name, marker_coordinates, "#FFFFFF", False)
        signal.add_marker(marker)

        "Set data in table"
        self.table.setItem(row_pos, 0, marker_data)
        self.table.setItem(row_pos, 1, plot_data)
        self.table.setItem(row_pos, 2, signal_data)
        self.table.setItem(row_pos, 3, coord_data)
        self.table.setCellWidget(row_pos, 4, visible)
        self.table.setCellWidget(row_pos, 5, color_button)
        self.count += 1

    def change_marker_color(self, row, button):
        current_color = button.palette().button().color()
        new_color = QColorDialog.getColor(current_color, self)

        if new_color.isValid():
            new_marker_color = new_color.name()
            button.setStyleSheet(f"background-color: {new_marker_color}; border: 1px solid black")

            # If marker is visible
            visible = self.table.cellWidget(row, 4)
            if visible.isChecked():
                marker_name = self.table.item(row, 0).text()
                plot_id = self.table.item(row, 1).data(Qt.UserRole)
                signal = self.table.item(row, 2).data(Qt.UserRole)
                xy = self.table.item(row, 3).data(Qt.UserRole)
                self.dropMarker.emit(marker_name, plot_id[:2], signal, xy, new_marker_color, True)

    def remove_markers(self):
        # Remove the selected markers from the table
        ordered_rows = sorted(self.selection_history, reverse=True)
        for row in ordered_rows:
            # Delete marker from signal markers list
            marker_name = self.table.item(row, 0).text()
            plot_id = self.table.item(row, 1).data(Qt.UserRole)
            signal = self.table.item(row, 2).data(Qt.UserRole)
            self.deleteMarker.emit(marker_name, plot_id[:2], signal, True)

            # Delete from table and from markers list
            self.table.removeRow(row)
            self.markers.pop(row)
            # Delete signal
            self.signals.remove(signal)

    def toggle_marker_visibility(self, row, state):
        is_visible = state == Qt.Checked.value
        marker_name = self.table.item(row, 0).text()
        plot_id = self.table.item(row, 1).data(Qt.UserRole)
        signal = self.table.item(row, 2).data(Qt.UserRole)

        if is_visible:
            xy = self.table.item(row, 3).data(Qt.UserRole)
            marker_color = self.table.cellWidget(row, 5).palette().button().color().name()
            self.dropMarker.emit(marker_name, plot_id[:2], signal, xy, marker_color, False)
        else:
            self.deleteMarker.emit(marker_name, plot_id[:2], signal, False)

    def compute_distance(self):
        # Check that only 2 rows are selected
        if len(self.selection_history) != 2:
            msg = "Invalid selection.\nSelect exactly 2 rows."
            box = QMessageBox()
            box.setIcon(QMessageBox.Icon.Warning)
            box.setWindowTitle("Error computing distance")
            box.setText(msg)
            logger.exception(msg)
            box.exec_()
            return

        # Get the markers
        row1, row2 = self.selection_history[-2:]

        # Get markers coordinates
        x1, y1 = self.table.item(row1, 3).data(Qt.UserRole)[0], self.table.item(row1, 3).data(Qt.UserRole)[1]
        x2, y2 = self.table.item(row2, 3).data(Qt.UserRole)[0], self.table.item(row2, 3).data(Qt.UserRole)[1]

        # Get markers name
        x1_name = self.table.item(row1, 0).text()
        x2_name = self.table.item(row2, 0).text()

        # Compute distance
        is_date = self.table.item(row1, 0).data(Qt.UserRole)
        if is_date:
            # Absolute difference for X axis
            dx = abs(pd.Timestamp(x2, unit='ns') - pd.Timestamp(x1, unit='ns'))
            dx_str = f"{dx.components.days}D" if dx.components.days else ""
            dx_str += f"T{dx.components.hours}H{dx.components.minutes}M{dx.components.seconds}S"
            if dx.components.nanoseconds:
                dx_str += f"+{dx.components.milliseconds}m"
                dx_str += f"+{dx.components.microseconds}u"
                dx_str += f"+{dx.components.nanoseconds}n"
            else:
                if dx.components.milliseconds:
                    dx_str += f"+{dx.components.milliseconds}m"
                if dx.components.microseconds:
                    dx_str += f"+{dx.components.microseconds}u"
        else:
            # Relative markers coordinates
            dx = abs(x2 - x1)
            dx_str = f"{dx}"

        dy = abs(y2 - y1)

        # Show distance
        msg_result = (f"The precise distance between the markers {x1_name} and {x2_name} is:\n"
                      f"dx = {dx_str}\ndy = {dy}")
        box = QMessageBox()
        box.setIcon(QMessageBox.Icon.Information)
        box.setWindowTitle("Distance calculated")
        box.setText(msg_result)
        logger.info(msg_result)
        box.exec_()
        return

    def get_markers(self):
        return self.markers

    def clear_info(self):
        self.table.setRowCount(0)
        self.markers.clear()
        self.signals.clear()
        self.count = 0

    def get_markers_signal(self):
        return set(self.signals)

    def remove_signal(self, signal):
        delete_rows = []

        for row in range(self.table.rowCount()):
            if self.table.item(row, 2).data(Qt.UserRole) == signal:
                delete_rows.append(row)

        for row in sorted(delete_rows, reverse=True):
            self.table.removeRow(row)

    def get_stack(self, signal):
        for row in range(self.table.rowCount()):
            if self.table.item(row, 2).data(Qt.UserRole) == signal:
                return self.table.item(row, 1).text()

    def refresh_stack(self, signal: SignalXY, stack: str):
        # New Signal stack
        marker_id = [signal.parent.id[0], signal.parent.id[1], signal.id]

        for row in range(self.table.rowCount()):
            if self.table.item(row, 2).data(Qt.UserRole) == signal.uid:
                plot_data = self.table.item(row, 1)
                plot_data.setText(stack)
                plot_data.setData(Qt.UserRole, marker_id)

    def import_table(self, signal: SignalXY):
        id_plot = signal.parent.id
        id_signal = signal.id
        id_marker = [id_plot[0], id_plot[1], id_signal]
        stack = f"{id_plot[0]}.{id_plot[1]}.{id_signal}"
        is_date = signal.parent.axes[0].is_date

        for marker in signal.markers_list:
            row_pos = self.table.rowCount()
            self.table.insertRow(row_pos)

            # Add marker
            self.markers.append(marker.xy)

            # Add signal
            self.signals.append(signal.uid)

            "Creation of QTableWidgetItem for each column"
            # 1- Marker name
            marker_data = QTableWidgetItem(marker.name)
            marker_data.setData(Qt.UserRole, is_date)

            # 2- Signal stack
            plot_data = QTableWidgetItem(stack)
            plot_data.setData(Qt.UserRole, id_marker)

            # 3- Signal name
            signal_data = QTableWidgetItem(signal.label)
            signal_data.setData(Qt.UserRole, signal.uid)

            # 4- Marker coordinates
            if is_date:
                coord_data = QTableWidgetItem(f"({pd.Timestamp(marker.xy[0])}, {marker.xy[1]})")
            else:
                coord_data = QTableWidgetItem(f"({marker.xy[0]}, {marker.xy[1]})")
            coord_data.setData(Qt.UserRole, marker.xy)

            # 5- Visibility checkbox
            visible = QCheckBox()
            visible.setChecked(marker.visible)
            visible.stateChanged.connect(
                lambda state, checkbox=visible: self.toggle_marker_visibility(self.table.indexAt(checkbox.pos()).row(),
                                                                              state))

            # 6- Marker color
            color_button = QPushButton("Select color")
            color_button.setStyleSheet(f"background-color: {marker.color}; border: 1px solid black")
            color_button.clicked.connect(
                lambda checked=True, btn=color_button: self.change_marker_color(self.table.indexAt(btn.pos()).row(),
                                                                                btn))

            # Set data in table
            self.table.setItem(row_pos, 0, marker_data)
            self.table.setItem(row_pos, 1, plot_data)
            self.table.setItem(row_pos, 2, signal_data)
            self.table.setItem(row_pos, 3, coord_data)
            self.table.setCellWidget(row_pos, 4, visible)
            self.table.setCellWidget(row_pos, 5, color_button)

        # Update marker count
        if signal.markers_list:
            last_name = signal.markers_list[-1].name
            self.count = ascii_uppercase.find(last_name) + 1
