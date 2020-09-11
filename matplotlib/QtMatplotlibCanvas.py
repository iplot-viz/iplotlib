from PyQt5 import QtGui
from PyQt5.QtCore import QPointF
from PyQt5.QtWidgets import QWidget, QVBoxLayout
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
import matplotlib.pyplot as plt
# from qtconsole.qt import QtGui

from api.Plot import Plot
from qt.QtPlotCanvas import QtPlotCanvas
from qt.QtCanvasOverlay import QtCanvasOverlay

"""
Qt matplotlib canvas implementation
"""


class QtMatplotlibCanvas(QtPlotCanvas):


    def __init__(self):
        super(QtMatplotlibCanvas, self).__init__()
        self.all_plots = []
        self.all_axes = []
        self.axes = None

        fig, axes = plt.subplots()
        self.axes = [axes]
        self.matplotlib_widget = FigureCanvas(fig)

        layout = QVBoxLayout()
        self.setLayout(layout)
        layout.addWidget(self.matplotlib_widget)

        self.overlay = QtCanvasOverlay(self.matplotlib_widget)

    def plot(self, plot: Plot = None):
        self.all_plots.append(plot)
        self.all_axes.append([{"min":a.min,"max":a.max} for a in plot.axes])
        self.replot()

    def activateTool(self, tool):
        self.overlay.activateTool(tool)

    def replot(self):
        for a in self.all_axes:
                if len(a) > 0:
                    self.axes[0].set_xlim([a[0]['min'], a[0]['max']])
                if len(a) > 1:
                    self.axes[0].set_ylim([a[1]['min'], a[1]['max']])
        if self.axes:
            print("APD: " + str(self.all_plots[0].data))
            self.axes[0].plot(self.all_plots[0].data[0],self.all_plots[0].data[1], "bx",color="blue")

        event = QtGui.QResizeEvent(self.matplotlib_widget.size(), self.matplotlib_widget.size())
        self.matplotlib_widget.resizeEvent(event)

    def scene_to_graph(self, x, y):
        y_offset = self.axes[0].get_ylim()[0] + self.axes[0].get_ylim()[1]
        x_g, y_g = self.axes[0].transData.inverted().transform([x, y])
        return QPointF(x_g, -(y_g - y_offset))
