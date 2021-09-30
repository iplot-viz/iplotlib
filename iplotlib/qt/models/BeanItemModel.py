# Description: Map a python object's attributes to an index (index used by a data widget mapper)
# Author: Piotr Mazur
# Changelog:
#   Sept 2021: -Refactor qt classes [Jaswant Sai Panchumarti]
#              -Port to PySide2 [Jaswant Sai Panchumarti]
#              -Use PyObjectRole [Jaswant Sai Panchumarti]
#              -Use BeanPrototype [Jaswant Sai Panchumarti]

import typing

from PySide2.QtCore import QModelIndex, QObject, Qt
from PySide2.QtGui import QStandardItemModel
from PySide2.QtWidgets import QComboBox

from iplotlib.qt.models.BeanItem import BeanItem, BeanPrototype
from iplotlib.qt.utils.conversions import ConversionHelper

from iplotLogging import setupLogger as sl

logger = sl.get_logger(__name__, 'INFO')

class BeanItemModel(QStandardItemModel):
    """An implementation of QStandardItemModel that binds indexes to object properties"""
    PyObjectRole = Qt.UserRole + 50

    def __init__(self, parent: typing.Optional[QObject] = ...):
        super().__init__(parent=parent)
        self._pyObject = None
        self.setItemPrototype(BeanItem('Bean', BeanPrototype))

    def data(self, index: QModelIndex, role: int = Qt.UserRole) -> typing.Any:
        logger.debug(f"Index: {index}, role: {role}")
        bean = self.item(index.row(), index.column())
        # converter = bean.data(BeanItem.ConverterRole)
        widget = bean.data(BeanItem.WidgetRole)
        # label = bean.data(BeanItem.LabelRole)
        property_name = bean.data(BeanItem.PropertyRole)

        logger.debug(f"PyObject: {self._pyObject}")
        if isinstance(widget, QComboBox):
            key = getattr(self._pyObject, property_name, None)
            keys = [widget.itemData(i, Qt.UserRole) for i in range(widget.count())]
            try:
                return keys.index(key)
            except ValueError:
                return None
        else:
            value = getattr(self._pyObject, property_name, None)
            return str(value) if value else None

    def setData(self, index: QModelIndex, value: typing.Any, role: int = Qt.UserRole) -> bool:
        logger.debug(f"Index: {index}, role: {role}, value: {value}")
        if role == BeanItemModel.PyObjectRole:
            self._pyObject = value
            self.dataChanged.emit(self.createIndex(0, 0), self.createIndex(0, self.columnCount()))
            return True
        else:
            bean = self.item(index.row(), index.column())
            # converter = bean.data(BeanItem.ConverterRole)
            widget = bean.data(BeanItem.WidgetRole)
            # label = bean.data(BeanItem.LabelRole)
            property_name = bean.data(BeanItem.PropertyRole)

            if isinstance(widget, QComboBox):
                keys = [widget.itemData(i, Qt.UserRole) for i in range(widget.count())]
                if hasattr(self._pyObject, property_name):
                    setattr(self._pyObject, property_name, keys[value])
                    self.dataChanged.emit(index, index)
                    return True
                else:
                    return False
            else:
                if hasattr(self._pyObject, property_name):
                    type_func = type(getattr(self._pyObject, property_name))
                    value = ConversionHelper.asType(value, type_func)
                setattr(self._pyObject, property_name, value)
                self.dataChanged.emit(index, index)
                return True
