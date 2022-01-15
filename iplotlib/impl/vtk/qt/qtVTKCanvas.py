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
        self._draw_call_counter = 0
        self._parser = VTKParser()
        self.set_canvas(kwargs.get('canvas'))
        # Let the view render its scene into our render window
        self._parser.view.SetRenderWindow(self._vtk_renderer.GetRenderWindow())

        # laid out vertically.
        v_layout = QVBoxLayout(self)
        v_layout.addWidget(self._vtk_renderer)
        self.setLayout(v_layout)

        # callback to process mouse movements
        self.mouse_move_cb_tag = self._vtk_renderer.AddObserver(
            vtkCommand.MouseMoveEvent, self._vtk_mouse_move_handler)

        # callback to process mouse clicks
        self.mouse_press_cb_tag = self._vtk_renderer.AddObserver(
            vtkCommand.LeftButtonPressEvent, self._vtk_mouse_press_handler)

        # callback to process mouse clicks
        self.mouse_release_cb_tag = self._vtk_renderer.AddObserver(
            vtkCommand.LeftButtonReleaseEvent, self._vtk_mouse_release_handler)
        
        # self._vtk_renderer.AddObserver(vtkCommand.RenderEvent, self._vtk_draw_finish)

    def stage_view_lim_cmd(self):
        return super().stage_view_lim_cmd()
    
    def commit_view_lim_cmd(self):
        return super().commit_view_lim_cmd()
    
    def stage_view_lim_cmd(self):
        return super().stage_view_lim_cmd()

    def resizeEvent(self, event: QResizeEvent):
        size = event.size()
        if not size.width():
            size.setWidth(5)
        
        if not size.height():
            size.setHeight(5)

        new_ev = QResizeEvent(size, event.oldSize())
        self._parser.resize(size.width(), size.height())
        logger.debug(f"Resize {new_ev.oldSize()} -> {new_ev.size()}")

        return super().resizeEvent(new_ev)

    def set_mouse_mode(self, mode: str):
        """Sets mouse mode of this canvas"""
        logger.debug(f"Mouse mode: {self._mmode} -> {mode}")
        self._mmode = mode
        self._parser.remove_crosshair_widget()
        self._parser.refresh_mouse_mode(self._mmode)
        self._parser.refresh_crosshair_widget()

    def _vtk_draw_finish(self, obj, ev):
        self._draw_call_counter += 1
        self._debug_log_event(ev, f"Draw call {self._draw_call_counter}")

    def _vtk_mouse_move_handler(self, obj, ev):
        if ev != "MouseMoveEvent":
            return
        mousePos = obj.GetEventPosition()
        # self._debug_log_event(ev, f"{mousePos}")
        if self._mmode == Canvas.MOUSE_MODE_CROSSHAIR:
            self._parser.crosshair.onMove(mousePos)

    def _vtk_mouse_press_handler(self, obj, ev):
        if ev not in ["LeftButtonPressEvent"]:
            return
        mousePos = obj.GetEventPosition()
        self._debug_log_event(ev, f"{mousePos}")
        if obj.GetRepeatCount() and self._mmode == Canvas.MOUSE_MODE_SELECT:
            index = self._parser.find_element_index(mousePos)
            self._parser.set_focus_plot(index)
            self._parser.process_ipl_canvas(self.get_canvas())
            self.render()
        elif self._mmode in [Canvas.MOUSE_MODE_PAN, Canvas.MOUSE_MODE_ZOOM]:
            print("press")

    def _vtk_mouse_release_handler(self, obj, ev):
        if ev not in ["LeftButtonReleaseEvent"]:
            return
        mousePos = obj.GetEventPosition()
        self._debug_log_event(ev, f"{mousePos}")
        if self._mmode in [Canvas.MOUSE_MODE_PAN, Canvas.MOUSE_MODE_ZOOM]:
            print("release")

    def showEvent(self, event: QShowEvent):
        super().showEvent(event)
        self._debug_log_event(event, "")
        self.render()

    def set_canvas(self, canvas: Canvas):
        """Sets new iplotlib canvas and redraw"""

        self._parser.process_ipl_canvas(canvas)
        if canvas:
            self.set_mouse_mode(canvas.mouse_mode or self._mmode)
        super().set_canvas(canvas)

    def get_canvas(self) -> Canvas:
        """Gets current iplotlib canvas"""
        return self._parser.canvas

    def get_vtk_renderer(self) -> QVTKRenderWindowInteractor:
        return self._vtk_renderer

    def render(self):
        self._vtk_renderer.Initialize()
        self._vtk_renderer.Render()
        self._vtk_draw_finish(self._vtk_renderer, 'ManualRenderEvent')
    
    def unfocus_plot(self):
        self._parser.focus_plot=None

    def _debug_log_event(self, event: vtkCommand, msg: str):
        logger.debug(f"{self.__class__.__name__}({hex(id(self))}) {msg} | {event}")
