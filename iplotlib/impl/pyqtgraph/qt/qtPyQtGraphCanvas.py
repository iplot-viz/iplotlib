from collections import defaultdict

import numpy as np
from PySide6.QtCore import QMargins, Qt, Signal
from PySide6.QtWidgets import QVBoxLayout, QGraphicsSceneMouseEvent

from iplotlib.core import Canvas, BackendParserBase, Plot, PlotContour
import pyqtgraph as pg

from pyqtgraph.Qt.QtGui import QMouseEvent

from iplotlib.impl.pyqtgraph.pyQtGraphCanvas import PyQtGraphParser
from iplotlib.qt.gui.IplotQtStatistics import IplotQtStatistics
from iplotlib.qt.gui.iplotQtCanvas import IplotQtCanvas
from iplotlib.qt.gui.iplotQtMarker import IplotQtMarker
import iplotLogging.setupLogger as Sl

logger = Sl.get_logger(__name__)


class QtPyQtGraphCanvas(IplotQtCanvas):
    """Qt widget that internally uses a matplotlib canvas backend"""

    dropSignal = Signal(object)

    def __init__(self, parent=None, tight_layout=True, **kwargs):
        super().__init__(parent, **kwargs)

        self._draw_call_counter = 0
        self._marker_window = IplotQtMarker()
        self._marker_window.dropMarker.connect(self.draw_marker_label)
        self._marker_window.deleteMarker.connect(self.delete_marker_label)

        self.info_shared_x_dialog = False
        self._parser = PyQtGraphParser()

        self._vlayout = QVBoxLayout(self)
        self._vlayout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._vlayout.setContentsMargins(QMargins())
        # self._vlayout.addWidget(self._parser.figure)
        self._vlayout.addLayout(self._parser.main_layout)

        self.setLayout(self._vlayout)

        # Drag & Drop
        self.setAcceptDrops(True)

    def set_canvas(self, canvas):
        super().set_canvas(canvas)

        prev_canvas = self._parser.canvas

        if prev_canvas != canvas and prev_canvas is not None and canvas is not None:
            self.unfocus_plot()

        self._parser.deactivate_cursor()
        self._parser.process_ipl_canvas(canvas)

        if canvas:
            self.set_mouse_mode(self._mmode or canvas.mouse_mode)

        self.canvas = canvas

        # Connect events
        for plot_item in self._parser._layout.values():
            vb = plot_item.getViewBox()
            vb.pressed.connect(self._impl_mouse_press_handler)
            vb.released.connect(self._impl_mouse_release_handler)

        # self._parser.figure.clear()
        # for i, col in enumerate(self.canvas.plots):
        #     for j, plot in enumerate(col):
        #         if not plot:
        #             continue
        #         p = pg.PlotItem()
        #
        #         self._parser.figure.addItem(p, row=j, col=i)
        #         for key, signal in plot.signals.items():
        #             print(signal)
        #             p.plot(signal[0].x_data, signal[0].y_data, pen=signal[0].color)

    def get_canvas(self) -> Canvas:
        """Gets current iplotlib canvas"""
        return self._parser.canvas

    def draw_marker_label(self, marker_name, plot_id, signal_uid, xy, color, modify):
        pass

    def delete_marker_label(self, marker_name, plot_id, signal_uid, delete):
        pass

    def check_markers(self, canvas: Canvas):
        pass

    def autoscale_y(self, impl_plot):
        pass

    def autoscale_all_y(self):
        pass

    def set_mouse_mode(self, mode: str):
        super().set_mouse_mode(mode)

        if self._mmode is None:
            return

        if mode == Canvas.MOUSE_MODE_SELECT:
            # self._mpl_toolbar.canvas.widgetlock.release(self._mpl_toolbar)
            self._parser.set_view_box()
        elif mode == Canvas.MOUSE_MODE_CROSSHAIR:
            self._parser.set_view_box()
            self._parser.activate_cursor()
        elif mode == Canvas.MOUSE_MODE_PAN:
            self._parser.set_view_box()
        elif mode == Canvas.MOUSE_MODE_ZOOM:
            self._parser.set_view_box_zoom()
        elif mode == Canvas.MOUSE_MODE_MARKER:
            self._parser.set_view_box()
            """
            if not self._marker_window.isVisible():
                self._marker_window.show()
            elif self._marker_window.isMinimized():
                self._marker_window.showNormal()
            else:
                self._marker_window.raise_()
                self._marker_window.activateWindow()
            """

    def undo(self):
        self._parser.undo()
        self._parser.unstale_cache_items()

    def redo(self):
        self._parser.redo()
        self._parser.unstale_cache_items()

    def drop_history(self):
        return self._parser.drop_history()

    def _full_screen_mode_on(self, impl_plot):
        pass

    def _full_screen_mode_off(self):
        pass

    def _impl_mouse_press_handler(self, vb):
        # if vb:
        # print(vb.parentItem())
        # self._debug_log_event(event, "Mouse released")

        ci = self._parser._impl_plot_cache_table.get_cache_item(vb.parentItem())
        if not hasattr(ci, 'plot'):
            return
        plot = ci.plot()

        if len(self._parser._stale_citems):
            self._parser.unstale_cache_items()

        if self._mmode in [Canvas.MOUSE_MODE_ZOOM, Canvas.MOUSE_MODE_PAN]:
            # Stage a command to obtain original view limits
            # Disable Zoom and Pan in PlotContour
            if isinstance(plot, PlotContour):
                return
            self.stage_view_lim_cmd()
            return

    def _impl_mouse_release_handler(self, vb):
        # self._debug_log_event(event, "Mouse released")
        if vb is None:
            pass
        else:
            if self._mmode in [Canvas.MOUSE_MODE_ZOOM, Canvas.MOUSE_MODE_PAN]:
                # commit commands from staging.
                while len(self._staging_cmds):
                    self.commit_view_lim_cmd()
                # push uncommitted changes onto the command stack.
                while len(self._commitd_cmds):
                    self.push_view_lim_cmd()
                # Update statistics
                # self.stats(self.get_canvas())

    """
    def _debug_log_event(self, event: Event, msg: str):
        logger.debug(f"{self.__class__.__name__}({hex(id(self))}) {msg} | {event}")
    """

    def unfocus_plot(self):
        pass

    def mouse_clicked(self, event):
        pass

    def mouse_moved(self, pos):
        pass
