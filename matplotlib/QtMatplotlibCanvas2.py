from collections import Sequence

import matplotlib
from PyQt5 import QtGui, QtCore
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QResizeEvent
from PyQt5.QtWidgets import QVBoxLayout
from matplotlib.backend_bases import FigureCanvasBase
from matplotlib.backends.backend_qt5 import FigureCanvasQT
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar

from iplotlib.ui.Event import MouseEvent
from iplotlib_matplotlib.MatplotlibCanvas import MatplotlibCanvas
from qt.QtPlotCanvas import QtPlotCanvas
import matplotlib.pyplot as plt

"""
A Qt widget holding matplotlib figure along with passing mouse events
"""


class QtMatplotlibCanvas2(QtPlotCanvas):

    def __init__(self, parent=None, plots=None, matplotlib_canvas: MatplotlibCanvas = None, enableToolbar: bool = False):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.installEventFilter(self)

        layout = QVBoxLayout()

        if matplotlib_canvas is None:
            if plots is not None:
                self.matplotlib_canvas = MatplotlibCanvas(plots)
            else:
                self.matplotlib_canvas = MatplotlibCanvas()
        else:
            self.matplotlib_canvas = matplotlib_canvas

        self.setLayout(layout)
        if self.matplotlib_canvas.figure:
            self.qt_canvas = FigureCanvas(self.matplotlib_canvas.figure)
            self.qt_canvas.setAttribute(Qt.WA_TransparentForMouseEvents)

            self.qt_canvas.setCursor(QtGui.QCursor(QtCore.Qt.CrossCursor))
            self.toolbar = NavigationToolbar(self.qt_canvas, self)
            if enableToolbar:
                layout.addWidget(self.toolbar)
            else:
                self.toolbar.setVisible(False)

            layout.addWidget(self.qt_canvas)
            self.matplotlib_canvas.figure.canvas.updateGeometry()

            self.matplotlib_canvas.figure.tight_layout()
            # self.matplotlib_canvas.activate_cursor()

        else:
            print("No figure given to qtmaplotlibanvas")

    def resizeEvent(self, event: QResizeEvent):
        # self.qt_canvas.mouseMoveEvent()
        if self.matplotlib_canvas is not None and self.matplotlib_canvas.figure is not None:
            print("RESIZE; " + str(self.geometry()) + " and " + str(self.qt_canvas.geometry()))
            self.matplotlib_canvas.figure.tight_layout()


    def eventFilter(self, source, event):

        if event.type() == QtCore.QEvent.MouseMove:
            ret = MouseEvent()
            ret.type = "mouseMove"
            ret.x, ret.y = self.qt_canvas.mouseEventCoords(event.pos())
            self.matplotlib_canvas.handleEvent(ret)
        elif event.type() == QtCore.QEvent.MouseButtonPress:
            ret = MouseEvent()
            ret.type = "mousePress"
            ret.x, ret.y = self.qt_canvas.mouseEventCoords(event.pos())
            if event.button() == QtCore.Qt.LeftButton:
                ret.button = "left"
            elif event.button() == QtCore.Qt.RightButton:
                ret.button = "right"
            self.matplotlib_canvas.handleEvent(ret)
        elif event.type() == QtCore.QEvent.MouseButtonRelease:
            ret = MouseEvent()
            ret.type = "mouseRelease"
            ret.x, ret.y = self.qt_canvas.mouseEventCoords(event.pos())
            if event.button() == QtCore.Qt.LeftButton:
                ret.button = "left"
            elif event.button() == QtCore.Qt.RightButton:
                ret.button = "right"
            self.matplotlib_canvas.handleEvent(ret)

        return False

    def enableTool(self, tool):
        if tool == "crosshair":
            self.matplotlib_canvas.activate_cursor()
            self.toolbar.set_cursor(self.matplotlib_canvas.cursor)
        elif tool == "zoom":
            self.matplotlib_canvas.deactivate_cursor()
            self.toolbar.zoom()
        elif tool == "pan":
            pass
