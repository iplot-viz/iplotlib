from PyQt5.QtCore import *
from PyQt5.QtGui import *
from PyQt5.QtWidgets import *
from qt import QtOverlayCanvasTool

"""
This class represents an overlay layer that is put on plot canvas
Additional objects such as crosshair are drawn on this overlay
"""


class QtCanvasOverlay(QWidget):

    def __init__(self, parent=None,dependentOverlays=[]):
        super().__init__(parent=parent)
        self.dependentOverlays=[]
        self.activeTool: QtOverlayCanvasTool = None  # TODO: In the future make it a list
        self.setMouseTracking(True)
        self.installEventFilter(self)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setGeometry(0, 0, self.parent().geometry().width(), self.parent().geometry().height())

    def activateTool(self, tool: QtOverlayCanvasTool):
        self.activeTool = tool

    def paintEvent(self, e):
        self.setGeometry(0, 0, self.parent().geometry().width(), self.parent().geometry().height())  # TODO: Can actually be done only on resize, not needed for every paint


        if self.activeTool is not None:
            self.activeTool.process_paint(QPainter(self))
            for overlay in self.dependentOverlays:
                if overlay is not self:
                    overlay.update()
                    # self.activeTool.process_paint(QPainter(overlay))
            pass

    def eventFilter(self, source, event):

        if self.activeTool is not None:
            if self.activeTool.process_event(self.parent().parent(), event):
                self.update()
        return False
