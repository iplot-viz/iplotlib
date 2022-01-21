"""
A window to configure the visual preferences for iplotlib.
"""

# Author: Piotr Mazur
# Changelog:
#   Sept 2021: -Refactor qt classes [Jaswant Sai Panchumarti]
#              -Port to PySide2 [Jaswant Sai Panchumarti]
#              -Add setModel function [Jaswant Sai Panchumarti]

import time
import typing

from PySide2.QtCore import QItemSelectionModel, QModelIndex, Qt
from PySide2.QtCore import Signal as QtSignal
from PySide2.QtGui import QShowEvent, QStandardItem, QStandardItemModel
from PySide2.QtWidgets import (QApplication, QMainWindow, QPushButton, QSplitter,
                               QStackedWidget, QTreeView, QWidget)

from iplotlib.core.axis import Axis, LinearAxis
from iplotlib.core.canvas import Canvas
from iplotlib.core.signal import ArraySignal, SimpleSignal, Signal
from iplotlib.core.plot import Plot, PlotXY
from iplotlib.interface import IplotSignalAdapter

from iplotlib.qt.gui.forms import IplotPreferencesForm, AxisForm, CanvasForm, PlotForm, SignalForm

from iplotLogging import setupLogger as sl

logger = sl.get_logger(__name__, 'INFO')

class IplotQtPreferencesWindow(QMainWindow):

    onApply = QtSignal()
    onReset = QtSignal()
    canvasSelected = QtSignal(int)

    def __init__(self, canvasAssembly: QStandardItemModel = None, parent: typing.Optional[QWidget] = None, flags: Qt.WindowFlags = Qt.WindowFlags()):

        super().__init__(parent=parent, flags=flags)

        self.treeView = QTreeView(self)
        self.treeView.setHeaderHidden(True)
        self.treeView.setModel(canvasAssembly)
        self.treeView.selectionModel().selectionChanged.connect(self.onItemSelected)
        self._applyTime = time.time_ns()

        self._forms = {
            Canvas: CanvasForm(self),
            PlotXY: PlotForm(self),
            LinearAxis: AxisForm(self),
            ArraySignal: SignalForm(self),
            IplotSignalAdapter: SignalForm(self),
            SimpleSignal: SignalForm(self),
            type(None): QPushButton("Select item", parent=self)
        }
        self.formsStack = QStackedWidget()
        for form in self._forms.values():
            self.formsStack.addWidget(form)
            if isinstance(form, IplotPreferencesForm):
                form.onApply.connect(self.onApply.emit)
                form.onReset.connect(self.onReset.emit)

        index = list(self._forms.keys()).index(Canvas)
        self.formsStack.setCurrentIndex(index)

        self.splitter = QSplitter(self)
        self.splitter.addWidget(self.treeView)
        self.splitter.addWidget(self.formsStack)
        self.splitter.setStretchFactor(1, 2)
        self.setCentralWidget(self.splitter)
        self.resize(800, 400)

    def _getCanvasItemIdx(self, idx: QModelIndex):
        child_idx = parent_idx = idx
        while parent_idx != self.treeView.rootIndex():
            child_idx = parent_idx
            parent_idx = self.treeView.model().parent(child_idx)
        return child_idx

    def postApplied(self):
        self._applyTime = time.time_ns()

    def getCollectiveMTime(self):
        val = 0
        for form in self._forms.values():
            if isinstance(form, IplotPreferencesForm):
                val = max(form.MTime(), val)
        return val

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
        if self._applyTime < self.getCollectiveMTime():
            self.onApply.emit()

    def setModel(self, model: QStandardItemModel):
        self.treeView.setModel(model)
        if isinstance(self.formsStack.currentWidget(), IplotPreferencesForm):
            self.formsStack.currentWidget().setSourceIndex(self.treeView.model().index(0, 0))
        self.treeView.expandAll()

    def showEvent(self, event: QShowEvent):
        self.treeView.selectionModel().select(self.treeView.model().index(0, 0), QItemSelectionModel.ClearAndSelect)
        return super().showEvent(event)

    def manualReset(self, idx: int):
        canvas = self.treeView.model().item(idx, 0).data(Qt.UserRole)
        if not isinstance(canvas, Canvas):
            return
        
        canvas.reset_preferences()
        for _, col in enumerate(canvas.plots):
            for _, plot in enumerate(col):
                if isinstance(plot, Plot):
                    plot.reset_preferences()
                else:
                    continue
                for axes in plot.axes:
                    if isinstance(axes, typing.Collection):
                        for axis in axes:
                            if isinstance(axis, Axis):
                                axis.reset_preferences()
                            else:
                                continue
                    elif isinstance(axes, Axis):
                        axes.reset_preferences()
                    else:
                        continue
                for stack in plot.signals.values():
                    for signal in stack:
                        if isinstance(signal, Signal):
                            signal.reset_preferences()
                        else:
                            continue
