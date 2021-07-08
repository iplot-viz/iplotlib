from abc import ABC, abstractmethod

from qtpy.QtCore import QObject
from qtpy.QtGui import QPainter

"""
This abstract class represents a canvas tool, usually interacts with events such as keyboard or mouse
TODO: Is it possible to make this independent from widget library?
TODO: Tools should redraw when size of the canvas changes in order to reflect range changes
"""


class QtOverlayCanvasTool(QObject):

    def __init__(self):
        super().__init__()

    def process_paint(self, widget, painter: QPainter):
        pass

    def process_event(self, widget, event):
        pass

    def __repr__(self):
        return type(self).__class__.__name__
