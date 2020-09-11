from PyQt5 import QtGui
from PyQt5.QtCore import QProcess, QByteArray, QPoint, QPointF, Qt
from PyQt5.QtWidgets import QWidget, QSizePolicy, QVBoxLayout
from gnuplot.pyqt5gnuplotwidget.PyGnuplotWidget import QtGnuplotWidget
from qt.QtCanvasOverlay import QtCanvasOverlay
from api.Plot import Plot
from qt.QtPlotCanvas import QtPlotCanvas

"""
Qt gnuplot canvas implementation
"""


class QtGnuplotCanvas(QtPlotCanvas):

    def __init__(self, gnuplot_path: str = "gnuplot"):
        super(QtGnuplotCanvas, self).__init__()
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
            self.__exec_and_read("set term qt widget \"" + self.gnuplot_widget.serverName() + "\" size " + str(self.gnuplot_widget.geometry().width()) + "," + str(self.gnuplot_widget.geometry().height()), 0)

            self.__exec_and_read("set xrange [-20:20]", 0)
            self.__exec_and_read("set yrange [-30:30]", 0)
            self.__exec_and_read("set multiplot", 0)
            self.__exec_and_read("plot x*x", 0)
            # self.__exec_and_read("plot x w l lt 3", 0)
            self.__exec_and_read("unset multiplot", 0)
        else:
            self.overlay = None
            print("Error initializing gnuplot process")

    def scene_to_graph(self, x, y) -> QPointF:
        return QPointF(self.gnuplot_widget.sceneToGraph(0, x), self.gnuplot_widget.sceneToGraph(1, y))

    def plot(self, plot: Plot = None):
        self.all_plots.append(plot)
        self.all_axes.append([{"min":a.min,"max":a.max} for a in plot.axes])
        self.replot()

    def replot(self):
        for a in self.all_axes:
            if len(a) > 0:
                self.__exec_and_read("set xrange ["+str(a[0]['min'])+":"+str(a[0]['max'])+"]")
            if len(a) > 1:
                self.__exec_and_read("set yrange ["+str(a[1]['min'])+":"+str(a[1]['max'])+"]")
        if self.all_axes:
            self.__exec_and_read("plot '-'")
            for x,y in zip(self.all_plots[0].data[0],self.all_plots[0].data[1]):
                self.__exec(str(x)+" "+str(y))
            self.__exec("e")
        self.gnuplot_widget.replot()

    def activateTool(self, tool):
        if self.overlay is not None:
            self.overlay.activateTool(tool)

    def __init_gnuplot(self):
        self.gnuplot_process = QProcess()
        self.gnuplot_process.setProcessChannelMode(QProcess.MergedChannels)
        self.gnuplot_process.start(self.gnuplot_path)
        self.gnuplot_process.waitForStarted()
        return self.gnuplot_process.state() != QProcess.NotRunning

    #TODO: Is there a way to avoid copying here?
    def __exec(self, command:str):
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
