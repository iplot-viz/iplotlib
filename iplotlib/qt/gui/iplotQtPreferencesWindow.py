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
import copy

from PySide6.QtCore import QItemSelectionModel, QModelIndex, Qt
from PySide6.QtCore import Signal as QtSignal
from PySide6.QtGui import QShowEvent, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (QApplication, QMainWindow, QPushButton, QSplitter, QStackedWidget, QTreeView, QWidget,
                               QScrollArea)

from iplotlib.core.axis import Axis, LinearAxis
from iplotlib.core.canvas import Canvas
from iplotlib.core.signal import Signal, SignalXY, SignalContour
from iplotlib.core.plot import Plot, PlotXY, PlotXYWithSlider, PlotContour
from iplotlib.qt.gui.forms import (IplotPreferencesForm, AxisForm, CanvasForm, PlotXYForm, PlotContourForm,
                                   SignalXYForm, SignalContourForm)

from iplotLogging import setupLogger as Sl

logger = Sl.get_logger(__name__, 'INFO')


class IplotQtPreferencesWindow(QMainWindow):
    """
    A window with a tree view of the iplotlib hierarchy on the left
    and the GUI forms on the right.
    """

    onApply = QtSignal()
    onReset = QtSignal()
    onDiscard = QtSignal()
    canvasSelected = QtSignal(int)

    def __init__(self, canvas_assembly: QStandardItemModel = None, parent: typing.Optional[QWidget] = None,
                 flags: Qt.WindowType = Qt.WindowType.Widget):

        super().__init__(parent=parent, flags=flags)
        self.setWindowTitle("Preferences")
        self.treeView = QTreeView(self)
        self.treeView.setHeaderHidden(True)
        self.treeView.setModel(canvas_assembly)
        self.treeView.selectionModel().selectionChanged.connect(self.on_item_selected)
        canvas_assembly.rowsInserted.connect(self.treeView.expandAll)
        self._applyTime = time.time_ns()
        self.current_canvas = None

        self._forms = {
            Canvas: CanvasForm(self),
            PlotXY: PlotXYForm(self),
            PlotXYWithSlider: PlotXYForm(self),
            PlotContour: PlotContourForm(self),
            LinearAxis: AxisForm(self),
            SignalXY: SignalXYForm(self),
            SignalContour: SignalContourForm(self),
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

        self.scrollArea = QScrollArea(self)
        self.scrollArea.setWidgetResizable(True)
        self.scrollArea.setWidget(self.formsStack)

        self.splitter = QSplitter(self)
        self.splitter.addWidget(self.treeView)
        self.splitter.addWidget(self.scrollArea)
        self.splitter.setStretchFactor(1, 2)
        self.setCentralWidget(self.splitter)
        self.resize(800, 400)

    def _get_canvas_item_idx(self, idx: QModelIndex):
        child_idx = parent_idx = idx
        while parent_idx != self.treeView.rootIndex():
            child_idx = parent_idx
            parent_idx = self.treeView.model().parent(child_idx)
        return child_idx

    def post_applied(self):
        self._applyTime = time.time_ns()

    def set_canvas_from_preferences(self):
        # Get the current canvas in order to preserve the preferences if these are reset
        original_canvas = self.treeView.model().item(0, 0).data(Qt.UserRole)
        self.current_canvas = copy.deepcopy(original_canvas)

    def get_collective_m_time(self):
        val = 0
        for form in self._forms.values():
            if isinstance(form, IplotPreferencesForm):
                val = max(form.m_time(), val)
        return val

    def on_item_selected(self, item: QStandardItem):
        if len(item.indexes()) > 0:
            for model_idx in item.indexes():
                data = model_idx.data(Qt.ItemDataRole.UserRole)
                try:
                    if isinstance(data, Canvas):
                        t = Canvas
                    else:
                        t = type(data)
                    index = list(self._forms.keys()).index(t)
                    canvas_item_idx = self._get_canvas_item_idx(model_idx)
                    self.canvasSelected.emit(canvas_item_idx.row())
                except ValueError:
                    logger.warning(f"Canvas assembly violated: An item with an unregistered class {type(data)}")
                    continue
                self.formsStack.setCurrentIndex(index)
                if isinstance(self.formsStack.currentWidget(), IplotPreferencesForm):
                    # Set top label
                    self.formsStack.currentWidget().top_label.setText(model_idx.data())
                    self.formsStack.currentWidget().set_source_index(model_idx)

    def closeEvent(self, event):
        if QApplication.focusWidget():
            QApplication.focusWidget().clearFocus()
        if self._applyTime < self.get_collective_m_time():
            self.onDiscard.emit()

    def setModel(self, model: QStandardItemModel):
        self.treeView.setModel(model)
        if isinstance(self.formsStack.currentWidget(), IplotPreferencesForm):
            self.formsStack.currentWidget().set_source_index(self.treeView.model().index(0, 0))
        self.treeView.expandAll()

    def showEvent(self, event: QShowEvent):
        # Clear selection in the Selection Model
        self.treeView.selectionModel().clearSelection()
        # Select model using the specified command
        self.treeView.selectionModel().select(self.treeView.model().index(0, 0), QItemSelectionModel.Select)
        self.treeView.expandAll()
        self.set_canvas_from_preferences()
        return super().showEvent(event)

    def reset_prefs(self, idx: int):
        canvas = self.treeView.model().item(idx, 0).data(Qt.UserRole)
        if not isinstance(canvas, Canvas):
            return
        canvas.merge(self.current_canvas)

    def manual_reset(self, idx: int):
        canvas = self.treeView.model().item(idx, 0).data(Qt.ItemDataRole.UserRole)
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
