"""
Link a python object to a widget.
"""

# Author: Jaswant Sai Panchumarti

import typing

from PySide2.QtCore import Qt
from PySide2.QtGui import QStandardItem

BeanPrototype = {'label' : None, 'property': None, 'widget': None, 'converter': None}


class BeanItem(QStandardItem):
    """
    This class encapsulates various roles of a BeanItem.
    """
    ConverterRole = Qt.UserRole + 40 #: The converter function.
    LabelRole = Qt.UserRole + 10 #: The label string used in a GUI form
    PropertyRole = Qt.UserRole + 20 #: The python property name.
    WidgetRole = Qt.UserRole + 30 #: The Qt widget that exposes the python object's property.

    def __init__(self, text: str, prototype: dict = BeanPrototype):
        super().__init__(text)

        self._data = {BeanItem.ConverterRole: prototype.get('converter'),
                      BeanItem.LabelRole: prototype.get('label'),
                      BeanItem.PropertyRole: prototype.get('property'),
                      BeanItem.WidgetRole: prototype.get('widget')}

    def setData(self, value: typing.Any, role: int = Qt.UserRole):
        if role in self._data.keys():
            self._data[role] = value
        else:
            return super().setData(value, role=role)

    def data(self, role: int = ...) -> typing.Any:
        if role in self._data.keys():
            return self._data[role]
        else:
            return super().data(role=role)
