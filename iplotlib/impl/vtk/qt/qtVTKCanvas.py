import inspect
import qtpy

from qtpy.QtWidgets import QVBoxLayout, QWidget
from qtpy.QtGui import QResizeEvent

from iplotlib.impl import CanvasFactory, Canvas, VTKCanvas
from iplotlib.qt.qtPlotCanvas import QtPlotCanvas

# Maintain consistent qt api across vtk and iplotlib
import vtkmodules.qt
vtkmodules.qt.PyQtImpl = qtpy.API_NAME

# vtk requirements
from vtkmodules.qt.QVTKRenderWindowInteractor import QVTKRenderWindowInteractor, PyQtImpl
from vtkmodules.vtkCommonCore import vtkCommand

# iplot utilities
from iplotLogging import setupLogger as sl
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

        self.impl_canvas = CanvasFactory.new("vtk")
        self.render_widget = QVTKRenderWindowInteractor(parent, **kwargs)
        # Let the view render its scene into our render window
        self.impl_canvas.view.SetRenderWindow(self.render_widget.GetRenderWindow())

        # laid out vertically.
        v_layout = QVBoxLayout(self)
        v_layout.addWidget(self.render_widget)
        self.setLayout(v_layout)

        # callback to process mouse movements
        self.mouse_move_cb_tag = self.render_widget.AddObserver(
            vtkCommand.MouseMoveEvent, self.mouse_move_callback)

    def resizeEvent(self, event: QResizeEvent):
        size = event.size()
        if not size.width():
            size.setWidth(5)
        
        if not size.height():
            size.setHeight(5)

        new_ev = QResizeEvent(size, event.oldSize())
        self.impl_canvas.resize(size.width(), size.height())
        logger.info(f"Resize {new_ev.oldSize()} -> {new_ev.size()}")

        return super().resizeEvent(new_ev)

    def back(self):
        """history: back"""
        pass

    def forward(self):
        """history: forward"""
        pass

    def set_mouse_mode(self, mode: str):
        """Sets mouse mode of this canvas"""
        self.impl_canvas.mouse_mode = mode

    def mouse_move_callback(self, obj, ev):
        mousePos = obj.GetEventPosition()
        self.impl_canvas.crosshair.onMove(mousePos)

    def set_canvas(self, canvas: Canvas):
        """Sets new iplotlib canvas and redraw"""

        super().set_canvas(canvas)  # does nothing

        if not isinstance(canvas, Canvas) and isinstance(self.impl_canvas, VTKCanvas):
            self.impl_canvas.clear()
            return

        for attr_name, attr_value in inspect.getmembers(Canvas):
            if not attr_name.startswith("__") and not attr_name.endswith("__") and not inspect.ismethod(attr_value):
                setattr(self.impl_canvas, attr_name, getattr(canvas, attr_name))

        self.impl_canvas.refresh()
        self.render_widget.repaint()

    def get_canvas(self) -> Canvas:
        """Gets current iplotlib canvas"""
        return self.impl_canvas

    def get_render_widget(self) -> QVTKRenderWindowInteractor:
        return self.render_widget

    def update(self):
        self.impl_canvas.refresh()
        super().update()