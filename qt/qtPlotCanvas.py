from abc import abstractmethod

from PyQt5.QtCore import QMargins, QSize, Qt
from PyQt5.QtWidgets import QVBoxLayout, QWidget

from iplotlib.core.canvas import Canvas

#TODO: if we have two canvases two canvases should be present in the preferences tree
#TODO: Remove the detach button and make it MINT-specific
#TODO: Add possibility of MOUSEMODE/state between canvases (show crosshair/pan/zoom) between two canvases, possibility of handling events independently
class QtPlotCanvas(QWidget):
    """
    Base class for all Qt related canvas implementaions
    """
    def __init__(self, parent=None, **kwargs):
        super().__init__(parent)

    @abstractmethod
    def back(self):
        """history: back"""

    @abstractmethod
    def forward(self):
        """history: forward"""

    @abstractmethod
    def set_mouse_mode(self, mode: str):
        """Sets mouse mode of this canvas"""

    @abstractmethod
    def set_canvas(self, canvas: Canvas):
        """Sets new version of iplotlib canvas and redraw"""

    @abstractmethod
    def get_canvas(self) -> Canvas:
        """Gets current iplotlib canvas"""

    def sizeHint(self):
        return QSize(900, 400)

    def export_json(self):
        return self.get_canvas().to_json() if self.get_canvas() is not None else None

    def import_json(self, json):
        self.set_canvas(Canvas.from_json(json))
