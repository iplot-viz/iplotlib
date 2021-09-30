# Description: An abstract widget that maps a python entity's properties to widgets in the form.
# Author: Piotr Mazur
# Changelog:
#   Sept 2021: -Refactor qt classes [Jaswant Sai Panchumarti]
#              -Port to PySide2 [Jaswant Sai Panchumarti]

import typing

from PySide2.QtCore import QModelIndex, Qt, Signal
from PySide2.QtGui import QStandardItemModel
from PySide2.QtWidgets import (QCheckBox, QComboBox, QDataWidgetMapper, QLabel, QLineEdit,
                               QFormLayout, QPushButton, QSizePolicy, QSpinBox, QVBoxLayout, QWidget)

from iplotlib.qt.models import BeanItem, BeanItemModel
from iplotlib.qt.utils.color_picker import ColorPicker


class IplotPreferencesForm(QWidget):

    applySignal = Signal()

    def __init__(self, fields: typing.List[dict] = [{}], label: str = "Preferences", parent: typing.Optional[QWidget] = None, f: Qt.WindowFlags = Qt.Widget):
        super().__init__(parent=parent, f=f)

        self.top_label = QLabel(label)
        self.top_label.setSizePolicy(QSizePolicy(
            QSizePolicy.MinimumExpanding, QSizePolicy.Maximum))

        self.form = QWidget()
        self.form.setLayout(QFormLayout())

        self.applyButton = QPushButton("Apply")
        self.applyButton.pressed.connect(self.applySignal.emit)

        vlayout = QVBoxLayout()
        self.setLayout(vlayout)
        self.layout().addWidget(self.top_label)
        self.layout().addWidget(self.form)
        self.layout().addWidget(self.applyButton)

        self.widgetMapper = QDataWidgetMapper(self)
        self.widgetModel = BeanItemModel(self)
        self.widgetMapper.setModel(self.widgetModel)

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

    def setSourceIndex(self, idx: QModelIndex):
        pyObject = idx.data(Qt.UserRole)
        self.widgetModel.setData(
            QModelIndex(), pyObject, BeanItemModel.PyObjectRole)
        self.widgetMapper.toFirst()

    @staticmethod
    def create_spinbox(**params):
        widget = QSpinBox()
        if params.get("min"):
            widget.setMinimum(params.get("min"))
        if params.get("max"):
            widget.setMaximum(params.get("max"))
        return widget

    @staticmethod
    def create_comboBox(items):
        widget = QComboBox()
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
        return IplotPreferencesForm.create_spinbox(min=0, max=40)

    @staticmethod
    def default_linesize_widget():
        return IplotPreferencesForm.create_spinbox(min=0, max=20)

    @staticmethod
    def default_markersize_widget():
        return IplotPreferencesForm.create_spinbox(min=0, max=20)

    @staticmethod
    def default_linestyle_widget():
        return IplotPreferencesForm.create_comboBox({"Solid": "Solid", "Dotted": "Dotted", "Dashed": "Dashed", "None": "None"})

    @staticmethod
    def default_marker_widget():
        return IplotPreferencesForm.create_comboBox({"None": "None", "o": "o", "x": "x"})

    @staticmethod
    def default_linepath_widget():
        return IplotPreferencesForm.create_comboBox({"None": "Linear", "post": "Last Value"})
