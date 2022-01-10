# Description: A concrete Qt GUI for a matplotlib canvas.
# Author: Piotr Mazur
# Changelog:
#   Sept 2021:  -Fix orphaned matploitlib figure. [Jaswant Sai Panchumarti]
#               -Fix draw_in_main_thread for when C++ object might have been deleted. [Jaswant Sai Panchumarti]
#               -Refactor qt classes [Jaswant Sai Panchumarti]
#               -Port to PySide2 [Jaswant Sai Panchumarti]


from PySide2.QtCore import QMargins, QMetaObject, Qt, Slot
from PySide2.QtGui import QKeyEvent
from PySide2.QtWidgets import QMessageBox, QSizePolicy, QVBoxLayout

from matplotlib.backend_bases import _Mode, DrawEvent, Event, MouseButton, MouseEvent
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar

import iplotLogging.setupLogger as ls
from iplotlib.core.canvas import Canvas
from iplotlib.core.distance import DistanceCalculator
from iplotlib.impl.matplotlib.matplotlibCanvas import MatplotlibParser, NanosecondHelper
from iplotlib.qt.gui.iplotQtCanvas import IplotQtCanvas

logger = ls.get_logger(__name__)


class QtMatplotlibCanvas(IplotQtCanvas):
    """Qt widget that internally uses a matplotlib canvas backend"""

    def __init__(self, parent=None, tight_layout=True, **kwargs):
        super().__init__(parent, **kwargs)

        self._mmode = None
        self._dist_calculator = DistanceCalculator()
        self._draw_call_counter = 0

        self._mpl_size_pol = QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._mpl_parser = MatplotlibParser(tight_layout=tight_layout, mpl_flush_method=self.draw_in_main_thread, **kwargs)
        self._mpl_renderer = FigureCanvas(self._mpl_parser.figure)
        self._mpl_renderer.setParent(self)
        self._mpl_renderer.setSizePolicy(self._mpl_size_pol)
        self._mpl_toolbar = NavigationToolbar(self._mpl_renderer, self)
        self._mpl_toolbar.setVisible(False)

        self._vlayout = QVBoxLayout(self)
        self._vlayout.setAlignment(Qt.AlignTop)
        self._vlayout.setContentsMargins(QMargins())
        self._vlayout.addWidget(self._mpl_renderer)

        # GUI event handlers 
        self._mpl_renderer.mpl_connect('draw_event', self._mpl_draw_finish)
        self._mpl_renderer.mpl_connect('button_press_event', self._mpl_mouse_press_handler)
        self._mpl_renderer.mpl_connect('button_release_event', self._mpl_mouse_release_handler)

        self.setLayout(self._vlayout)

        self._mpl_parser.axes_update_timer = self._mpl_renderer.new_timer(interval=self._mpl_parser.refresh_delay)
        self._mpl_parser.axes_update_timer.add_callback(self._mpl_parser.refresh_data)

        self.set_canvas(kwargs.get('canvas'))

    # Implement basic superclass functionality
    def set_canvas(self, canvas: Canvas):
        """Sets new iplotlib canvas and redraw"""

        prev_canvas = self._mpl_parser.canvas
        if prev_canvas != canvas and prev_canvas is not None and canvas is not None:
            self.unfocus_plot()

        super().set_canvas(canvas)  # does nothing for now

        self._mpl_parser.deactivate_cursor()
        
        if not canvas:
            return

        self._mpl_parser.process_ipl_canvas(canvas)
        self.set_mouse_mode(self._mmode or canvas.mouse_mode)
        self.render()

    def get_canvas(self) -> Canvas:
        """Gets current iplotlib canvas"""
        return self._mpl_parser.canvas if self._mpl_parser else None

    def set_mouse_mode(self, mode: str):
        logger.debug(f"MMode change {self._mmode} -> {mode}")
        super().set_mouse_mode(mode)

        if self._mpl_toolbar:
            self._mpl_toolbar.mode = _Mode.NONE
            self._mpl_parser.deactivate_cursor()
        
        if self._mmode is None:
            return

        if not self._mpl_toolbar:
            return

        if mode == Canvas.MOUSE_MODE_CROSSHAIR:
            self._mpl_toolbar.canvas.widgetlock.release(self._mpl_toolbar)
            self._mpl_parser.activate_cursor()
        elif mode == Canvas.MOUSE_MODE_PAN:
            self._mpl_parser.deactivate_cursor()
            self._mpl_toolbar.pan()
        elif mode == Canvas.MOUSE_MODE_ZOOM:
            self._mpl_parser.deactivate_cursor()
            self._mpl_toolbar.zoom()

    def undo(self):
        if self._mpl_toolbar:
            self._mpl_toolbar.back()
        self._mpl_parser.undo()

    def redo(self):
        if self._mpl_toolbar:
            self._mpl_toolbar.forward()
        self._mpl_parser.redo()

    def unfocus_plot(self):
        self._mpl_parser.set_focus_plot(None)

    def drop_history(self):
        return self._mpl_parser.drop_history()

    def draw_in_main_thread(self):
        import shiboken2
        if shiboken2.isValid(self):
            QMetaObject.invokeMethod(self, "flush_draw_queue")

    @Slot()
    def flush_draw_queue(self):
        if self._mpl_parser:
            self._mpl_parser.process_work_queue()

    @Slot()
    def render(self):
        self._mpl_renderer.draw()

    # custom event handlers
    def _mpl_draw_finish(self, event: DrawEvent):
        self._draw_call_counter += 1
        self._debug_log_event(event, f"Draw call {self._draw_call_counter}")

    def _mpl_mouse_press_handler(self, event: MouseEvent):
        """Additional callback to allow for focusing on one plot and returning home after double click"""
        self._debug_log_event(event, "Mouse pressed")
        if event.dblclick:
            if self._mmode == Canvas.MOUSE_MODE_SELECT and event.button == MouseButton.LEFT and event.inaxes is not None:
                logger.debug(
                    f"Plot clicked: {event.inaxes}. Plot: {event.inaxes._ipl_plot()} stack_key: {event.inaxes._ipl_plot_stack_key}")
                self._mpl_parser.set_focus_plot(event.inaxes)
                self.refresh(False)
            elif self._mmode == Canvas.MOUSE_MODE_ZOOM:
                pass
            else:
                self._mpl_parser.set_focus_plot(None)
                self.refresh(False)
            QMetaObject.invokeMethod(self, "render")
        else:
            if event.inaxes is None:
                return
            if self._mmode in [Canvas.MOUSE_MODE_ZOOM, Canvas.MOUSE_MODE_PAN]:
                print('pressed')
                return
            if event.button != MouseButton.LEFT:
                return
            if self._mmode == Canvas.MOUSE_MODE_DIST:
                if self._dist_calculator.plot1 is not None:
                    x_axis = event.inaxes.get_xaxis()
                    has_offset = hasattr(x_axis, '_offset')
                    x = NanosecondHelper.mpl_transform_value(event.inaxes.get_xaxis(), event.xdata)
                    self._dist_calculator.set_dst(x, event.ydata, event.inaxes._ipl_plot(), event.inaxes._ipl_plot_stack_key)
                    self._dist_calculator.set_dx_is_datetime(has_offset)
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
                    x = NanosecondHelper.mpl_transform_value(event.inaxes.get_xaxis(), event.xdata)
                    self._dist_calculator.set_src(x, event.ydata, event.inaxes._ipl_plot(), event.inaxes._ipl_plot_stack_key)

    def _mpl_mouse_release_handler(self, event: MouseEvent):
        self._debug_log_event(event, "Mouse released")
        if event.dblclick:
            pass
        else:
            if event.inaxes is None:
                return
            if self._mmode in [Canvas.MOUSE_MODE_ZOOM, Canvas.MOUSE_MODE_PAN]:
                print('released')
    
    def keyPressEvent(self, event: QKeyEvent):
        if event.text() == 'n':
            self.forward()
        elif event.text() == 'p':
            self.back()

    def _debug_log_event(self, event: Event, msg: str):
        logger.debug(f"{self.__class__.__name__}({hex(id(self))}) {msg} | {event}")
