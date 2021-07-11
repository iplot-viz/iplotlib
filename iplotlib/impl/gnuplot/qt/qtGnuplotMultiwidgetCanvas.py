from PyQt5.QtCore import QMargins, QPoint, QPointF
from PyQt5.QtWidgets import QGridLayout, QVBoxLayout, QWidget

from iplotlib.core.canvas import Canvas
from iplotlib.core.plot import PlotXY
from iplotlib.impl.gnuplot.gnuplotCanvas import GnuplotCanvas
from qt.QtCanvasOverlay import QtCanvasOverlay
from qt.QtPlotCanvas import QtPlotCanvas
from qt.gnuplot.QtGnuplotWidget2 import QtGnuplotWidget2

from qt.canvastools.QtCrosshairTool import QtOverlayCrosshairTool
from qt.canvastools.QtPanTool import QtOverlayPanTool
from qt.canvastools.QtZoomTool import QtOverlayZoomTool

import sip

"""
A plot canvas that uses multiple widgets in order to place multiple gnuplot graphs on a grid
This way it is possible not to use multiplot that interferes with mouse actions
"""


class QtGnuplotMultiwidgetCanvas(QtPlotCanvas):


    """
    This widget uses a QWidget container because there is no way to reset grid row and columns in a grid layout
    Therefore when this widget is redrawn with different Canvas instance it is created from scratch,
    there is no way to reset QGridLayout if number of rows/columns is smaller
    """
    def __init__(self, canvas: Canvas = None, parent=None):
        super().__init__(parent)
        self.container = None
        self.setLayout(QVBoxLayout())
        self.layout().setContentsMargins(QMargins())
        self.gnuplot_widgets = []
        self.mouse_mode = None
        self.set_canvas(canvas)


    def set_canvas(self, canvas):
        self.hide()  # Hide/Show combination will cause only one resizeEvent per entire widget therefore it will be drawn only once

        if self.container:
            for widget in self.gnuplot_widgets:
                widget.cleanup()
                widget.setParent(None)
                sip.delete(widget)
            self.container.setParent(None)
            self.gnuplot_widgets.clear()

        self.container = QWidget(self)
        self.container.setStyleSheet("background-color: white")
        self.container.setLayout(QGridLayout())
        self.container.layout().setSpacing(0)
        self.container.layout().setContentsMargins(QMargins())
        self.layout().addWidget(self.container)

        if canvas:
            self.canvas = canvas

            for i in range(self.canvas.rows):
                self.container.layout().setRowStretch(i, 2)

            for i in range(self.canvas.cols):
                self.container.layout().setColumnStretch(i, 2)

            for i, col in enumerate(self.canvas.plots):
                for j, plot in enumerate(col):
                    if plot and plot.signals:
                        if len(plot.signals.keys()) > 1:
                            vbox = QWidget(self)
                            vbox.setLayout(QVBoxLayout())
                            vbox.layout().setSpacing(0)
                            vbox.layout().setContentsMargins(QMargins())
                            for stack_idx, signals in enumerate(plot.signals.values()):
                                widget = QtGnuplotWidget2(self)
                                c = Canvas()
                                p = PlotXY()
                                for signal in signals:
                                    p.add_signal(signal)
                                c.add_plot(p)
                                show_x_axis = True if stack_idx+1 == len(plot.signals.values()) else False
                                bmargin = None if stack_idx + 1 == len(plot.signals.values()) else 0
                                tmargin = None if stack_idx == 0 else 0
                                widget._gnuplot_canvas = GnuplotCanvas(c,show_x_axis=show_x_axis, bmargin=bmargin, tmargin=tmargin)
                                widget._overlay = QtCanvasOverlay(widget)
                                vbox.layout().addWidget(widget)
                                self.gnuplot_widgets.append(widget)
                            self.container.layout().addWidget(vbox, j, i)
                        else:
                            widget = QtGnuplotWidget2(self)
                            self.container.layout().addWidget(widget, j, i)
                            c = Canvas()
                            c.add_plot(plot)
                            widget._gnuplot_canvas = GnuplotCanvas(c)
                            widget._overlay = QtCanvasOverlay(widget)
                            self.gnuplot_widgets.append(widget)

            self.set_mouse_mode(self.mouse_mode or canvas.mouse_mode)

        self.show()

    def set_mouse_mode(self, mode: str):
        self.mouse_mode = mode
        for widget in self.gnuplot_widgets:
            if hasattr(widget,"_overlay"):
                if mode == Canvas.MOUSE_MODE_CROSSHAIR:
                    widget._overlay.activeTool = QtOverlayCrosshairTool(vertical=self.canvas.crosshair_vertical,
                                                                horizontal=self.canvas.crosshair_horizontal,
                                                                linewidth=self.canvas.crosshair_line_width,
                                                                color=self.canvas.crosshair_color)

                    widget._overlay.activeTool.crosshairMoved.connect(self._crosshairMoved)
                elif mode == Canvas.MOUSE_MODE_PAN:
                    widget._overlay.activeTool = QtOverlayPanTool()
                    widget._overlay.activeTool.panAction.connect(self._panAction)
                    pass
                elif mode == Canvas.MOUSE_MODE_ZOOM:
                    widget._overlay.activeTool = QtOverlayZoomTool()

    def screen_to_graph(self, point: QPoint):
        if self.graph_bounds and self.graph_screen_bounds:
            dx = (self.graph_bounds[2]-self.graph_bounds[0])/(self.graph_screen_bounds[2]-self.graph_screen_bounds[0])
            dy = (self.graph_bounds[3]-self.graph_bounds[1])/(self.graph_screen_bounds[3]-self.graph_screen_bounds[1])

            x = self.graph_bounds[0]+(point.x()-self.graph_screen_bounds[0])*dx
            y = self.graph_bounds[1] + (self.geometry().height()-point.y()-self.graph_screen_bounds[1])*dy
            return QPointF(x, y)

    def graph_to_screen(self, point: QPointF):
        if self.graph_bounds and self.graph_screen_bounds:
            dx = (self.graph_screen_bounds[2]-self.graph_screen_bounds[0])/(self.graph_bounds[2]-self.graph_bounds[0])
            dy = (self.graph_screen_bounds[3]-self.graph_screen_bounds[1])/(self.graph_bounds[3]-self.graph_bounds[1])
            x = self.graph_screen_bounds[0]+(point.x()-self.graph_bounds[0])*dx
            y = self.geometry().height() - (self.graph_screen_bounds[1] + (point.y()-self.graph_bounds[1])*dy)
            return QPointF(x, y)


    def _crosshairMoved(self, pos):
        for widget in self.gnuplot_widgets:
            if isinstance(widget._overlay.activeTool, QtOverlayCrosshairTool):
                widget._overlay.activeTool.graph_pos = pos
                widget.update()

    def _panAction(self, x1, y1, x2, y2):
        for widget in self.gnuplot_widgets:
            if widget._gnuplot_canvas:
                widget._gnuplot_canvas.process_event(None)

    def next(self):
        for i, col in enumerate(self.canvas.plots):
            for j, plot in enumerate(col):
                if plot:
                    widget = self.layout().itemAtPosition(j, i).main_widget()
                    widget._gnuplot_canvas.next()

    def prev(self):
        for i, col in enumerate(self.canvas.plots):
            for j, plot in enumerate(col):
                if plot:
                    widget = self.layout().itemAtPosition(j, i).main_widget()
                    widget._gnuplot_canvas.prev()
