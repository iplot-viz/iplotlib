from abc import abstractmethod

from PyQt5.QtCore import QProcess, QByteArray, QPointF, Qt, QRectF
from PyQt5.QtWidgets import QWidget, QVBoxLayout
from gnuplot.pyqt5gnuplotwidget.PyGnuplotWidget import QtGnuplotWidget

from iplotlib.Axis import RangeAxis
from qt.QtCanvasOverlay import QtCanvasOverlay
from iplotlib.Plot import Plot
from qt.QtOverlayPlotCanvas import QtOverlayPlotCanvas
from copy import copy
"""
Qt gnuplot canvas implementation
"""


class QtGnuplotCanvas(QtOverlayPlotCanvas):

    def __init__(self, gnuplot_path: str = "gnuplot"):
        super().__init__()
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.all_plots = []
        self.all_axes = []

        self.gnuplot_path = gnuplot_path
        self.gnuplot_process: QProcess = None
        self.gnuplot_widget: QWidget = None

        layout = QVBoxLayout()
        self.setLayout(layout)
        self.gnuplot_widget = QtGnuplotWidget()
        layout.addWidget(self.gnuplot_widget)

        status = self.__init_gnuplot()

        #TODO: We should run "set terminal" alone first and check if qt terminal is available
        if status:
            self.overlay = QtCanvasOverlay(self.gnuplot_widget)
            self.__exec("set term qt widget '{}' size {},{}".format(
                self.gnuplot_widget.serverName(),
                self.gnuplot_widget.geometry().width(),
                self.gnuplot_widget.geometry().height()))
        else:
            self.overlay = None
            print("Error initializing gnuplot process")

    def scene_to_graph(self, x, y) -> QPointF:
        return QPointF(self.gnuplot_widget.sceneToGraph(0, x), self.gnuplot_widget.sceneToGraph(1, y))

    def plot(self, plot: Plot = None):
        self.all_plots.append(plot)
        self.all_axes.append([copy(a) for a in plot.axes])
        self.replot()

    def replot(self):
        for a in self.all_axes:
            if len(a) > 0 and issubclass(type(a[0]), RangeAxis):
                xaxis = a[0]
                if xaxis.begin is not None and xaxis.end is not None:
                    self.__exec_and_read("set xrange [{}:{}]".format(xaxis.begin, xaxis.end))

            if len(a) > 1 and issubclass(type(a[1]), RangeAxis):
                yaxis = a[1]
                if yaxis.begin is not None and yaxis.end is not None:
                    self.__exec_and_read("set yrange [{}:{}]".format(yaxis.begin, yaxis.end))

        if self.all_axes:
            plot = self.all_plots[0]
            if plot.title is not None:
                self.__exec_and_read("plot '-' title '{}'".format(plot.title))
            else:
                self.__exec_and_read("plot '-'")

            for x, y in zip(plot.data[0], plot.data[1]):
                self.__exec(str(x)+" "+str(y))
            self.__exec("e")

        self.gnuplot_widget.replot()

    @abstractmethod
    def graphArea(self) -> QRectF:
        pass

    def __init_gnuplot(self):
        self.gnuplot_process = QProcess()
        self.gnuplot_process.setProcessChannelMode(QProcess.MergedChannels)
        self.gnuplot_process.start(self.gnuplot_path)
        self.gnuplot_process.waitForStarted()
        return self.gnuplot_process.state() != QProcess.NotRunning

    def __exec(self, command: str):
        command_array = QByteArray()
        command_array.append(command+'\n')
        self.gnuplot_process.write(command_array)

    def __exec_and_read(self, command: str, msecs: int = 0):
        self.gnuplot_process.waitForReadyRead(0)
        trailing = self.gnuplot_process.readAllStandardOutput()
        while not trailing.isEmpty():
            trailing = self.gnuplot_process.readAllStandardOutput()

        command_array = QByteArray()
        command_array.append(command+'\n')
        self.gnuplot_process.write(command_array)
        self.gnuplot_process.waitForReadyRead(msecs)
        answer = self.gnuplot_process.readAllStandardOutput()
        if len(answer):
            print("Gnuplot: " + str(answer) + " for command: " + command)

        return answer
