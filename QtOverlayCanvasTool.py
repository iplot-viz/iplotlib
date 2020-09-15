from abc import ABC, abstractmethod

from PyQt5.QtGui import QPainter
from PyQt5.QtWidgets import QWidget

from qt.QtPlotCanvas import QtPlotCanvas

"""
This abstract class represents a canvas tool, usually interacts with events such as keyboard or mouse
TODO: Is it possible to make this independent from widget library?
TODO: Tools should redraw when size of the canvas changes in order to reflect range changes
"""


class QtOverlayCanvasTool(ABC):

    @abstractmethod
    def process_paint(self, painter: QPainter):
        pass

    @abstractmethod
    def process_event(self, canvas: QtPlotCanvas, event):
        pass

    def __repr__(self):
        return type(self).__class__.__name__
