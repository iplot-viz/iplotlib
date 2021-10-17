# Description: An assembly of canvas widgets arranged into a QStandardItemModel. 
#              The model is accessible with self.model(). A convenient exposure to TreeView/ListView/TableView.
#              Make sure you call refreshLinks after modifying the canvases.
# Author: Jaswant Sai Panchumarti

import typing

from PySide2.QtCore import Qt, Signal
from PySide2.QtGui import QStandardItemModel
from PySide2.QtWidgets import QStackedWidget, QWidget

from iplotlib.qt.utils.message_box import show_msg
from iplotlib.qt.gui.iplotQtCanvas import IplotQtCanvas
from iplotlib.qt.models.plotting import CanvasItem

from iplotLogging import setupLogger as sl

logger = sl.get_logger(__name__)


class IplotQtCanvasAssembly(QStackedWidget):
    toolActivated = Signal(str)
    detachClicked = Signal(str)
    canvasAdded = Signal(int, IplotQtCanvas)
    canvasRemoved = Signal(int, IplotQtCanvas)

    def __init__(self, parent: typing.Optional[QWidget] = None):
        super().__init__(parent=parent)
        self._model = QStandardItemModel(parent=self)
        self._parentItem = self._model.invisibleRootItem()

    def refreshLinks(self):
        for i in range(self.count()):
            self.setCanvasData(i, self.widget(i))

    def setCanvasData(self, idx, canvas: IplotQtCanvas):
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
            self.setCanvasData(idx, canvas)
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
            self.setCanvasData(idx, canvas)
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
