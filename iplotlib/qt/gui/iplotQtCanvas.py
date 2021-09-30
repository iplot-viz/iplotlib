from abc import abstractmethod

from PySide2.QtCore import QSize
from PySide2.QtWidgets import QWidget

from iplotlib.core.canvas import Canvas


# TODO: Add possibility of MOUSEMODE/state between canvases (show crosshair/pan/zoom) between two canvases, possibility of handling events independently
class IplotQtCanvas(QWidget):
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
