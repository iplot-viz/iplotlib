from PyQt5.QtCore import Qt
from PyQt5.QtGui import QResizeEvent
from PyQt5.QtWidgets import QVBoxLayout, QPushButton, QToolBar
from qt.gnuplotwidget.pyqt5gnuplotwidget.PyGnuplotWidget import QtGnuplotWidget

from iplotlib.Canvas import Canvas
from iplotlib_gnuplot.GnuplotCanvas import GnuplotCanvas
from qt.QtPlotCanvas import QtPlotCanvas


class QtGnuplotCanvas2(QtPlotCanvas):

    def __init__(self, canvas: Canvas = None, parent=None, toolbar=False, intercept_mouse=False):
        super().__init__(parent)

        self.gnuplot_canvas = GnuplotCanvas(canvas)

        self.qt_canvas = QtGnuplotWidget(self)
        self.setLayout(QVBoxLayout())

        if intercept_mouse:
            self.setMouseTracking(True)
            self.installEventFilter(self)
            self.qt_canvas.setAttribute(Qt.WA_TransparentForMouseEvents)

        if toolbar:
            self.layout().addWidget(self.createToolbar())

        self.layout().addWidget(self.qt_canvas)

    def replot(self):
        self.gnuplot_canvas.write("set term qt widget '{}' size {},{} font 'Arial,8' noenhanced".format(
            self.qt_canvas.serverName(),
            self.qt_canvas.geometry().width(),
            self.qt_canvas.geometry().height()))
        self.gnuplot_canvas.process_layout()

    def resizeEvent(self, event: QResizeEvent) -> None:
        self.replot()


    def createToolbar(self):
        toolbar = QToolBar()
        refresh_button = QPushButton("Refresh")
        refresh_button.clicked.connect(self.replot)
        toolbar.addWidget(refresh_button)
        return toolbar

    def eventFilter(self, source, event):
        print("GNUPLOT: handle event: " + str(event))
        return False
