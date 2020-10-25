from PyQt5.QtCore import Qt
from PyQt5.QtGui import QResizeEvent
from PyQt5.QtWidgets import QVBoxLayout, QPushButton, QToolBar
from qt.gnuplotwidget.pyqt5gnuplotwidget.PyGnuplotWidget import QtGnuplotWidget

from iplotlib.Canvas import Canvas
from iplotlib_gnuplot.GnuplotCanvas import GnuplotCanvas
from qt.QtPlotCanvas import QtPlotCanvas


class QtGnuplotCanvas2(QtPlotCanvas):

    def __init__(self, canvas: Canvas = None, parent=None):
        super().__init__(parent)

        self.gnuplot_canvas = GnuplotCanvas(canvas)
        self.qt_canvas = QtGnuplotWidget(self)

        self.setLayout(QVBoxLayout())
        self.layout().addWidget(self.qt_canvas)

    def replot(self):
        self.gnuplot_canvas.write("set term qt widget '{}' size {},{} font 'Arial,8' noenhanced".format(
            self.qt_canvas.serverName(),
            self.qt_canvas.geometry().width(),
            self.qt_canvas.geometry().height()))
        self.gnuplot_canvas.process_layout()

    def resizeEvent(self, event: QResizeEvent) -> None:
        self.replot()
