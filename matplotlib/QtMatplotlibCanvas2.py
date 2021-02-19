import dataclasses
from abc import ABCMeta

import matplotlib
from PyQt5 import QtGui, QtCore
from PyQt5.QtCore import QMargins, QMetaObject, Qt, pyqtSlot
from PyQt5.QtGui import QResizeEvent
from PyQt5.QtWidgets import QAction, QStyle, QVBoxLayout
from matplotlib.backend_bases import _Mode
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar

from iplotlib.Canvas import Canvas
from iplotlib_matplotlib.MatplotlibCanvas import MatplotlibCanvas
from matplotlib.widgets import MultiCursor
from qt.QtPlotCanvas import QtPlotCanvas

"""
A Qt widget holding matplotlib figure along with passing mouse events
"""


class QtMatplotlibCanvas2(QtPlotCanvas):

    def __init__(self, canvas: Canvas = None, parent=None, tight_layout=True):
        super().__init__(parent)
        self.setLayout(QVBoxLayout())
        self.layout().setContentsMargins(QMargins())

        self.qt_canvas = None
        self.toolbar = None
        self.mouse_mode = None
        self.tight_layout = tight_layout

        self.matplotlib_canvas = MatplotlibCanvas(tight_layout=tight_layout, mpl_flush_method=self.draw_in_main_thread)
        self.set_canvas(canvas)


    def draw_in_main_thread(self):
        QMetaObject.invokeMethod(self, "flush_draw_queue")

    @pyqtSlot()
    def flush_draw_queue(self):
        if self.matplotlib_canvas:
            self.matplotlib_canvas.process_work_queue()

    def set_canvas(self, canvas, focus_plot=None):
        if self.matplotlib_canvas:
            self.matplotlib_canvas.deactivate_cursor()

        if canvas:
            print("Using matplotlib: {} interactive={}".format(matplotlib.__version__, matplotlib.is_interactive()))
            self.matplotlib_canvas.process_iplotlib_canvas(canvas)

            if self.qt_canvas is not None:
                self.qt_canvas.setParent(None)

            if self.matplotlib_canvas.figure:

                self.qt_canvas = FigureCanvas(self.matplotlib_canvas.figure)
                self.toolbar = NavigationToolbar(self.qt_canvas, self)
                self.toolbar.setVisible(False)

                self.layout().addWidget(self.qt_canvas)

                self.set_mouse_mode(self.mouse_mode or canvas.mouse_mode)
                QMetaObject.invokeMethod(self, "apply_tight_layout")

    def get_canvas(self):
        return self.matplotlib_canvas.canvas if self.matplotlib_canvas else None


    @pyqtSlot()
    def apply_tight_layout(self):
        if self.matplotlib_canvas is not None:
            self.matplotlib_canvas.figure.tight_layout()
            self.matplotlib_canvas.figure.canvas.draw()

    def process_canvas_toolbar(self, toolbar):
        toolbar.addSeparator()
        toolbar.addAction(self.style().standardIcon(getattr(QStyle, "SP_FileDialogListView")), "Layout", self.apply_tight_layout)

    def set_mouse_mode(self, mode: str):
        self.mouse_mode = mode

        def reset_tool():
            if self.toolbar:
                self.toolbar.mode = _Mode.NONE
                self.matplotlib_canvas.deactivate_cursor()

        reset_tool()

        if self.toolbar and self.mouse_mode is not None:
            if mode == Canvas.MOUSE_MODE_CROSSHAIR:
                self.toolbar.canvas.widgetlock.release(self.toolbar)
                self.matplotlib_canvas.activate_cursor()
                self.matplotlib_canvas.figure.canvas.mpl_connect('button_press_event', self.click)

            elif mode == Canvas.MOUSE_MODE_PAN:
                self.matplotlib_canvas.deactivate_cursor()
                self.toolbar.pan()
                self.matplotlib_canvas.figure.canvas.mpl_connect('button_press_event', self.click)
            elif mode == Canvas.MOUSE_MODE_ZOOM:
                self.matplotlib_canvas.deactivate_cursor()
                self.toolbar.zoom()
                self.matplotlib_canvas.figure.canvas.mpl_connect('button_press_event', self.click)
            elif mode == Canvas.MOUSE_MODE_SELECT:
                self.matplotlib_canvas.figure.canvas.mpl_connect('button_press_event', self.click)
                pass

    def click(self, event):
        """Additional callback to allow for focusing on one plot and returning home after double click"""
        if event.dblclick:
            if self.mouse_mode == Canvas.MOUSE_MODE_SELECT and event.button == 1 and event.inaxes is not None:
                self.focus_plot(event.inaxes._plot)
            else:
                self.toolbar.home()

    def keyPressEvent(self, event: QtGui.QKeyEvent):
        if event.text() == 'n':
            self.toolbar.forward()
        elif event.text() == 'p':
            self.toolbar.back()

    def back(self):
        if self.toolbar:
            self.toolbar.back()

    def forward(self):
        if self.toolbar:
            self.toolbar.forward()



    def focus_plot(self, plot):
        """Toggle focus on one plot on/off"""
        if self.matplotlib_canvas.focused_plot is None:
            self.matplotlib_canvas.focus_plot(plot)
        else:
            self.matplotlib_canvas.unfocus_plot()

        self.matplotlib_canvas.figure.canvas.draw()
