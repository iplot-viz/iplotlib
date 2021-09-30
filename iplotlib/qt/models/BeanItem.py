# Description: Link a python object to a widget.
# Author: Jaswant Sai Panchumarti

import typing

from PySide2.QtCore import Qt
from PySide2.QtGui import QStandardItem

BeanPrototype = {'label' : None, 'property': None, 'widget': None, 'converter': None}


class BeanItem(QStandardItem):
    ConverterRole = Qt.UserRole + 40
    LabelRole = Qt.UserRole + 10
    PropertyRole = Qt.UserRole + 20
    WidgetRole = Qt.UserRole + 30

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
