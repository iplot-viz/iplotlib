from abc import ABC, ABCMeta, abstractmethod

from PyQt5.QtCore import QPoint, QPointF, QSize
from PyQt5.QtWidgets import QWidget
from iplotlib.Canvas import Canvas

"""
Main abstraction of a Qt plot canvas.
A Qt plot canvas is used to plot multiple plots and present them in form of a Qt widget
"""


class QtPlotCanvas(QWidget):

    @abstractmethod
    def back(self):
        """history: back"""

    @abstractmethod
    def forward(self):
        """history: forward"""

    @abstractmethod
    def process_canvas_toolbar(self, toolbar):
        """Post process canvas toolbar, add custom canvas-specific buttons etc..."""

    @abstractmethod
    def set_mouse_mode(self, mode: str):
        """Sets mouse mode of this canvas"""

    @abstractmethod
    def set_canvas(self, canvas: Canvas):
        """Updates canvas"""

    @abstractmethod
    def get_canvas(self):
        """Gets current canvas"""

    def sizeHint(self):
        return QSize(900, 400)
