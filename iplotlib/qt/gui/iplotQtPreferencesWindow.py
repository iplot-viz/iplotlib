# Description: A window to configure the visual preferences for iplotlib.
# Author: Piotr Mazur
# Changelog:
#   Sept 2021: -Refactor qt classes [Jaswant Sai Panchumarti]
#              -Port to PySide2 [Jaswant Sai Panchumarti]
#              -Add setModel function [Jaswant Sai Panchumarti]

import typing
from collections import namedtuple

from PySide2.QtCore import QItemSelectionModel, QModelIndex, Qt, Signal
from PySide2.QtGui import QShowEvent, QStandardItem, QStandardItemModel
from PySide2.QtWidgets import (QApplication, QMainWindow, QPushButton, QSplitter,
                               QStackedWidget, QTreeView, QWidget)

from iplotlib.core.axis import LinearAxis
from iplotlib.core.canvas import Canvas
from iplotlib.core.signal import ArraySignal
from iplotlib.core.plot import PlotXY
from iplotlib.interface import IplotSignalAdapter

from iplotlib.qt.gui.forms import IplotPreferencesForm, AxisForm, CanvasForm, PlotForm, SignalForm

from iplotLogging import setupLogger as sl

logger = sl.get_logger(__name__, 'INFO')

class IplotQtPreferencesWindow(QMainWindow):

    apply = Signal()
    canvasSelected = Signal(int)

    def __init__(self, canvasAssembly: QStandardItemModel = None, parent: typing.Optional[QWidget] = None, flags: Qt.WindowFlags = Qt.WindowFlags()):

        super().__init__(parent=parent, flags=flags)

        self.treeView = QTreeView(self)
        self.treeView.setHeaderHidden(True)
        self.treeView.setModel(canvasAssembly)
        self.treeView.selectionModel().selectionChanged.connect(self.onItemSelected)

        self._forms = {
            Canvas: CanvasForm(self),
            PlotXY: PlotForm(self),
            LinearAxis: AxisForm(self),
            ArraySignal: SignalForm(self),
            IplotSignalAdapter: SignalForm(self),
            type(None): QPushButton("Select item", parent=self)
        }
        self.formsStack = QStackedWidget()
        for form in self._forms.values():
            self.formsStack.addWidget(form)
            if isinstance(form, IplotPreferencesForm):
                form.applySignal.connect(self.apply.emit)

        index = list(self._forms.keys()).index(Canvas)
        self.formsStack.setCurrentIndex(index)

        self.splitter = QSplitter(self)
        self.splitter.addWidget(self.treeView)
        self.splitter.addWidget(self.formsStack)
        self.splitter.setSizes([30, 70])
        self.setCentralWidget(self.splitter)
        self.resize(800, 400)

    def _getCanvasItemIdx(self, idx: QModelIndex):
        child_idx = parent_idx = idx
        while parent_idx != self.treeView.rootIndex():
            child_idx = parent_idx
            parent_idx = self.treeView.model().parent(child_idx)
        return child_idx

    def onItemSelected(self, item: QStandardItem):
        if len(item.indexes()) > 0:
            for model_idx in item.indexes():
                data = model_idx.data(Qt.UserRole)
                try:
                    if isinstance(data, Canvas):
                        t = Canvas
                    else:
                        t = type(data)
                    index = list(self._forms.keys()).index(t)
                    canvasItemIdx = self._getCanvasItemIdx(model_idx)
                    self.canvasSelected.emit(canvasItemIdx.row())
                except ValueError:
                    logger.warning(f"Canvas assembly violated: An item with an unregistered class {type(data)}")
                    continue
                self.formsStack.setCurrentIndex(index)
                if isinstance(self.formsStack.currentWidget(), IplotPreferencesForm):
                    self.formsStack.currentWidget().setSourceIndex(model_idx)

    def closeEvent(self, event):
        if QApplication.focusWidget():
            QApplication.focusWidget().clearFocus()
        self.apply.emit()

    def setModel(self, model: QStandardItemModel):
        self.treeView.setModel(model)
        if isinstance(self.formsStack.currentWidget(), IplotPreferencesForm):
            self.formsStack.currentWidget().setSourceIndex(self.treeView.model().index(0, 0))
        self.treeView.expandAll()

    def showEvent(self, event: QShowEvent):
        self.treeView.selectionModel().select(self.treeView.model().index(0, 0), QItemSelectionModel.ClearAndSelect)
        return super().showEvent(event)