from PyQt5.QtGui import QResizeEvent
from PyQt5.QtWidgets import QGridLayout

from iplotlib.Canvas import Canvas
from iplotlib_gnuplot.GnuplotCanvas import GnuplotCanvas
from qt.QtCanvasOverlay import QtCanvasOverlay
from qt.QtPlotCanvas import QtPlotCanvas
from qt.gnuplotwidget.pyqt5gnuplotwidget.PyGnuplotWidget import QtGnuplotWidget

from qt.canvastools.QtCrosshairTool import QtOverlayCrosshairTool
from qt.canvastools.QtPanTool import QtOverlayPanTool
from qt.canvastools.QtZoomTool import QtOverlayZoomTool

"""
A plot canvas that uses multiple widgets in order to place multiple gnuplot graphs on a grid
This way it is possible not to use multiplot that interferes with mouse actions
"""
class QtGnuplotMultiwidgetCanvas(QtPlotCanvas):

    def __init__(self, canvas: Canvas = None, parent=None, toolbar=False, intercept_mouse=False):
        super().__init__(parent)
        if canvas:
            self.canvas = canvas
            self.setLayout(QGridLayout())
            self.layout().setSpacing(0)
            for i in range(canvas.cols):
                for j in range(canvas.rows):
                    widget = QtGnuplotWidget(self)
                    widget.setStyleSheet("border:0px none")


                    # overlay.activeTool = QtOverlayCrosshairTool()
                    # overlay.activeTool = QtOverlayZoomTool()
                    # overlay.activeTool = QtOverlayPanTool()

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

    def replot(self):
        for i, col in enumerate(self.canvas.plots):
            for j, plot in enumerate(col):
                if plot:
                    widget = self.layout().itemAtPosition(j, i).widget()
                    widget.statusTextChanged.connect(self.test)
                    gnuplot_canvas = widget._gnuplot_canvas
                    gnuplot_canvas.write("set term qt widget '{}' size {},{} font 'Arial,8' noenhanced".format(
                        widget.serverName(),
                        widget.geometry().width(),
                        widget.geometry().height()),True)
                    gnuplot_canvas.process_layout()


    def test(self,e):
        widget = self.sender()

        # print("TEST"+str(e)+' , ' + str(self.sender()))

    def resizeEvent(self, event: QResizeEvent) -> None:
        self.replot()
