from PyQt5.QtCore import QMetaObject, Qt, pyqtSlot
from PyQt5.QtGui import QResizeEvent
from PyQt5.QtWidgets import QGridLayout, QPushButton, QSizePolicy, QWidget

from iplotlib.Canvas import Canvas
from iplotlib_gnuplot.GnuplotCanvas import GnuplotCanvas
from qt.QtCanvasOverlay import QtCanvasOverlay
from qt.QtPlotCanvas import QtPlotCanvas
from qt.gnuplot.QtGnuplotWidget2 import QtGnuplotWidget2
from qt.gnuplotwidget.pyqt5gnuplotwidget.PyGnuplotWidget import QtGnuplotWidget

from qt.canvastools.QtCrosshairTool import QtOverlayCrosshairTool
from qt.canvastools.QtPanTool import QtOverlayPanTool
from qt.canvastools.QtZoomTool import QtOverlayZoomTool

import sip

"""
A plot canvas that uses multiple widgets in order to place multiple gnuplot graphs on a grid
This way it is possible not to use multiplot that interferes with mouse actions
"""


class QtGnuplotMultiwidgetCanvas(QtPlotCanvas):

    def __init__(self, canvas: Canvas = None, parent=None):
        super().__init__(parent)
        self.setLayout(QGridLayout())
        self.canvas = None
        self.set_canvas(canvas)

    def set_canvas(self,canvas):
        self.hide()  # Hide/Show will cause only one resizeEvent per widget. Plot will be redrawn then

        items = [self.layout().itemAt(i) for i in range(self.layout().count())]
        for item in items:
            self.layout().removeItem(item)
            item.widget().cleanup()
            sip.delete(item.widget())

        if canvas:
            self.canvas = canvas
            self.layout().setSpacing(0)
            for i in range(canvas.cols):
                for j in range(canvas.rows):
                    policy = QSizePolicy(QSizePolicy.Expanding,QSizePolicy.Expanding,QSizePolicy.Frame)
                    policy.setVerticalStretch(2)
                    policy.setHorizontalStretch(2)
                    # widget = QtGnuplotWidget(self)
                    widget = QtGnuplotWidget2(self)
                    widget.setSizePolicy(policy)
                    widget.setStyleSheet("border:1px solid red")
                    self.layout().addWidget(widget, j, i)

            for i, col in enumerate(self.canvas.plots):
                for j, plot in enumerate(col):
                    widget = self.layout().itemAtPosition(j, i).widget()

                    c = Canvas()
                    c.add_plot(plot)
                    widget._gnuplot_canvas = GnuplotCanvas(c)

                    if plot:
                        overlay = QtCanvasOverlay(widget)

                        if self.canvas.mouse_mode == "zoom":
                            overlay.activeTool = QtOverlayZoomTool()
                        elif self.canvas.mouse_mode == "pan":
                            overlay.activeTool = QtOverlayPanTool()

                        if self.canvas.crosshair_enabled:
                            overlay.activeTool = QtOverlayCrosshairTool(vertical=self.canvas.crosshair_vertical,
                                                                        horizontal=self.canvas.crosshair_horizontal,
                                                                        linewidth=self.canvas.crosshair_line_width,
                                                                        color=self.canvas.crosshair_color)
        self.show()

    def next(self):
        for i, col in enumerate(self.canvas.plots):
            for j, plot in enumerate(col):
                if plot:
                    widget = self.layout().itemAtPosition(j, i).widget()
                    widget._gnuplot_canvas.next()

    def prev(self):
        for i, col in enumerate(self.canvas.plots):
            for j, plot in enumerate(col):
                if plot:
                    widget = self.layout().itemAtPosition(j, i).widget()
                    widget._gnuplot_canvas.prev()

