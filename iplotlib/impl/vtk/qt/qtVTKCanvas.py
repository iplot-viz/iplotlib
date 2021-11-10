# Description: A concrete Qt GUI for a VTK canvas.
# Author: Jaswant Sai Panchumarti
# Changelog:
#   Sept 2021:  -Refactor qt classes [Jaswant Sai Panchumarti]
#               -Port to PySide2 [Jaswant Sai Panchumarti]


import inspect

from PySide2.QtWidgets import QVBoxLayout, QWidget
from PySide2.QtGui import QResizeEvent, QShowEvent

from iplotlib.impl import CanvasFactory, Canvas
from iplotlib.impl.vtk import VTKCanvas
from iplotlib.qt.gui.iplotQtCanvas import IplotQtCanvas

# Maintain consistent qt api across vtk and iplotlib
import vtkmodules.qt
vtkmodules.qt.PyQtImpl = 'PySide2'

# vtk requirements
from vtkmodules.qt.QVTKRenderWindowInteractor import QVTKRenderWindowInteractor, PyQtImpl
from vtkmodules.vtkCommonDataModel import vtkVector2i
from vtkmodules.vtkCommonCore import vtkCommand

# iplot utilities
from iplotLogging import setupLogger as sl
logger = sl.get_logger(__name__, "DEBUG")

try:
    assert(PyQtImpl == 'PySide2')
except AssertionError as e:
    logger.warning("Invalid python Qt binding: the sanity check failed")
    logger.exception(e)


class QtVTKCanvas(IplotQtCanvas):
    """A Qt container widget that emebeds a VTKCanvas.
        See set_canvas, get_canvas
    """

    def __init__(self, parent: QWidget = None, **kwargs):
        """Initialize a VTK Canvas embedded in QWidget

        Args:
            parent (QWidget, optional): Parent QWidget. Defaults to None.
        """
        super().__init__(parent, **kwargs)

        self.render_widget = QVTKRenderWindowInteractor(self, **kwargs)
        
        self.impl_canvas = CanvasFactory.new("vtk")
        self.set_canvas(kwargs.get('canvas'))
        # Let the view render its scene into our render window
        self.impl_canvas.view.SetRenderWindow(self.render_widget.GetRenderWindow())

        # laid out vertically.
        v_layout = QVBoxLayout(self)
        v_layout.addWidget(self.render_widget)
        self.setLayout(v_layout)

        # callback to process mouse movements
        self.mouse_move_cb_tag = self.render_widget.AddObserver(
            vtkCommand.MouseMoveEvent, self.mouse_move_callback)

        # callback to process mouse double clicks
        self.mouse_press_cb_tag = self.render_widget.AddObserver(
            vtkCommand.LeftButtonPressEvent, self.mouse_dclick_callback)

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
        
        logger.info(f"Mouse mode: {self.impl_canvas.mouse_mode} -> {mode}")
        self.impl_canvas.remove_crosshair_widget()
        self.impl_canvas.refresh_mouse_mode(mode)
        self.impl_canvas.refresh_crosshair_widget()

    def mouse_move_callback(self, obj, ev):
        mousePos = obj.GetEventPosition()
        self.impl_canvas.crosshair.onMove(mousePos)

    def mouse_dclick_callback(self, obj, ev):
        mousePos = obj.GetEventPosition()
        if obj.GetRepeatCount() and self.impl_canvas.mouse_mode == Canvas.MOUSE_MODE_SELECT:
            index = self.impl_canvas.find_element_index(mousePos)
            self.impl_canvas.set_focus_plot(index)
            self.impl_canvas.refresh()
            self.render()

    def showEvent(self, event: QShowEvent):
        super().showEvent(event)
        self.render()

    def set_canvas(self, canvas: Canvas):
        """Sets new iplotlib canvas and redraw"""

        super().set_canvas(canvas)  # does nothing

        if not isinstance(canvas, Canvas) and isinstance(self.impl_canvas, VTKCanvas):
            return

        self.impl_canvas.clear()
        self.impl_canvas.focus_plot=None
        self.impl_canvas.refresh()
        for attr_name, attr_value in inspect.getmembers(Canvas):
            if not attr_name.startswith("__") and not attr_name.endswith("__") and not inspect.ismethod(attr_value):
                setattr(self.impl_canvas, attr_name, getattr(canvas, attr_name))

        self.impl_canvas.refresh()

    def get_canvas(self) -> Canvas:
        """Gets current iplotlib canvas"""
        return self.impl_canvas

    def get_render_widget(self) -> QVTKRenderWindowInteractor:
        return self.render_widget

    def update(self):
        self.impl_canvas.refresh()
        super().update()
    
    def render(self):
        self.render_widget.Initialize()
        self.render_widget.Render()
    
    def unfocus_plot(self):
        self.impl_canvas.focus_plot=None
