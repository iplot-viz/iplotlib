# Description: A concrete Qt GUI for a matplotlib canvas.
# Author: Piotr Mazur
# Changelog:
#   Sept 2021:  -Fix orphaned matploitlib figure. [Jaswant Sai Panchumarti]
#               -Fix draw_in_main_thread for when C++ object might have been deleted. [Jaswant Sai Panchumarti]
#               -Refactor qt classes [Jaswant Sai Panchumarti]
#               -Port to PySide2 [Jaswant Sai Panchumarti]
#   Jan 2022:   -Introduce custom HistoryManagement for zooming and panning with git style revision control [Jaswant Sai Panchumarti]
#               -Introduce distance calculator. [Jaswant Sai Panchumarti]
#               -Refactor and let superclass methods refresh, reset use set_canvas, get_canvas [Jaswant Sai Panchumarti]

import typing

from PySide2.QtCore import QMargins, QMetaObject, Qt, Slot
from PySide2.QtGui import QKeyEvent
from PySide2.QtWidgets import QMessageBox, QSizePolicy, QVBoxLayout

from matplotlib.backend_bases import _Mode, DrawEvent, Event, MouseButton, MouseEvent
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar

from iplotlib.core.commands.axes_range import XYLimits
from iplotlib.core.canvas import Canvas
from iplotlib.core.distance import DistanceCalculator
from iplotlib.impl.matplotlib.matplotlibCanvas import MatplotlibParser, MplAxesRangeCmd, NanosecondHelper
from iplotlib.qt.gui.iplotQtCanvas import IplotQtCanvas
import iplotLogging.setupLogger as ls

logger = ls.get_logger(__name__)


class QtMatplotlibCanvas(IplotQtCanvas):
    """Qt widget that internally uses a matplotlib canvas backend"""

    def __init__(self, parent=None, tight_layout=True, **kwargs):
        super().__init__(parent, **kwargs)

        self._mmode = None
        self._dist_calculator = DistanceCalculator()
        self._draw_call_counter = 0
        self._staging_commands = [] # type: typing.List[MplAxesRangeCmd]
        self._commited_commands = [] # type: typing.List[MplAxesRangeCmd]

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
        self._mpl_parser.undo()
        self._mpl_parser.refresh_data()
        self.render()

    def redo(self):
        self._mpl_parser.redo()
        self._mpl_parser.refresh_data()
        self.render()

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
        self._mpl_parser.unstale_mpl_axes()

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
                self.refresh()
            elif self._mmode == Canvas.MOUSE_MODE_ZOOM:
                pass
            else:
                self._mpl_parser.set_focus_plot(None)
                self.refresh()
            QMetaObject.invokeMethod(self, "render")
        else:
            if event.inaxes is None:
                return
            if self._mmode in [Canvas.MOUSE_MODE_ZOOM, Canvas.MOUSE_MODE_PAN]:
                # Stage a command to obtain original view limits for event.inaxes
                old_lim = XYLimits(
                    *NanosecondHelper.mpl_get_lim(event.inaxes, 0),
                    *NanosecondHelper.mpl_get_lim(event.inaxes, 1)
                )
                new_lim = None
                name = self._mmode[3:]
                cmd = MplAxesRangeCmd(name.capitalize(), old_lim, new_lim, event.inaxes._ipl_plot(), self._mpl_parser)
                self._staging_commands.append(cmd)
                logger.debug(f"Staged {cmd}")
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
                # commit commands from staging.
                while len(self._staging_commands):
                    cmd = self._staging_commands.pop()
                    cmd.new_lim = XYLimits(
                        *NanosecondHelper.mpl_get_lim(cmd.mpl_axes, 0),
                        *NanosecondHelper.mpl_get_lim(cmd.mpl_axes, 1)
                    )
                    if any([val1 != val2 for val1, val2 in zip(cmd.old_lim, cmd.new_lim)]):
                        self._commited_commands.append(cmd)
                        logger.debug(f"Commited {cmd}")
                    else:
                        logger.debug(f"Rejected {cmd}")
                # push uncommited changes onto the command stack.
                while len(self._commited_commands):
                    cmd = self._commited_commands.pop()
                    self._mpl_parser._hm.done(cmd)
                    logger.debug(f"Pushed {cmd}")
                    self._mpl_parser.refresh_data()
    
    def keyPressEvent(self, event: QKeyEvent):
        if event.text() == 'n':
            self.redo()
        elif event.text() == 'p':
            self.undo()

    def _debug_log_event(self, event: Event, msg: str):
        logger.debug(f"{self.__class__.__name__}({hex(id(self))}) {msg} | {event}")
