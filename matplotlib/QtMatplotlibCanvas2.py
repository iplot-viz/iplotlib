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
        self.original_canvas = None
        self.current_canvas = None
        self.setLayout(QVBoxLayout())
        self.layout().setContentsMargins(QMargins())
        self.matplotlib_canvas = None
        self.qt_canvas = None
        self.toolbar = None
        self.mouse_mode = None
        self.tight_layout = tight_layout

        self.set_canvas(canvas)


    def draw_in_main_thread(self):
        QMetaObject.invokeMethod(self, "flush_draw_queue")

    @pyqtSlot()
    def flush_draw_queue(self):
        if self.matplotlib_canvas:
            self.matplotlib_canvas.process_work_queue()

    def set_canvas(self, canvas):
        self.current_canvas = canvas
        if self.matplotlib_canvas and self.matplotlib_canvas.figure:
            self.matplotlib_canvas.figure.clear()
            self.matplotlib_canvas.deactivate_cursor()

        if canvas:
            print("Using matplotlib: {} interactive={}".format(matplotlib.__version__, matplotlib.is_interactive()))
            self.matplotlib_canvas = MatplotlibCanvas(canvas, tight_layout=self.tight_layout, mpl_flush_method=self.draw_in_main_thread)

            if self.qt_canvas is not None:
                self.qt_canvas.setParent(None)

            if self.matplotlib_canvas.figure:
                self.qt_canvas = FigureCanvas(self.matplotlib_canvas.figure)
                self.toolbar = NavigationToolbar(self.qt_canvas, self)
                self.toolbar.setVisible(False)

                self.layout().addWidget(self.qt_canvas)

                self.set_mouse_mode(self.mouse_mode or canvas.mouse_mode)
                QMetaObject.invokeMethod(self, "apply_tight_layout")

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

    """Additional callback to allow for returning to home after ouble click"""
    def click(self, event):
        print("CLICK",event)
        if event.dblclick:
            if event.button == 3 and event.inaxes is not None:
                print("ZOOM TO", event.inaxes._plot)
                self.select_plot(event.inaxes._plot)

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


    def select_plot(self, plot):
        if self.original_canvas is None:
            self.original_canvas = self.current_canvas
            new_canvas = dataclasses.replace(self.original_canvas)
            new_canvas.cols = 1
            new_canvas.rows = 1
            new_canvas.plots = [[]]
            new_canvas.add_plot(plot)
            self.set_canvas(new_canvas)
        else:
            self.set_canvas(self.original_canvas)
            self.original_canvas = None