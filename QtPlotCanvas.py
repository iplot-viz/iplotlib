from abc import abstractmethod

from PyQt5 import QtCore
from PyQt5.QtCore import QSize, QPointF, QRectF
from PyQt5.QtGui import QMouseEvent
from PyQt5.QtWidgets import QWidget

from iplotlib.Plot import Plot
from iplotlib.ui.Event import Event, MouseEvent

"""
Main abstraction of a Qt plot canvas.
A Qt plot canvas is used to plot multiple plots and present them in form of a Qt widget
"""


class QtPlotCanvas(QWidget):

    def enableTool(self,tool):
        print("ENABLE", tool)

    def createEvent(self,event):
        ret = MouseEvent()
        if event.type() == QtCore.QEvent.MouseMove:
            ret.type = "mouseMove"
            ret.x = event.x()
            ret.y = event.y()
        elif event.type() == QtCore.QEvent.Enter:
            ret.type = "mouseEnter"
        elif event.type() == QtCore.QEvent.Leave:
            ret.type = "mouseLeave"
        else:
            # print("Unknown event: " + str(event.type()))
            pass
        return ret

    # Old api, will be deprecated

    @abstractmethod
    def plot(self, plot: Plot = None):
        pass

    @abstractmethod
    def replot(self):
        pass

    @abstractmethod
    def get_overlay(self):
        return self.overlay

    def plots(self) -> list:
        return self.all_plots

    def axes_list(self) -> list:
        return self.all_axes

    @abstractmethod
    def graphArea(self) -> QRectF:
        pass

    @abstractmethod
    def scene_to_graph(self, x, y) -> QPointF:
        pass

    # This will be applied as initial size
    def sizeHint(self):
        return QSize(900, 200)


