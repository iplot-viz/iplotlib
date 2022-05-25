# Description: A concrete Qt GUI for a VTK canvas.
# Author: Jaswant Sai Panchumarti
# Changelog:
#   Sept 2021:  -Refactor qt classes [Jaswant Sai Panchumarti]
#               -Port to PySide2 [Jaswant Sai Panchumarti]


from PySide6.QtWidgets import QMessageBox, QSizePolicy, QVBoxLayout, QWidget
from PySide6.QtGui import QResizeEvent, QShowEvent
from PySide6.QtCore import Qt

from iplotlib.core.canvas import Canvas
from iplotlib.core.distance import DistanceCalculator
from iplotlib.impl.vtk import VTKParser
from iplotlib.impl.vtk.tools.queryMatrix import find_root_plot
from iplotlib.qt.gui.iplotQtCanvas import IplotQtCanvas

# Maintain consistent qt api across vtk and iplotlib
import vtkmodules.qt
vtkmodules.qt.PyQtImpl = 'PySide6'

# vtk requirements
from vtkmodules.vtkCommonDataModel import vtkVector2f
from vtkmodules.qt.QVTKRenderWindowInteractor import QVTKRenderWindowInteractor, PyQtImpl
from vtkmodules.vtkCommonCore import vtkCommand
from vtkmodules.vtkChartsCore import vtkChart, vtkAxis

# iplot utilities
from iplotLogging import setupLogger as sl
logger = sl.get_logger(__name__)

try:
    assert(PyQtImpl == 'PySide6')
except AssertionError as e:
    logger.warning("Invalid python Qt binding: the sanity check failed")
    logger.exception(e)

