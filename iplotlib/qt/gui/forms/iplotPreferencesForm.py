"""
An abstract widget that maps a python entity's properties to widgets in the form.
"""

# Author: Piotr Mazur
# Changelog:
#   Sept 2021:  -Refactor qt classes [Jaswant Sai Panchumarti]
#               -Port to PySide2 [Jaswant Sai Panchumarti]
#   Jan 2023:   -Added methods to create legend position and layout combobox [Alberto Luengo]

from typing import List, Optional
import time

from PySide6.QtCore import QModelIndex, Qt, Signal, Slot
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDataWidgetMapper, QLabel, QLineEdit, QFormLayout, QPushButton,
                               QSizePolicy, QSpinBox, QVBoxLayout, QWidget, QScrollArea)

from iplotlib.qt.models import BeanItem, BeanItemModel
from iplotlib.qt.utils.color_picker import ColorPicker


class IplotPreferencesForm(QWidget):
    """
    Map a python object's attributes onto data widgets in a GUI form.
    """
    onApply = Signal()
    onReset = Signal()

    def __init__(self, fields: Optional[List[dict]] = None, label: str = "Preferences",
                 parent: Optional[QWidget] = None,
                 f: Qt.WindowType = Qt.WindowType.Widget):
        if fields is None:
            fields = [{}]
        super().__init__(parent=parent, f=f)

        self.top_label = QLabel(label)
        self.top_label.setSizePolicy(QSizePolicy(QSizePolicy.Policy.MinimumExpanding, QSizePolicy.Policy.Maximum))

        self.form = QWidget()
        self.form.setLayout(QFormLayout())

        self.applyButton = QPushButton("Apply")
        self.applyButton.pressed.connect(self.onApply.emit)
        self.resetButton = QPushButton("Reset")
        self.resetButton.pressed.connect(self.reset_prefs)
        self._modifiedTime = time.time_ns()

        vlayout = QVBoxLayout()
        self.setLayout(vlayout)

        self.scrollArea = QScrollArea(self)
        self.scrollArea.setWidgetResizable(True)
        self.scrollArea.setWidget(self.form)
        self.layout().addWidget(self.top_label)
        self.layout().addWidget(self.scrollArea)
        self.layout().addWidget(self.applyButton)
        self.layout().addWidget(self.resetButton)

        self.widgetMapper = QDataWidgetMapper(self)
        self.widgetModel = BeanItemModel(self)
        self.widgetMapper.setModel(self.widgetModel)
        self.widgetModel.dataChanged.connect(self.modified)

        if all([isinstance(f, dict) for f in fields]):
            for i, field in enumerate(fields):
                bean = BeanItem(field.get('label'), field)
                self.widgetModel.appendColumn([bean])

                widget = bean.data(BeanItem.WidgetRole)
                if isinstance(widget, QComboBox):
                    self.widgetMapper.addMapping(widget, i, b'currentIndex')
                elif isinstance(widget, ColorPicker):
                    self.widgetMapper.addMapping(widget, i, b'currentColor')
                else:
                    self.widgetMapper.addMapping(widget, i)

                label = bean.data(BeanItem.LabelRole)
                self.form.layout().addRow(label, widget)
        self.widgetMapper.toFirst()

    def m_time(self):
        """
        Return the last modified time stamp.
        """
        return self._modifiedTime

    def modified(self):
        """
        Force modify the preferences state.
        """
        self._modifiedTime = time.time_ns()

    def set_source_index(self, idx: QModelIndex):
        """
        Set the python object that will be sourced by the data widgets.
        The python object should be an instance of the core iplotlib Canvas class for tthe sourcing mechanism to
        function.
        The `QModelIndex` should've encapsulated a python object for the `Qt.UserRole`.
        This encapsulation is done in :data:`~iplotlib.qt.gui.iplotQtCanvasAssembly.IplotQtCanvasAssembly.setCanvasData`
        """
        py_object = idx.data(Qt.ItemDataRole.UserRole)
        self.widgetModel.setData(QModelIndex(), py_object, BeanItemModel.PyObjectRole)
        self.widgetMapper.toFirst()

    @Slot()
    def reset_prefs(self):
        """
        Derived instances will implement the reset functionality.
        """
        self.onReset.emit()

    @staticmethod
    def create_spinbox(**params):
        widget = QSpinBox()
        # Override the wheelEvent method using a lambda function to ignore mouse wheel events
        widget.wheelEvent = lambda event: event.ignore()
        if params.get("min"):
            widget.setMinimum(params.get("min"))
        if params.get("max"):
            widget.setMaximum(params.get("max"))
        return widget

    @staticmethod
    def create_combo_box(items):
        widget = QComboBox()
        # Override the wheelEvent method using a lambda function to ignore mouse wheel events
        widget.wheelEvent = lambda event: event.ignore()
        if isinstance(items, dict):
            for k, v in items.items():
                widget.addItem(v, k)
        elif isinstance(items, list):
            for i in items:
                widget.addItem(i)
            pass
        return widget

    @staticmethod
    def create_lineedit(**params):
        widget = QLineEdit()
        if params.get("readonly"):
            widget.setReadOnly(params.get("readonly"))
        return widget

    @staticmethod
    def create_checkbox():
        widget = QCheckBox()
        return widget

    @staticmethod
    def default_fontsize_widget():
        return IplotPreferencesForm.create_spinbox(min=0, max=15)

    @staticmethod
    def default_linesize_widget():
        return IplotPreferencesForm.create_spinbox(min=0, max=20)

    @staticmethod
    def default_markersize_widget():
        return IplotPreferencesForm.create_spinbox(min=0, max=10)

    @staticmethod
    def default_ticknumber_widget():
        return IplotPreferencesForm.create_spinbox(min=1, max=7)

    @staticmethod
    def default_contour_levels_widget():
        return IplotPreferencesForm.create_spinbox(min=1, max=10)

    @staticmethod
    def default_linestyle_widget():
        return IplotPreferencesForm.create_combo_box(
            {"Solid": "Solid", "Dotted": "Dotted", "Dashed": "Dashed", "None": "None"})

    @staticmethod
    def default_marker_widget():
        return IplotPreferencesForm.create_combo_box({"None": "None", "o": "o", "x": "x"})

    @staticmethod
    def default_linepath_widget():
        return IplotPreferencesForm.create_combo_box({"linear": "Linear", "post": "Last Value"})

    @staticmethod
    def default_canvas_legend_position_widget():
        return IplotPreferencesForm.create_combo_box({'upper right': 'Upper right', 'upper left': 'Upper left',
                                                      'upper center': 'Upper center', 'lower right': 'Lower right',
                                                      'lower left': 'Lower left', 'lower center': 'Lower center',
                                                      'center right': 'Center right', 'center left': 'Center left',
                                                      'center': 'Center'})

    @staticmethod
    def default_plot_legend_position_widget():
        return IplotPreferencesForm.create_combo_box({'same as canvas': 'Same as canvas',
                                                      'upper right': 'Upper right', 'upper left': 'Upper left',
                                                      'upper center': 'Upper center', 'lower right': 'Lower right',
                                                      'lower left': 'Lower left', 'lower center': 'Lower center',
                                                      'center right': 'Center right', 'center left': 'Center left',
                                                      'center': 'Center'})

    @staticmethod
    def default_plot_contour_legend_format_widget():
        return IplotPreferencesForm.create_combo_box({'color_bar': 'Color bar', 'in_lines': 'In Lines'})

    @staticmethod
    def default_plot_contour_color_map_widget():
        return IplotPreferencesForm.create_combo_box({'viridis': 'Viridis', 'plasma': 'Plasma', 'inferno': 'Inferno',
                                                      'magma': 'Magma', 'cividis': 'Cividis', 'Greys': 'Greys',
                                                      'Purples': 'Purples', 'Blues': 'Blues', 'Greens': 'Greens',
                                                      'Oranges': 'Oranges', 'Reds': 'Reds', 'coolwarm': 'Coolwarm',
                                                      'bwr': 'Bwr', 'seismic': 'Seismic', 'PiYG': 'PiYG',
                                                      'RdBu': 'RdBu'})

    @staticmethod
    def default_canvas_legend_layout_widget():
        return IplotPreferencesForm.create_combo_box({'vertical': 'Vertical',
                                                      'horizontal': 'Horizontal'})

    @staticmethod
    def default_plot_legend_layout_widget():
        return IplotPreferencesForm.create_combo_box({'same as canvas': 'Same as canvas', 'vertical': 'Vertical',
                                                      'horizontal': 'Horizontal'})
