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
from vtkmodules.vtkCommonCore import vtkCommand

# iplot utilities
from iplotLogging import setupLogger as sl
logger = sl.get_logger(__name__, 'DEBUG')

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

        self._vtk_renderer = QVTKRenderWindowInteractor(self, **kwargs)
        self._vtk_parser = VTKParser()
        self.set_canvas(kwargs.get('canvas'))
        # Let the view render its scene into our render window
        self._vtk_parser.view.SetRenderWindow(self._vtk_renderer.GetRenderWindow())

        # laid out vertically.
        v_layout = QVBoxLayout(self)
        v_layout.addWidget(self._vtk_renderer)
        self.setLayout(v_layout)

        # callback to process mouse movements
        self.mouse_move_cb_tag = self._vtk_renderer.AddObserver(
            vtkCommand.MouseMoveEvent, self._vtk_mouse_move_handler)

        # callback to process mouse clicks
        self.mouse_press_cb_tag = self._vtk_renderer.AddObserver(
            vtkCommand.LeftButtonPressEvent, self._vtk_mouse_click_handler)

        # callback to process mouse clicks
        self.mouse_press_cb_tag = self._vtk_renderer.AddObserver(
            vtkCommand.RightButtonPressEvent, self._vtk_mouse_click_handler)

    def undo(self):
        """history: undo"""
        self._vtk_parser.undo()

    def redo(self):
        """history: redo"""
        self._vtk_parser.redo()

    def drop_history(self):
        return self._vtk_parser.drop_history()

    def resizeEvent(self, event: QResizeEvent):
        size = event.size()
        if not size.width():
            size.setWidth(5)
        
        if not size.height():
            size.setHeight(5)

        new_ev = QResizeEvent(size, event.oldSize())
        self._vtk_parser.resize(size.width(), size.height())
        logger.debug(f"Resize {new_ev.oldSize()} -> {new_ev.size()}")

        return super().resizeEvent(new_ev)

    def set_mouse_mode(self, mode: str):
        """Sets mouse mode of this canvas"""
        logger.debug(f"Mouse mode: {self._mmode} -> {mode}")
        self._mmode = mode
        self._vtk_parser.remove_crosshair_widget()
        self._vtk_parser.refresh_mouse_mode(self._mmode)
        self._vtk_parser.refresh_crosshair_widget()

    def _vtk_mouse_move_handler(self, obj, ev):
        if ev != "MouseMoveEvent":
            return
        mousePos = obj.GetEventPosition()
        self._debug_log_event(ev, f"{mousePos}")
        if self._mmode == Canvas.MOUSE_MODE_CROSSHAIR:
            self._vtk_parser.crosshair.onMove(mousePos)

    def _vtk_mouse_click_handler(self, obj, ev):
        if ev not in ["LeftButtonPressEvent", "RightButtonPressEvent"]:
            return
        mousePos = obj.GetEventPosition()
        self._debug_log_event(ev, f"{mousePos} " + "left" if ev == "LeftButtonPressEvent" else "right")
        if obj.GetRepeatCount() and self._mmode == Canvas.MOUSE_MODE_SELECT:
            index = self._vtk_parser.find_element_index(mousePos)
            self._vtk_parser.set_focus_plot(index)
            self._vtk_parser.process_ipl_canvas(self.get_canvas())
            self.render()

    def showEvent(self, event: QShowEvent):
        super().showEvent(event)
        self._debug_log_event(event, "")
        self.render()

    def set_canvas(self, canvas: Canvas):
        """Sets new iplotlib canvas and redraw"""

        super().set_canvas(canvas)  # does nothing

        self._vtk_parser.set_focus_plot(None)
        self._vtk_parser.process_ipl_canvas(canvas)
        if canvas:
            self.set_mouse_mode(canvas.mouse_mode or self._mmode)

    def get_canvas(self) -> Canvas:
        """Gets current iplotlib canvas"""
        return self._vtk_parser.canvas

    def get_vtk_renderer(self) -> QVTKRenderWindowInteractor:
        return self._vtk_renderer

    def render(self):
        self._vtk_renderer.Initialize()
        self._vtk_renderer.Render()
    
    def unfocus_plot(self):
        self._vtk_parser.focus_plot=None

    def _debug_log_event(self, event: vtkCommand, msg: str):
        logger.debug(f"{self.__class__.__name__}({hex(id(self))}) {msg} | {event}")
