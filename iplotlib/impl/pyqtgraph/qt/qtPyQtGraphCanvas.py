from collections import defaultdict

import numpy as np
from PySide6.QtCore import QMargins, Qt, Signal
from PySide6.QtWidgets import QVBoxLayout

from iplotlib.core import Canvas, BackendParserBase
import pyqtgraph as pg

from iplotlib.impl.matplotlib.matplotlibCanvas import MatplotlibParser
from iplotlib.impl.pyqtgraph.pyQtGraphCanvas import PyQtGraphParser
from iplotlib.qt.gui.IplotQtStatistics import IplotQtStatistics
from iplotlib.qt.gui.iplotQtCanvas import IplotQtCanvas
from iplotlib.qt.gui.iplotQtMarker import IplotQtMarker
import iplotLogging.setupLogger as Sl
from iplotlib.qt.models import PlotItem

logger = Sl.get_logger(__name__)


class QtPyQtGraphCanvas(IplotQtCanvas):
    """Qt widget that internally uses a matplotlib canvas backend"""

    dropSignal = Signal(object)

    def __init__(self, parent=None, tight_layout=True, **kwargs):
        super().__init__(parent, **kwargs)

        # Aquí podrías poner tus clases equivalentes a marcadores y estadísticas
        self._draw_call_counter = 0
        self._marker_window = IplotQtMarker()  # Conéctalo según tu lógica
        self._marker_window.dropMarker.connect(self.draw_marker_label)
        self._marker_window.deleteMarker.connect(self.delete_marker_label)

        self._stats_table = IplotQtStatistics()

        self.info_shared_x_dialog = False
        self._parser = PyQtGraphParser()

        self._vlayout = QVBoxLayout(self)
        self._vlayout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._vlayout.setContentsMargins(QMargins())
        self._vlayout.addWidget(self._parser.figure)
        self._parser.figure.scene().sigMouseClicked.connect(self.mouse_clicked)

        self.setLayout(self._vlayout)

        # Drag & Drop
        self.setAcceptDrops(True)

    def draw_marker_label(self, marker_name, plot_id, signal_uid, xy, color, modify):
        pass

    def delete_marker_label(self, marker_name, plot_id, signal_uid, delete):
        pass

    def unfocus_plot(self):
        """Quita el focus del plot actual."""
        if self._parser:
            self._parser.set_focus_plot(None)

    def check_markers(self, canvas: Canvas):
        pass

    def mouse_clicked(self, event):
        if not event.currentItem:
            return
        plot = event.currentItem.parentItem()
        if not plot or not isinstance(plot, PlotItem):
            return
        if event.button() == Qt.MouseButton.LeftButton:
            if event.double():
                self._parser.set_focus_plot(plot)
            else:
                pass
        elif event.button() == Qt.MouseButton.RightButton:
            if event.double():
                pass
            else:
                pass


    def mouse_moved(self, pos):
        pass

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
