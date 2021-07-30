from iplotLogging import setupLogger as sl
from vtkmodules.qt.QVTKRenderWindowInteractor import QVTKRenderWindowInteractor, PyQtImpl
from vtkmodules.vtkRenderingCore import vtkRenderer
import inspect
import qtpy

from qtpy.QtWidgets import QVBoxLayout, QWidget

from iplotlib.impl.vtk.vtkCanvas import VTKCanvas, Canvas
from iplotlib.qt.qtPlotCanvas import QtPlotCanvas

# Maintain consistent qt api across vtk and iplotlib
import vtkmodules.qt
vtkmodules.qt.PyQtImpl = qtpy.API_NAME

# vtk requirements

# iplot utilities
logger = sl.get_logger(__name__, "DEBUG")

try:
    assert(PyQtImpl == qtpy.API_NAME)
except AssertionError:
    logger.exception("Sanity check failed")


class QtVTKCanvas(QtPlotCanvas):
    """A Qt container widget that emebeds a VTKCanvas.
        See set_canvas, get_canvas
    """

    def __init__(self, parent: QWidget = None, **kwargs):
        """Initialize a VTK Canvas embedded in QWidget

        Args:
            parent (QWidget, optional): Parent QWidget. Defaults to None.
        """
        super(QtPlotCanvas, self).__init__(parent=parent, **kwargs)

        self._vtk_canvas = VTKCanvas(2, 2)

        self._qvtk_render_widget = QVTKRenderWindowInteractor(parent, **kwargs)

        # laid out vertically.
        vLayout = QVBoxLayout(self)
        vLayout.addWidget(self._qvtk_render_widget)
        self.setLayout(vLayout)

        # Let the view render its scene into our render window
        self._vtk_canvas.view.SetRenderWindow(self._qvtk_render_widget.GetRenderWindow())

    def back(self):
        """history: back"""
        pass

    def forward(self):
        """history: forward"""
        pass

    def set_mouse_mode(self, mode: str):
        """Sets mouse mode of this canvas"""
        pass

    def set_canvas(self, canvas: Canvas):
        """Sets new iplotlib canvas and redraw"""

        super().set_canvas(canvas)  # does nothing
        for attr_name, attr_value in inspect.getmembers(Canvas):
            if not attr_name.startswith("__") and not attr_name.endswith("__") and not inspect.ismethod(attr_value):
                setattr(self._vtk_canvas, attr_name, getattr(canvas, attr_name))

        self._vtk_canvas.refresh()
        self._qvtk_render_widget.repaint()

    def get_canvas(self) -> Canvas:
        """Gets current iplotlib canvas"""
        return self._vtk_canvas

    def get_qvtk_render_widget(self) -> QVTKRenderWindowInteractor:
        return self._qvtk_render_widget