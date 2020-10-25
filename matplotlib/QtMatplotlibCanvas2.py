from abc import ABCMeta

from PyQt5 import QtGui, QtCore
from PyQt5.QtCore import QMargins, Qt
from PyQt5.QtGui import QResizeEvent
from PyQt5.QtWidgets import QVBoxLayout
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar

from iplotlib.Canvas import Canvas
from iplotlib_matplotlib.MatplotlibCanvas import MatplotlibCanvas
from qt.QtPlotCanvas import QtPlotCanvas

"""
A Qt widget holding matplotlib figure along with passing mouse events
"""


class QtMatplotlibCanvas2(QtPlotCanvas):

    def __init__(self, canvas: Canvas = None, parent=None):
        super().__init__(parent)
        self.setLayout(QVBoxLayout())
        self.layout().setContentsMargins(QMargins())
        self.matplotlib_canvas = None
        self.qt_canvas = None
        self.toolbar = None
        self.mouse_mode = None
        self.set_canvas(canvas)

    def set_canvas(self, canvas):
        if canvas:
            self.matplotlib_canvas = MatplotlibCanvas(canvas)

            if self.qt_canvas is not None:
                self.qt_canvas.setParent(None)

            if self.matplotlib_canvas.figure:
                self.qt_canvas = FigureCanvas(self.matplotlib_canvas.figure)
                self.toolbar = NavigationToolbar(self.qt_canvas, self)
                self.toolbar.setVisible(False)

                self.layout().addWidget(self.qt_canvas)

                self.set_mouse_mode(self.mouse_mode or canvas.mouse_mode)

    def set_mouse_mode(self, mode: str):
        self.mouse_mode = mode

        if self.toolbar:
            if mode == Canvas.MOUSE_MODE_CROSSHAIR:
                self.toolbar._active = 'PAN'
                self.toolbar.pan()
                self.matplotlib_canvas.activate_cursor()
            elif mode == Canvas.MOUSE_MODE_PAN:
                self.toolbar.pan()
                self.matplotlib_canvas.figure.canvas.mpl_connect('button_press_event', self.click)
            elif mode == Canvas.MOUSE_MODE_ZOOM:
                self.toolbar.zoom()
                self.matplotlib_canvas.figure.canvas.mpl_connect('button_press_event', self.click)

    """Return to home position on double click"""
    def click(self, event):
        if event.dblclick:
            self.toolbar.home()

    def keyPressEvent(self, event: QtGui.QKeyEvent):
        if event.text() == 'n':
            self.toolbar.forward()
        elif event.text() == 'p':
            self.toolbar.back()
