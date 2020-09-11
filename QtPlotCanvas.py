from abc import abstractmethod

from PyQt5.QtCore import QSize, QPointF
from PyQt5.QtWidgets import QWidget

from api.Plot import Plot

"""
Main abstraction of a Qt plot canvas.
A Qt plot canvas is used to plot multiple plots and present them in form of a Qt widget
"""


class QtPlotCanvas(QWidget):

    @abstractmethod
    def plot(self, plot: Plot = None):
        pass

    @abstractmethod
    def replot(self):
        pass

    @abstractmethod
    def activateTool(self, tool):
        pass

    def plots(self) -> list:
        return self.all_plots

    def axes_list(self) -> list:
        return self.all_axes

    @abstractmethod
    def scene_to_graph(self, x, y) -> QPointF:
        pass

    # This will be applied as initial size
    def sizeHint(self):
        return QSize(900, 200)
