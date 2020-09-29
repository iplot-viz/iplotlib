from time import sleep

from PyQt5.QtCore import QSize
from PyQt5.QtGui import QResizeEvent
from PyQt5.QtWidgets import QVBoxLayout, QPushButton, QToolBar

from iplotlib_gnuplot.GnuplotCanvas import GnuplotCanvas
from qt.QtPlotCanvas import QtPlotCanvas
from qt.gnuplotwidget.pyqt5gnuplotwidget.PyGnuplotWidget import QtGnuplotWidget


class QtGnuplotCanvas2(QtPlotCanvas):

    def __init__(self, parent=None, plots=None, canvas: GnuplotCanvas = None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.installEventFilter(self)

        self.__real_size_known = False  # Ugly hack but it seems than similar method is present in official gnuplot src
        if canvas is None:
            if plots is not None:
                self.gnuplot_canvas = GnuplotCanvas(plots)
            else:
                self.gnuplot_canvas = GnuplotCanvas()
        else:
            self.gnuplot_canvas = canvas

        self.qt_canvas = QtGnuplotWidget(self)
        layout = QVBoxLayout()
        self.setLayout(layout)

        layout.addWidget(self.createToolbar())
        layout.addWidget(self.qt_canvas)

    def replot(self):
        self.gnuplot_canvas.write("set term qt widget '{}' size {},{} font 'Arial,8' noenhanced".format(
            self.qt_canvas.serverName(),
            self.qt_canvas.geometry().width(),
            self.qt_canvas.geometry().height()), True)
        self.gnuplot_canvas.process_layout()

    def resizeEvent(self, event: QResizeEvent) -> None:
        if self.isVisible() and not self.__real_size_known:
            self.__real_size_known = True
            self.replot()

    def createToolbar(self):
        toolbar = QToolBar()
        refresh_button = QPushButton("Refresh")
        refresh_button.clicked.connect(self.replot)
        toolbar.addWidget(refresh_button)
        return toolbar


    def eventFilter(self, source, event):
        # print("Process event: " + str(event))
        return False