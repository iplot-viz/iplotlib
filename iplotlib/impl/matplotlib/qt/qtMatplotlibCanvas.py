# Description: A concrete Qt GUI for a matplotlib canvas.
# Author: Piotr Mazur
# Changelog:
#   Sept 2021:  -Fix orphaned matploitlib figure. [Jaswant Sai Panchumarti]
#               -Fix draw_in_main_thread for when C++ object might have been deleted. [Jaswant Sai Panchumarti]
#               -Refactor qt classes [Jaswant Sai Panchumarti]
#               -Port to PySide2 [Jaswant Sai Panchumarti]


import pandas as pd

from PySide2.QtCore import QMargins, QMetaObject, Qt, Slot
from PySide2.QtGui import QKeyEvent
from PySide2.QtWidgets import QMessageBox, QSizePolicy, QVBoxLayout

from matplotlib.backend_bases import _Mode
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar

import iplotLogging.setupLogger as ls
from iplotlib.core.canvas import Canvas
from iplotlib.core.distance import DistanceCalculator
from iplotlib.impl.matplotlib.matplotlibCanvas import MatplotlibParser, NanosecondHelper
from iplotlib.qt.gui.iplotQtCanvas import IplotQtCanvas

logger = ls.get_logger(__name__)


class QtMatplotlibCanvas(IplotQtCanvas):
    """Qt widget that internally uses MatplotlibCanvas as backend"""

    def __init__(self, parent=None, tight_layout=True, **kwargs):
        super().__init__(parent, **kwargs)

        self.mpl_toolbar = None
        self.mouse_mode = None
        self._distCalculator = DistanceCalculator()
        self._draw_call_counter = 0

        self.mpl_parser = MatplotlibParser(tight_layout=tight_layout, mpl_flush_method=self.draw_in_main_thread, **kwargs)

        self.render_widget = FigureCanvas(self.mpl_parser.figure)
        self.render_widget.setParent(self)
        self.render_widget.setSizePolicy(QSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Expanding))
        self.render_widget.mpl_connect('draw_event', self.on_draw_finish)
        self.mpl_toolbar = NavigationToolbar(self.render_widget, self)
        self.mpl_toolbar.setVisible(False)

        self.setLayout(QVBoxLayout())
        self.layout().setAlignment(Qt.AlignTop)
        self.layout().setContentsMargins(QMargins())
        self.layout().addWidget(self.render_widget)

        self.mpl_parser.axes_update_timer = self.render_widget.new_timer(interval=self.mpl_parser.refresh_delay)
        self.mpl_parser.axes_update_timer.add_callback(self.mpl_parser.refresh_data)

        self.set_canvas(kwargs.get('canvas'))

    def draw_in_main_thread(self):
        import shiboken2
        if shiboken2.isValid(self):
            QMetaObject.invokeMethod(self, "flush_draw_queue")

    @Slot()
    def flush_draw_queue(self):
        if self.mpl_parser:
            self.mpl_parser.process_work_queue()

    def set_canvas(self, canvas: Canvas):
        """Sets new iplotlib canvas and redraw"""

        super().set_canvas(canvas)  # does nothing
        self.mpl_parser.deactivate_cursor()
        if canvas:
            self.mpl_parser.refresh(canvas)
            self.set_mouse_mode(self.mouse_mode or canvas.mouse_mode)
            QMetaObject.invokeMethod(self, "render")

    def get_canvas(self) -> Canvas:
        """Gets current iplotlib canvas"""
        return self.mpl_parser.canvas if self.mpl_parser else None

    @Slot()
    def render(self):
        self.render_widget.draw()

    def set_mouse_mode(self, mode: str):
        self.mouse_mode = mode

        def reset_tool():
            if self.mpl_toolbar:
                self.mpl_toolbar.mode = _Mode.NONE
                self.mpl_parser.deactivate_cursor()

        reset_tool()

        if self.mpl_toolbar and self.mouse_mode is not None:
            if mode == Canvas.MOUSE_MODE_CROSSHAIR:
                self.mpl_toolbar.canvas.widgetlock.release(self.mpl_toolbar)
                self.mpl_parser.activate_cursor()
                self.mpl_parser.figure.canvas.mpl_connect(
                    'button_press_event', self.click)

            elif mode == Canvas.MOUSE_MODE_PAN:
                self.mpl_parser.deactivate_cursor()
                self.mpl_toolbar.pan()
                self.mpl_parser.figure.canvas.mpl_connect(
                    'button_press_event', self.click)
            elif mode == Canvas.MOUSE_MODE_ZOOM:
                self.mpl_parser.deactivate_cursor()
                self.mpl_toolbar.zoom()
                self.mpl_parser.figure.canvas.mpl_connect(
                    'button_press_event', self.click)
            elif mode == Canvas.MOUSE_MODE_SELECT:
                self.mpl_parser.figure.canvas.mpl_connect(
                    'button_press_event', self.click)
                pass
            elif mode == Canvas.MOUSE_MODE_DIST:
                self.mpl_parser.figure.canvas.mpl_connect(
                    'button_press_event', self.click)
                pass

    def click(self, event):
        """Additional callback to allow for focusing on one plot and returning home after double click"""
        if event.dblclick:
            if self.mouse_mode == Canvas.MOUSE_MODE_SELECT and event.button == 1 and event.inaxes is not None:
                logger.debug(
                    f"Plot clicked: {event.inaxes}. Plot: {event.inaxes._ipl_plot()} stack_key: {event.inaxes._ipl_plot_stack_key}")
                self.mpl_parser.set_focus_plot(event.inaxes)
            else:
                self.mpl_parser.set_focus_plot(None)

            self.mpl_parser.refresh(self.mpl_parser.canvas)
            self.mpl_parser.figure.canvas.draw()
        else:
            if self.mouse_mode == Canvas.MOUSE_MODE_DIST and event.button == 1 and event.inaxes is not None:
                if self._distCalculator.plot1 is not None:
                    x_axis = event.inaxes.get_xaxis()
                    has_offset = hasattr(x_axis, '_offset')
                    x = NanosecondHelper.mpl_transform_value(event.inaxes.get_xaxis(), event.xdata)
                    self._distCalculator.set_dst(x, event.ydata, event.inaxes._ipl_plot(), event.inaxes._ipl_plot_stack_key)
                    box = QMessageBox(self)
                    box.setWindowTitle('Distance')
                    dx, dy, dz = self._distCalculator.dist()
                    if has_offset:
                        dx = pd.Timestamp(x, unit='ns') - pd.Timestamp(self._distCalculator.p1[0], unit='ns')
                        dx = pd.Timedelta(dx).isoformat()
                    if any([dx, dy, dz]):
                        box.setText(f"dx = {dx}\ndy = {dy}\ndz = {dz}")
                    else:
                        box.setText("Invalid selection")
                    box.exec_()
                    self._distCalculator.reset()
                else:
                    x = NanosecondHelper.mpl_transform_value(event.inaxes.get_xaxis(), event.xdata)
                    self._distCalculator.set_src(x, event.ydata, event.inaxes._ipl_plot(), event.inaxes._ipl_plot_stack_key)

    def keyPressEvent(self, event: QKeyEvent):
        if event.text() == 'n':
            self.mpl_toolbar.forward()
        elif event.text() == 'p':
            self.mpl_toolbar.back()

    def back(self):
        if self.mpl_toolbar:
            self.mpl_toolbar.back()

    def forward(self):
        if self.mpl_toolbar:
            self.mpl_toolbar.forward()

    def unfocus_plot(self):
        self.mpl_parser.set_focus_plot(None)

    def on_draw_finish(self, e):
        self._draw_call_counter += 1
        logger.info(f"{self.__class__.__name__}({hex(id(self))}) Draw Call {self._draw_call_counter} | {e}")