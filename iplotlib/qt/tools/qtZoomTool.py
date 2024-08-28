from math import sqrt

from PySide6 import QtCore
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QBrush, QColor, QPainter, QPen
from iplotlib.qt.gui.iplotOverlayCanvasTool import QtOverlayCanvasTool


class QtOverlayZoomTool(QtOverlayCanvasTool):

    def __init__(self):
        self.rect_start: QPoint = None
        self.mouse_pos: QPoint = None
        self.graph_bounds = None

    def process_paint(self, widget, painter: QPainter):
        if self.rect_start is not None:
            painter.setPen(QPen(Qt.red, 1, Qt.DashLine))
            x1, y1, x2, y2 = self.rect_start.x(), self.rect_start.y(), self.mouse_pos.x(), self.mouse_pos.y()
            if self.graph_bounds:
                x1 = self.__limit(x1, self.graph_bounds[0], self.graph_bounds[2])
                x2 = self.__limit(x2, self.graph_bounds[0], self.graph_bounds[2])
                y1 = self.__limit(y1, painter.viewport().height() - self.graph_bounds[3],
                                  painter.viewport().height() - self.graph_bounds[1])
                y2 = self.__limit(y2, painter.viewport().height() - self.graph_bounds[3],
                                  painter.viewport().height() - self.graph_bounds[1])

            painter.fillRect(x1, y1, x2 - x1, y2 - y1, QBrush(QColor(255, 0, 255, 64)))
            painter.drawRect(x1, y1, x2 - x1, y2 - y1)

    def process_event(self, widget, event):

        if hasattr(widget, "_gnuplot_canvas"):
            self.graph_bounds = widget._gnuplot_canvas.terminal_range

        if event.type() == QtCore.QEvent.MouseMove:
            self.mouse_pos = event.localPos()
            return True

        elif event.type() == QtCore.QEvent.Enter:
            pass
        elif event.type() == QtCore.QEvent.Leave:
            self.rect_start = None
            return True

        elif event.type() == QtCore.QEvent.MouseButtonPress:

            if self.rect_start is None and event.button() == Qt.LeftButton:
                self.rect_start = event.localPos()
            return True

        elif event.type() == QtCore.QEvent.MouseButtonRelease:
            if event.button() == Qt.LeftButton:
                if self.__distance(self.rect_start, event.localPos()) > 10:
                    self.__do_zoom(widget, self.rect_start, event.localPos())

                self.rect_start = None
            # elif event.button() == Qt.RightButton:
            #     self.__reset(canvas)
            return True
        elif event.type() == QtCore.QEvent.MouseButtonDblClick:
            if event.button() == Qt.LeftButton:
                widget._gnuplot_canvas.reset_bounds()

        elif event.type() != 12:
            # print("UNKNOWN EVENT " + str(event.type()))
            pass

    def __distance(self, start: QPoint, end: QPoint) -> float:
        if start is None or end is None:
            return 0
        return sqrt((start.x() - end.x()) ** 2 + (start.y() - end.y()) ** 2)

    def __do_zoom(self, widget, start: QPoint, end: QPoint):
        if hasattr(widget, "_gnuplot_canvas"):
            gs = widget._gnuplot_canvas.to_graph(start.x(), start.y())
            ge = widget._gnuplot_canvas.to_graph(end.x(), end.y())
            widget._gnuplot_canvas.set_bounds(gs[0], gs[1], ge[0], ge[1], replot=True, save_history=True)

    def __limit(self, val, lo, hi):
        if val < lo:
            return lo
        if val > hi:
            return hi
        return val
