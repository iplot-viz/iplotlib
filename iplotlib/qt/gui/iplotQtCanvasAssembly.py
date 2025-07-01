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
An assembly of canvas widgets arranged into a QStandardItemModel. 
"""

# Author: Jaswant Sai Panchumarti

import typing

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QStandardItemModel
from PySide6.QtWidgets import QStackedWidget, QWidget

from iplotlib.qt.utils.message_box import show_msg
from iplotlib.qt.gui.iplotQtCanvas import IplotQtCanvas
from iplotlib.qt.models.plotting import CanvasItem

from iplotLogging import setupLogger as Sl

logger = Sl.get_logger(__name__)


class IplotQtCanvasAssembly(QStackedWidget):
    """
    The model is accessible with self.model(). Convenient for TreeView/ListView/TableView.
    Make sure you call refreshLinks after modifying the canvases.
    """
    canvasAdded = Signal(int, IplotQtCanvas)
    canvasRemoved = Signal(int, IplotQtCanvas)

    def __init__(self, parent: typing.Optional[QWidget] = None):
        super().__init__(parent=parent)
        self._model = QStandardItemModel(parent=self)
        self._parentItem = self._model.invisibleRootItem()

    def refreshLinks(self):
        """
        Refresh the links b/w the python canvas data object and the model.
        """
        for i in range(self.count()):
            self.set_canvas_data(i, self.widget(i))

    def set_canvas_data(self, idx, canvas: IplotQtCanvas):
        """
        Set the canvas data object for the 'idx' row in the model.
        """
        self._model.item(idx, 0).removeRows(0, self._model.item(idx, 0).rowCount())
        self._model.item(idx, 0).setData(canvas.get_canvas(), Qt.UserRole)

    def model(self) -> QStandardItemModel:
        return self._model

    def addWidget(self, canvas: QWidget):
        if not isinstance(canvas, IplotQtCanvas):
            show_msg(
                f"Cannot add canvas of type: {type(canvas)} != IplotQtCanvas or derived from it", "ERROR", self)
        else:
            idx = super().addWidget(canvas)
            self.setCurrentIndex(idx)
            canvasItem = CanvasItem(f'Canvas {idx + 1}')
            canvasItem.setEditable(False)
            self._parentItem.appendRow(canvasItem)
            self.set_canvas_data(idx, canvas)
            self.canvasAdded.emit(idx, canvas)

    def insertWidget(self, idx: int, canvas: QWidget):
        if not isinstance(canvas, IplotQtCanvas):
            show_msg(
                f"Cannot insert canvas of type: {type(canvas)} != IplotQtCanvas or derived from it", "ERROR", self)
        else:
            super().insertWidget(idx, canvas)
            canvasItem = CanvasItem(f'Canvas {idx + 1}')
            canvasItem.setEditable(False)
            self._parentItem.insertRow(idx, canvasItem)
            self.set_canvas_data(idx, canvas)
            self.canvasAdded.emit(idx, canvas)

    def removeWidget(self, canvas: QWidget):
        idx = self.indexOf(canvas)
        if idx >= 0:
            self.removeWidget(canvas)
            removed = self._parentItem.takeRow(idx)
            assert len(removed) > 0
            assert removed[0] == canvas
            self.canvasRemoved.emit(idx, canvas)
        else:
            show_msg(
                f"Cannot remove canvas: {id(canvas)}" + "Error: idx: {i} < 0", "ERROR", self)

    def currentWidget(self) -> IplotQtCanvas:
        return super().currentWidget()
