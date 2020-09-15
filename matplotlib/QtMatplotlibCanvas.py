from abc import abstractmethod

from PyQt5 import QtGui
from PyQt5.QtCore import QPointF, QRectF
from PyQt5.QtWidgets import QVBoxLayout
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
import matplotlib.pyplot as plt
from copy import copy

from iplotlib.Plot import Plot
from iplotlib.Axis import RangeAxis
from qt.QtOverlayPlotCanvas import QtOverlayPlotCanvas
from qt.QtCanvasOverlay import QtCanvasOverlay

"""
Qt matplotlib canvas implementation
"""


class QtMatplotlibCanvas(QtOverlayPlotCanvas):

    def __init__(self):
        super().__init__()
        self.all_plots = []
        self.all_axes = []
        self.axes = None

        fig, axes = plt.subplots()
        self.axes = [axes]
        self._matplotlib_widget = FigureCanvas(fig)

        layout = QVBoxLayout()
        self.setLayout(layout)
        layout.addWidget(self._matplotlib_widget)

        self.overlay = QtCanvasOverlay(self._matplotlib_widget)

    def plot(self, plot: Plot = None):
        self.all_plots.append(plot)
        self.all_axes.append([copy(a) for a in plot.axes])
        self.replot()

    def replot(self):
        if len(self.axes):
            self.axes[0].clear()

        for a in self.all_axes:
            if len(a) > 0 and issubclass(type(a[0]), RangeAxis):
                xaxis = a[0]
                if xaxis.begin is not None and xaxis.end is not None:
                    self.axes[0].set_xlim([xaxis.begin, xaxis.end])

            if len(a) > 1 and issubclass(type(a[1]), RangeAxis):
                yaxis = a[1]
                if yaxis.begin is not None and yaxis.end is not None:
                    self.axes[0].set_ylim([yaxis.begin, yaxis.end])
        if self.axes:
            plot = self.all_plots[0]
            self.axes[0].plot(plot.data[0], plot.data[1], "bx", color="blue", label=plot.title)
            if plot.title is not None:
                self.axes[0].legend()

        event = QtGui.QResizeEvent(self._matplotlib_widget.size(), self._matplotlib_widget.size())
        self._matplotlib_widget.resizeEvent(event)

    def scene_to_graph(self, x, y):
        y_offset = self.axes[0].get_ylim()[0] + self.axes[0].get_ylim()[1]
        x_g, y_g = self.axes[0].transData.inverted().transform([x, y])
        return QPointF(x_g, -(y_g - y_offset))

    @abstractmethod
    def graphArea(self) -> QRectF:
        pass
