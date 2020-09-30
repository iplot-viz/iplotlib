from PyQt5.QtGui import QResizeEvent
from PyQt5.QtWidgets import QGridLayout, QWidget

from iplotlib.Canvas import Canvas
from iplotlib_gnuplot.GnuplotCanvas import GnuplotCanvas
from qt.QtPlotCanvas import QtPlotCanvas
from qt.gnuplotwidget.pyqt5gnuplotwidget.PyGnuplotWidget import QtGnuplotWidget

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
                    self.layout().addWidget(widget, j, i)

        for i, col in enumerate(self.canvas.plots):
            for j, plot in enumerate(col):
                widget = self.layout().itemAtPosition(j, i).widget()
                c = Canvas()
                c.add_plot(plot)
                widget.__gnuplot_canvas = GnuplotCanvas(c)

    def replot(self):
        for i, col in enumerate(self.canvas.plots):
            for j, plot in enumerate(col):
                if plot:
                    widget = self.layout().itemAtPosition(j, i).widget()
                    gnuplot_canvas = widget.__gnuplot_canvas
                    print("PLOT at " + str(i) + "," + str(j) + " widget: " + str(widget) + " plot: " + str(plot))
                    gnuplot_canvas.write("set term qt widget '{}' size {},{} font 'Arial,8' noenhanced".format(
                        widget.serverName(),
                        widget.geometry().width(),
                        widget.geometry().height()), True)
                    gnuplot_canvas.process_layout()


    def resizeEvent(self, event: QResizeEvent) -> None:
        self.replot()
