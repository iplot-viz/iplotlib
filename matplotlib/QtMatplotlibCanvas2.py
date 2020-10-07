from PyQt5 import QtGui, QtCore
from PyQt5.QtCore import Qt
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

    def __init__(self, canvas: Canvas = None, parent=None, plots=None, enableToolbar: bool = False, intercept_mouse=False):
        super().__init__(parent)

        if intercept_mouse:
            self.setMouseTracking(True)
            self.installEventFilter(self)

        self.matplotlib_canvas = MatplotlibCanvas(canvas)

        layout = QVBoxLayout()

        self.setLayout(layout)
        if self.matplotlib_canvas.figure:
            self.qt_canvas = FigureCanvas(self.matplotlib_canvas.figure)
            if intercept_mouse:
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

            if self.matplotlib_canvas.canvas.mouse_mode == "zoom":
                self.toolbar.zoom()
                self.matplotlib_canvas.figure.canvas.mpl_connect('button_press_event', self.click)

            elif self.matplotlib_canvas.canvas.mouse_mode == "pan":
                self.toolbar.pan()
                self.matplotlib_canvas.figure.canvas.mpl_connect('button_press_event', self.click)

            if canvas.crosshair_enabled:
                self.matplotlib_canvas.activate_cursor()

        else:
            print("No figure given")

    def click(self, event):
        if event.dblclick:
            self.toolbar.home()

    def keyPressEvent(self, event: QtGui.QKeyEvent):
        if event.text() == 'n':
            self.toolbar.forward()
        elif event.text() == 'p':
            self.toolbar.back()

    def resizeEvent(self, event: QResizeEvent):
        if self.matplotlib_canvas is not None and self.matplotlib_canvas.figure is not None:
            self.matplotlib_canvas.figure.tight_layout()
            # pass
