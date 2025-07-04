# Copyright (c) 2020-2025 ITER Organization,
#               CS 90046
#               13067 St Paul Lez Durance Cedex
#               France
# Author IO
#
# This file is part of iplotlib module.
# iplotlib python module is free software: you can redistribute it and/or modify it under
# the terms of the MIT license.
#
# This file is part of ITER CODAC software.
# For the terms and conditions of redistribution or use of this software
# refer to the file LICENSE located in the top level directory
# of the distribution package
#


"""
Map a python object's attributes to an index (index used by a data widget mapper)
"""

# Author: Piotr Mazur
# Changelog:
#   Sept 2021: -Refactor qt classes [Jaswant Sai Panchumarti]
#              -Port to PySide2 [Jaswant Sai Panchumarti]
#              -Use PyObjectRole [Jaswant Sai Panchumarti]
#              -Use BeanPrototype [Jaswant Sai Panchumarti]

import typing

from PySide6.QtCore import QModelIndex, QObject, Qt
from PySide6.QtGui import QStandardItemModel
from PySide6.QtWidgets import QComboBox

from iplotlib.core import PropertyManager, SignalXY
from iplotlib.qt.models.beanItem import BeanItem, BeanPrototype
from iplotlib.qt.utils.conversions import ConversionHelper

from iplotLogging import setupLogger as Sl

logger = Sl.get_logger(__name__, 'INFO')


class BeanItemModel(QStandardItemModel):
    """
    An implementation of QStandardItemModel that binds indexes to object properties
    """
    PyObjectRole = Qt.ItemDataRole.UserRole + 50  #: This role is used to bind this model to a python object.

    def __init__(self, parent: typing.Optional[QObject] = ...):
        super().__init__(parent=parent)
        self._pyObject = None
        self.setItemPrototype(BeanItem('Bean', BeanPrototype))

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.UserRole) -> typing.Any:
        logger.debug(f"Index: {index}, role: {role}")

        if role == BeanItemModel.PyObjectRole:
            return self._pyObject

        bean = self.item(index.row(), index.column())
        # converter = bean.data(BeanItem.ConverterRole)
        widget = bean.data(BeanItem.WidgetRole)
        # label = bean.data(BeanItem.LabelRole)
        property_name = bean.data(BeanItem.PropertyRole)

        logger.debug(f"PyObject: {self._pyObject}")

        value = PropertyManager().get_value(self._pyObject, property_name)

        if isinstance(self._pyObject, SignalXY) and property_name == 'color' and value is None:
            return PropertyManager().get_value(self._pyObject, 'original_color')

        if isinstance(widget, QComboBox):
            keys = [widget.itemData(i, Qt.ItemDataRole.UserRole) for i in range(widget.count())]
            try:
                return keys.index(value)
            except ValueError:
                return None
        else:
            return str(value) if value is not None else None

    def setData(self, index: QModelIndex, value: typing.Any, role: int = Qt.ItemDataRole.UserRole) -> bool:
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
                keys = [widget.itemData(i, Qt.ItemDataRole.UserRole) for i in range(widget.count())]
                setattr(self._pyObject, property_name, keys[value])
                self.dataChanged.emit(index, index)
                return True
            else:
                if hasattr(self._pyObject, property_name):
                    type_func = type(getattr(self._pyObject, property_name))
                    value = ConversionHelper.asType(value, type_func)

                setattr(self._pyObject, property_name, value)
                self.dataChanged.emit(index, index)
                return True
