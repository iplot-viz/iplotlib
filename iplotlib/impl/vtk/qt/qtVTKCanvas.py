# Description: A concrete Qt GUI for a VTK canvas.
# Author: Jaswant Sai Panchumarti
# Changelog:
#   Sept 2021:  -Refactor qt classes [Jaswant Sai Panchumarti]
#               -Port to PySide2 [Jaswant Sai Panchumarti]


from PySide2.QtWidgets import QVBoxLayout, QWidget
from PySide2.QtGui import QResizeEvent, QShowEvent

from iplotlib.core.canvas import Canvas
from iplotlib.impl.vtk import VTKParser
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
        
        self.vtk_parser = VTKParser()
        self.set_canvas(kwargs.get('canvas'))
        # Let the view render its scene into our render window
        self.vtk_parser.view.SetRenderWindow(self.render_widget.GetRenderWindow())

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
        self.vtk_parser.resize(size.width(), size.height())
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
        
        logger.info(f"Mouse mode: {self.vtk_parser.canvas.mouse_mode} -> {mode}")
        self.vtk_parser.remove_crosshair_widget()
        self.vtk_parser.refresh_mouse_mode(mode)
        self.vtk_parser.refresh_crosshair_widget()

    def mouse_move_callback(self, obj, ev):
        mousePos = obj.GetEventPosition()
        self.vtk_parser.crosshair.onMove(mousePos)

    def mouse_dclick_callback(self, obj, ev):
        mousePos = obj.GetEventPosition()
        if obj.GetRepeatCount() and self.vtk_parser.mouse_mode == Canvas.MOUSE_MODE_SELECT:
            index = self.vtk_parser.find_element_index(mousePos)
            self.vtk_parser.set_focus_plot(index)
            self.vtk_parser.refresh()
            self.render()

    def showEvent(self, event: QShowEvent):
        super().showEvent(event)
        self.render()

    def set_canvas(self, canvas: Canvas):
        """Sets new iplotlib canvas and redraw"""

        super().set_canvas(canvas)  # does nothing

        self.vtk_parser.focus_plot=None
        self.vtk_parser.refresh(canvas)

    def get_canvas(self) -> Canvas:
        """Gets current iplotlib canvas"""
        return self.vtk_parser.canvas

    def get_render_widget(self) -> QVTKRenderWindowInteractor:
        return self.render_widget

    def update(self):
        self.vtk_parser.refresh(self.vtk_parser.canvas)
        super().update()
    
    def render(self):
        self.render_widget.Initialize()
        self.render_widget.Render()
    
    def unfocus_plot(self):
        self.vtk_parser.focus_plot=None
