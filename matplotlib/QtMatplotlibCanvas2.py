from collections import Sequence

import matplotlib
from PyQt5 import QtGui, QtCore
from PyQt5.QtGui import QResizeEvent
from PyQt5.QtWidgets import QVBoxLayout
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar

from iplotlib_matplotlib.MatplotlibCanvas import MatplotlibCanvas
from qt.QtPlotCanvas import QtPlotCanvas
import matplotlib.pyplot as plt

"""
A Qt widget holding matplotlib figure along with passing mouse events
"""


class QtMatplotlibCanvas2(QtPlotCanvas):

    def __init__(self, parent=None, plots=None, matplotlib_canvas: MatplotlibCanvas = None, enableToolbar: bool = False):
        super().__init__(parent)
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
            self.qt_canvas.setCursor(QtGui.QCursor(QtCore.Qt.CrossCursor))
            toolbar = NavigationToolbar(self.qt_canvas, self)
            if enableToolbar:
                layout.addWidget(toolbar)

            layout.addWidget(self.qt_canvas)
            self.matplotlib_canvas.figure.canvas.updateGeometry()

            self.matplotlib_canvas.figure.tight_layout()
            # self.matplotlib_canvas.activate_cursor()
            toolbar.zoom()
        else:
            print("No figure given to qtmaplotlibanvas")

    def resizeEvent(self, event: QResizeEvent):
        if self.matplotlib_canvas is not None and self.matplotlib_canvas.figure is not None:
            self.matplotlib_canvas.figure.tight_layout()