class IplotQVTKRwi(QVTKRenderWindowInteractor):
    """This subclass is a small hack to disable the timer that constantly makes a Render call every 10 ms.
       Hack: The QTimer created in parent class probably runs in the same thread and causes an unexplained
       lag when UDA data access is enabled. Override the TimerEvent and do nothing.


    :param QVTKRenderWindowInteractor: [description]
    :type QVTKRenderWindowInteractor: [type]
    """
    def __init__(self, parent=None, **kw):
        super().__init__(parent=parent, **kw)
    
    def TimerEvent(self):
        return

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

        self._dist_calculator = DistanceCalculator()
        self._draw_call_counter = 0
        
        self._vtk_size_pol = QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._vtk_renderer = IplotQVTKRwi(self, **kwargs)
        self._vtk_renderer._Timer.stop()
        self._parser = VTKParser(impl_flush_method=self.draw_in_main_thread)
        self._vtk_renderer.setSizePolicy(self._vtk_size_pol)
        self._vlayout = QVBoxLayout(self)
        self._vlayout.addWidget(self._vtk_renderer)

        # Let the view render its scene into our render window
        rwin = self._vtk_renderer.GetRenderWindow()
        self._parser.view.SetRenderWindow(rwin)

        # GUI event handlers 
        self.draw_end_cb_tag = rwin.AddObserver(vtkCommand.EndEvent, self._vtk_draw_finish)
        self.mouse_move_cb_tag = self._vtk_renderer.AddObserver(
            vtkCommand.MouseMoveEvent, self._vtk_mouse_move_handler)
        self.mouse_press_cb_tag = self._vtk_renderer.AddObserver(
            vtkCommand.LeftButtonPressEvent, self._vtk_mouse_press_handler)
        self.mouse_release_cb_tag = self._vtk_renderer.AddObserver(
            vtkCommand.LeftButtonReleaseEvent, self._vtk_mouse_release_handler)

        self.setLayout(self._vlayout)
        self.set_canvas(kwargs.get('canvas'))

    def set_canvas(self, canvas: Canvas):
        """Sets new iplotlib canvas and redraw"""
        prev_canvas = self._parser.canvas
        if prev_canvas != canvas and prev_canvas is not None and canvas is not None:
            self.unfocus_plot()

        self._parser.remove_crosshair_widget()
        self._parser.process_ipl_canvas(canvas)
        
        if canvas:
            self.set_mouse_mode(self._mmode or canvas.mouse_mode)

        self.render()
        super().set_canvas(canvas)

    def get_canvas(self) -> Canvas:
        """Gets current iplotlib canvas"""
        return self._parser.canvas

    def set_mouse_mode(self, mode: str):
        """Sets mouse mode of this canvas"""
        if mode == self._mmode:
            return
        super().set_mouse_mode(mode)
        self._parser.remove_crosshair_widget()
        self._parser.refresh_mouse_mode(self._mmode)
        self._parser.refresh_crosshair_widget()

    def undo(self):
        self._parser.undo()
        self.render()

    def redo(self):
        self._parser.redo()
        self.render()

    def unfocus_plot(self):
        self._parser.set_focus_plot(None)

    def drop_history(self):
        return self._parser.drop_history()

    def render(self):
        self._vtk_renderer.Initialize()
        self._vtk_renderer.Render()
        self._parser.unstale_cache_items()

    def resizeEvent(self, event: QResizeEvent):
        size = event.size()
        if not size.width():
            size.setWidth(5)
        
        if not size.height():
            size.setHeight(5)

        new_ev = QResizeEvent(size, event.oldSize())
        self._parser.resize(size.width(), size.height())
        self._debug_log_event(new_ev, "")
        return super().resizeEvent(new_ev)

    def _vtk_draw_finish(self, obj, ev):
        self._draw_call_counter += 1
        # self._debug_log_event(ev, f"Draw call {self._draw_call_counter}")

    def _vtk_mouse_move_handler(self, obj, ev):
        if ev != "MouseMoveEvent":
            return
        mousePos = obj.GetEventPosition()
        # self._debug_log_event(ev, f"{mousePos}") # silenced for easy debugging
        if self._mmode == Canvas.MOUSE_MODE_CROSSHAIR:
            self._parser.crosshair.onMove(mousePos)
        self._vtk_renderer.Render()

    def _vtk_mouse_press_handler(self, obj, ev):
        if ev not in ["LeftButtonPressEvent"]:
            return
        mousePos = obj.GetEventPosition()
        self._debug_log_event(ev, f"{mousePos}")
        chart = self._parser.find_chart(mousePos)
        if obj.GetRepeatCount():
            if self._mmode == Canvas.MOUSE_MODE_SELECT:
                self._parser.set_focus_plot(chart)
                self._refresh_original_ranges = False
                self.refresh()
                self._refresh_original_ranges = True
            elif self._mmode in [Canvas.MOUSE_MODE_PAN, Canvas.MOUSE_MODE_ZOOM]:
                if not isinstance(chart, vtkChart):
                    return
                ci = self._parser._impl_plot_cache_table.get_cache_item(chart)
                if not hasattr(ci, 'plot'):
                    return
                plot = ci.plot()
                if not plot:
                    return

                # Stage a command to obtain original view limits
                self.stage_view_lim_cmd()
                
                # Reset plot to original view limits
                original_limits = self._parser.get_plot_limits(plot, which='original')
                self._parser.set_plot_limits(original_limits)

                # Commit it.
                while len(self._staging_cmds):
                    self.commit_view_lim_cmd()

                # Push it.
                while len(self._commitd_cmds):
                    self.push_view_lim_cmd()

                self.render()
            else:
                self._parser.set_focus_plot(None)
                self._refresh_original_ranges = False
                self.refresh()
                self._refresh_original_ranges = True
        else:
            if chart is None:
                return
            if self._mmode in [Canvas.MOUSE_MODE_ZOOM, Canvas.MOUSE_MODE_PAN]:
                # Stage a command to obtain original view limits
                self.stage_view_lim_cmd()
                return
            ci = self._parser._impl_plot_cache_table.get_cache_item(chart)
            if not hasattr(ci, 'plot'):
                return
            plot = ci.plot()
            if not plot:
                self._dist_calculator.reset()
                return

            screenToScene = self._parser.scene.GetTransform()
            probe = [0, 0]
            screenToScene.TransformPoints(mousePos, probe, 1)

            plotRoot = find_root_plot(self._parser.matrix, probe)
            if plotRoot is None:
                return

            pos = plotRoot.MapFromScene(vtkVector2f(probe))
            if self._mmode == Canvas.MOUSE_MODE_DIST:
                try:
                    is_date = plot.axes[0].is_date
                except (AttributeError, IndexError):
                    is_date = False
                impl_axis = self._parser.get_impl_axis(chart, 0) # type: vtkAxis
                shift, scale = impl_axis.GetShift(), impl_axis.GetScalingFactor()
                if is_date:
                    x = (int(pos[0] / scale) - int(shift))
                elif not is_date:
                    x = (pos[0] / scale) - shift
                x = self._parser.transform_value(chart, 0, x)
                if self._dist_calculator.plot1 is not None:
                    self._dist_calculator.set_dst(x, pos[1], plot, ci.stack_key)
                    self._dist_calculator.set_dx_is_datetime(is_date)
                    box = QMessageBox(self)
                    box.setWindowTitle('Distance')
                    dx, dy, dz = self._dist_calculator.dist()
                    if any([dx, dy, dz]):
                        box.setText(f"dx = {dx}\ndy = {dy}\ndz = {dz}")
                    else:
                        box.setText("Invalid selection")
                    box.exec_()
                    self._dist_calculator.reset()
                else:
                    self._dist_calculator.set_src(x, pos[1], plot, ci.stack_key)


    def _vtk_mouse_release_handler(self, obj, ev):
        if ev not in ["LeftButtonReleaseEvent"]:
            return
        mousePos = obj.GetEventPosition()
        self._debug_log_event(ev, f"{mousePos}")
        if obj.GetRepeatCount():
            pass
        else:
            if self._mmode in [Canvas.MOUSE_MODE_ZOOM, Canvas.MOUSE_MODE_PAN]:
                # commit commands from staging.
                while len(self._staging_cmds):
                    self.commit_view_lim_cmd()
                # push uncommited changes onto the command stack.
                while len(self._commitd_cmds):
                    self.push_view_lim_cmd()
            self.render()

    def showEvent(self, event: QShowEvent):
        super().showEvent(event)
        self._debug_log_event(event, "")
        self.render()

    def get_vtk_renderer(self) -> QVTKRenderWindowInteractor:
        return self._vtk_renderer
    
    def _debug_log_event(self, event: vtkCommand, msg: str):
        logger.debug(f"{self.__class__.__name__}({hex(id(self))}) {msg} | {event}")
