# Description: A main window with a collection of iplotlib canvases and a helpful toolbar.
#               This helps developers write custom applications with PySide2
# Author: Jaswant Sai Panchumarti

from functools import partial
import typing

from PySide2.QtCore import QMargins, Qt, Signal
from PySide2.QtWidgets import QMainWindow, QWidget
from iplotlib.core.canvas import Canvas

from iplotlib.core.plot import Plot
from iplotlib.qt.utils.message_box import show_msg
from iplotlib.qt.gui.iplotCanvasToolbar import IplotQtCanvasToolbar
from iplotlib.qt.gui.iplotQtCanvasAssembly import IplotQtCanvasAssembly
from iplotlib.qt.gui.iplotQtPreferencesWindow import IplotQtPreferencesWindow

from iplotLogging import setupLogger as sl

logger = sl.get_logger(__name__)


class IplotQtMainWindow(QMainWindow):
    toolActivated = Signal(str)
    detachClicked = Signal(str)

    def __init__(self, show_toolbar: bool = True, parent: typing.Optional[QWidget] = None, flags: Qt.WindowFlags = Qt.WindowFlags()):
        super().__init__(parent=parent, flags=flags)

        self.canvasStack = IplotQtCanvasAssembly(parent=self)
        self.toolBar = IplotQtCanvasToolbar(parent=self)
        self.toolBar.setVisible(show_toolbar)
        self.prefWindow = IplotQtPreferencesWindow(
            self.canvasStack.model(), parent=self, flags=flags)
        self.prefWindow.canvasSelected.connect(self.canvasStack.setCurrentIndex)
        self.prefWindow.apply.connect(self.applyPreferences)

        self.addToolBar(self.toolBar)
        self.setCentralWidget(self.canvasStack)
        self.wireConnections()

        self._floatingWindow = QMainWindow(parent=self, flags=Qt.CustomizeWindowHint |
                                           Qt.WindowTitleHint | Qt.WindowMaximizeButtonHint | Qt.WindowMinimizeButtonHint)
        self._floatingWinMargins = QMargins()
        self._floatingWindow.layout().setContentsMargins(self._floatingWinMargins)
        self._floatingWindow.hide()

    def wireConnections(self):
        self.toolBar.undoAction.triggered.connect(self.undo)
        self.toolBar.redoAction.triggered.connect(self.redo)
        self.toolBar.toolActivated.connect(
            lambda tool_name:
                [self.canvasStack.widget(i).set_mouse_mode(tool_name) for i in range(self.canvasStack.count())])
        self.toolBar.redrawAction.triggered.connect(partial(self.reDraw, True))
        self.toolBar.detachAction.triggered.connect(self.detach)
        self.toolBar.configureAction.triggered.connect(
            lambda:
                [self.prefWindow.setWindowTitle(self.windowTitle()),
                 self.prefWindow.show()])

    def undo(self):
        for i in range(self.canvasStack.count()):
            canvas = self.canvasStack.widget(i)
            canvas.back()

    def redo(self):
        for i in range(self.canvasStack.count()):
            canvas = self.canvasStack.widget(i)
            canvas.forward()

    def applyPreferences(self):
        self.reDraw(discard_axis_range=False, discard_focused_plot=False)
        self.prefWindow.modified()

    def reDraw(self, discard_axis_range: bool = True, discard_focused_plot: bool = True):
        canvas = self.canvasStack.currentWidget()
        core_canvas = canvas.get_canvas()
        if not isinstance(core_canvas, Canvas):
            return
        for _, col in enumerate(core_canvas.plots):
            for _, plot in enumerate(col):
                if not isinstance(plot, Plot):
                    continue
                for axes in plot.axes:
                    if isinstance(axes, typing.Collection):
                        for axis in axes:
                            if discard_axis_range:
                                axis.begin = None
                                axis.end = None
                    else:
                        axis = axes
                        if discard_axis_range:
                            axis.begin = None
                            axis.end = None
        # TODO: change this confusing API to just call refresh(redraw=True, unfocus=..) of IplotQtCanvas
        if discard_focused_plot:
            canvas.unfocus_plot()
        canvas.set_canvas(canvas.get_canvas())

    def detach(self):
        if self.toolBar.detachAction.text() == 'Detach':
            # we detach now.
            tbArea = self.toolBarArea(self.toolBar)
            self._floatingWindow.setCentralWidget(self.canvasStack)
            self._floatingWindow.addToolBar(tbArea, self.toolBar)
            self._floatingWindow.setWindowTitle(self.windowTitle())
            self._floatingWindow.show()
            self.toolBar.detachAction.setText('Reattach')
        elif self.toolBar.detachAction.text() == 'Reattach':
            # we attach now.
            self.toolBar.detachAction.setText('Detach')
            tbArea = self._floatingWindow.toolBarArea(self.toolBar)
            self.setCentralWidget(self.canvasStack)
            self.addToolBar(tbArea, self.toolBar)
            self._floatingWindow.hide()
