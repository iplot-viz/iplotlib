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
    dropMarker = Signal(object, object, object, object)
    deleteMarker = Signal(object, object)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.resize(700, 500)
        self.setWindowTitle("Markers window")

        self.markers = []
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

        # Edit color
        self.table.cellDoubleClicked.connect(self.edit_marker_color)

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
        Adds to the table the necessary information about the markers.
            - The 'Marker' column stores the name of each marker as well as the points (x,y) of the marker after 
            zooming in.    
            - The 'Stack' column stores the stack corresponding to the plot.
            - In the column 'Signal name' is stored the signal where the marker is created.
            - In the column '(X,Y) values' is stored the point (x,y) corresponding to the nearest point of the signal 
            with the transformed coordinates by adding the corresponding offset.
        """

        row_pos = self.table.rowCount()
        self.table.insertRow(row_pos)
        # Add marker
        self.markers.append(marker_coordinates)
        # Insert data in table
        marker_name = ascii_uppercase[self.count % len(ascii_uppercase)]
        marker_data = QTableWidgetItem(marker_name)  # Marker name

        stack = f"{signal.parent.id[0]}.{signal.parent.id[1]}"
        plot_data = QTableWidgetItem(stack)  # Signal stack

        signal_data = QTableWidgetItem(signal.label)  # Signal name
        # Add marker instance to signal
        marker = Marker(marker_name, marker_coordinates, "#FFFFFF", False)
        signal.add_marker(marker)
        signal_data.setData(Qt.UserRole, signal)

        # Marker coordinates
        coord_data = QTableWidgetItem(f"({pd.Timestamp(marker_coordinates[0])}, {marker_coordinates[1]})")
        coord_data.setData(Qt.UserRole, marker_coordinates)

        # Visibility checkbox
        visible = QCheckBox()
        visible.setChecked(False)
        visible.stateChanged.connect(lambda state, row=row_pos: self.toggle_marker_visibility(row, state))

        # Marker color
        color_button = QPushButton("Select color")
        color_button.setStyleSheet(f"background-color: #FFFFFF; border: 1px solid black")
        color_button.clicked.connect(lambda: self.change_marker_color(row_pos, color_button))

        # Set data in table
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
            signal = self.table.item(row, 2).data(Qt.UserRole)
            signal.get_marker(row).color = new_marker_color

    def remove_markers(self):
        # Remove the selected markers from the table
        ordered_rows = sorted(self.selection_history, reverse=True)
        for row in ordered_rows:
            # Get correspondence signal
            signal = self.table.item(row, 2).data(Qt.UserRole)
            signal.delete_marker(row)
            # Delete from table and from markers list
            self.table.removeRow(row)
            self.markers.pop(row)

    def toggle_marker_visibility(self, row, state):
        is_visible = state == Qt.Checked.value
        signal = self.table.item(row, 2).data(Qt.UserRole)  # SignalXY
        if is_visible:
            marker_name = self.table.item(row, 0).text()  # Marker name
            xy = self.table.item(row, 3).data(Qt.UserRole)  # Real Coordinates
            marker_color = self.table.cellWidget(row, 5).palette().button().color().name()  # Color
            # Set marker visibility
            signal.get_marker(row).visible = True

            self.dropMarker.emit(marker_name, signal, xy, marker_color)
        else:
            marker_name = self.table.item(row, 0).text()  # Marker name
            # Set marker visibility
            signal.get_marker(row).visible = False

            self.deleteMarker.emit(marker_name, signal)

        # Update signal info
        self.table.item(row, 2).setData(Qt.UserRole, signal)

    def show_markers(self):
        # Check if markers are going to be displayed or if they are going to be hidden
        if self.markers_visible:
            self.hide_markers()
            return

        self.show_marker.setText('Hide markers')
        self.markers_visible = True
        self.table.setEnabled(False)

        for marker in self.selection_history:
            marker_name = self.table.item(marker, 0).text()  # Marker name
            xy = self.table.item(marker, 3).data(Qt.UserRole)  # Current coordinates
            signal = self.table.item(marker, 2).data(Qt.UserRole)  # SignalXY
            marker_color = self.table.cellWidget(marker, 4).palette().button().color().name()

            # Set marker visibility
            signal.get_marker(marker).visible = True

            self.dropMarker.emit(marker_name, signal, xy, marker_color)

    def hide_markers(self):
        self.show_marker.setText('Show markers')
        self.markers_visible = False
        self.table.setEnabled(True)

        for marker in self.selection_history:
            signal = self.table.item(marker, 2).data(Qt.UserRole)  # SignalXY

            # Set marker visibility
            signal.get_marker(marker).visible = False

            self.deleteMarker.emit(signal)

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
        dx_str = None
        is_date = self.table.item(row1, 2).data(Qt.UserRole).parent.axes[0].is_date
        if is_date:
            # Absolute difference for X axis
            dx = abs(pd.Timestamp(x2, unit='ns') - pd.Timestamp(x1, unit='ns'))
            dx_str = f"{dx.components.days}D" if dx.components.days else ""
            dx_str += f"T{dx.components.hours}H{dx.components.minutes}M{dx.components.seconds}S"
            if dx.components.nanoseconds:
                dx_str += f"+{dx.components.milliseconds}m"
                dx_str += f"+{dx.components.nanoseconds}n"
                dx_str += f"+{dx.components.microseconds}u"
            else:
                if dx.components.milliseconds:
                    dx_str += f"+{dx.components.milliseconds}m"
                if dx.components.microseconds:
                    dx_str += f"+{dx.components.microseconds}m"
        dy = y2 - y1

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

    def edit_marker_color(self, row, column):
        if column == 4:
            current_color = self.table.item(row, column).background().color()

            new_color = QColorDialog.getColor(current_color, self)

            if new_color.isValid():
                new_marker_color = new_color.name()
                color_data = QTableWidgetItem()
                color_data.setBackground(new_color)
                self.table.setItem(row, column, color_data)

    def clear_info(self):
        self.table.clear()
        self.table.setRowCount(0)
        self.markers.clear()
        self.count = 0

    def import_table(self, signal):
        # Clear
        self.clear_info()

        if isinstance(signal, SignalXY):
            for marker in signal.markers_list:
                row_pos = self.table.rowCount()
                self.table.insertRow(row_pos)

                # Add marker
                self.markers.append(marker.xy)

                # Insert data in table
                marker_name = marker.name
                marker_data = QTableWidgetItem(marker_name)  # Marker name

                stack = f"{signal.parent.id[0]}.{signal.parent.id[1]}"
                plot_data = QTableWidgetItem(stack)  # Signal stack

                signal_data = QTableWidgetItem(signal.label)  # Signal name
                signal_data.setData(Qt.UserRole, signal)

                # Marker coordinates
                coord_data = QTableWidgetItem(f"({pd.Timestamp(marker.xy[0])}, {marker.xy[1]})")
                coord_data.setData(Qt.UserRole, marker.xy)

                visible = QCheckBox()
                visible.setChecked(marker.visible)
                visible.stateChanged.connect(lambda state, row=row_pos: self.toggle_marker_visibility(row, state))

                # Marker color
                color_button = QPushButton("Select color")
                color_button.setStyleSheet(f"background-color: {marker.color}; border: 1px solid black")
                color_button.clicked.connect(lambda: self.change_marker_color(row_pos, color_button))

                # Set data in table
                self.table.setItem(row_pos, 0, marker_data)
                self.table.setItem(row_pos, 1, plot_data)
                self.table.setItem(row_pos, 2, signal_data)
                self.table.setItem(row_pos, 3, coord_data)
                self.table.setCellWidget(row_pos, 4, visible)
                self.table.setCellWidget(row_pos, 5, color_button)
                self.count += 1
