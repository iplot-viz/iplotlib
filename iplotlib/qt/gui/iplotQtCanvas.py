from abc import abstractmethod

from PySide2.QtCore import QSize
from PySide2.QtWidgets import QWidget

from iplotlib.core.canvas import Canvas


class IplotQtCanvas(QWidget):
    """
    Base class for all Qt related canvas implementaions
    """

    def __init__(self, parent=None, **kwargs):
        super().__init__(parent)
        self._mmode = None

    @abstractmethod
    def undo(self):
        """history: undo"""

    @abstractmethod
    def redo(self):
        """history: redo"""

    @abstractmethod
    def drop_history(self):
        """history: clear undo history. after this, can no longer undo"""

    @abstractmethod
    def refresh(self):
        """Refresh the canvas from the current iplotlib.core.Canvas instance.
        """
        self.set_canvas(self.get_canvas())
    
    @abstractmethod
    def reset(self):
        """Remove the current iplotlib.core.Canvas instance.
            Typical implementation would be a call to set_canvas with None argument.
        """
        self.set_canvas(None)

    @abstractmethod
    def set_mouse_mode(self, mode: str):
        """Sets mouse mode of this canvas"""
        self._mmode = mode

    @abstractmethod
    def set_canvas(self, canvas: Canvas):
        """Sets new version of iplotlib canvas and redraw"""

    @abstractmethod
    def get_canvas(self) -> Canvas:
        """Gets current iplotlib canvas"""

    def sizeHint(self):
        return QSize(900, 400)

    def export_dict(self):
        return self.get_canvas().to_dict() if self.get_canvas() else None
    
    def import_dict(self, input_dict):
        self.set_canvas(Canvas.from_dict(input_dict))

    def export_json(self):
        return self.get_canvas().to_json() if self.get_canvas() is not None else None

    def import_json(self, json):
        self.set_canvas(Canvas.from_json(json))
