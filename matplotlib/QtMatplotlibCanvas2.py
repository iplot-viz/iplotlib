from collections import Sequence

import matplotlib
from PyQt5 import QtGui, QtCore
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

    def __init__(self, parent, matplotlib_canvas: MatplotlibCanvas = None, enableToolbar: bool = True):
        super().__init__()
        layout = QVBoxLayout()
        self.matplotlib_canvas = matplotlib_canvas
        self.setLayout(layout)
        self.qt_canvas = FigureCanvas(matplotlib_canvas.figure)
        self.qt_canvas.setCursor(QtGui.QCursor(QtCore.Qt.CrossCursor))

        if enableToolbar:
            layout.addWidget(NavigationToolbar(self.qt_canvas, self))

        layout.addWidget(self.qt_canvas)
        self.matplotlib_canvas.figure.tight_layout()
        self.matplotlib_canvas.activate_cursor()
