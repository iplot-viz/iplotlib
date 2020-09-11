from math import sqrt

from PyQt5 import QtCore
from PyQt5.QtCore import QPoint, Qt, QRect, QRectF
from PyQt5.QtGui import QPainter, QPen, QBrush, QColor

from qt.QtCanvasTool import QtCanvasTool
from qt.QtPlotCanvas import QtPlotCanvas


class QtZoomTool(QtCanvasTool):

    def __init__(self):
        self.rect_start: QPoint = None
        self.mouse_pos: QPoint = None

    def process_paint(self, painter: QPainter):
        if self.rect_start is not None:
            painter.setPen(QPen(Qt.red, 1, Qt.DashLine))
            painter.fillRect(self.rect_start.x(), self.rect_start.y(), self.mouse_pos.x()-self.rect_start.x(), self.mouse_pos.y()-self.rect_start.y(), QBrush(QColor(255, 0, 255, 64)))
            painter.drawRect(self.rect_start.x(), self.rect_start.y(), self.mouse_pos.x()-self.rect_start.x(), self.mouse_pos.y()-self.rect_start.y())
            # painter.drawRect(self.rect_start.x(), self.rect_start.y(), self.mouse_pos.x()-self.rect_start.x(), self.mouse_pos.y()-self.rect_start.y())
            # painter.drawRect(QRectF(self.rect_start,(self.mouse_pos-self.rect_start) ))


    def process_event(self, canvas: QtPlotCanvas, event):
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
                    self.__do_zoom(canvas, self.rect_start, event.localPos())

                self.rect_start = None
            elif event.button() == Qt.RightButton:
                self.__reset(canvas)
            return True

        elif event.type() != 12:
            # print("UNKNOWN EVENT " + str(event.type()))
            pass

    @staticmethod
    def __reset(canvas: QtPlotCanvas):
        for c_axis, plot in zip(canvas.axes_list(), canvas.plots()):
            for index, axis in enumerate(plot.axes):
                c_axis[index]['min'] = axis.min
                c_axis[index]['max'] = axis.max
        canvas.replot()

    def __distance(self, start: QPoint, end: QPoint) -> float:
        return sqrt((start.x()-end.x())**2 + (start.y()-end.y())**2)

    def __do_zoom(self, canvas: QtPlotCanvas, start: QPoint, end: QPoint):
        p1 = canvas.scene_to_graph(start.x(), start.y())
        p2 = canvas.scene_to_graph(end.x(), end.y())
        print("ZOOM tool: rect " + str(p1) + " , " + str(p2) +" canvas="+str(canvas))
        for a in canvas.axes_list():
            if len(a) > 1:
                a[0]['min'] = p1.x() if p1.x() < p2.x() else p2.x()
                a[0]['max'] = p1.x() if p1.x() > p2.x() else p2.x()

                a[1]['min'] = p1.y() if p1.y() < p2.y() else p2.y()
                a[1]['max'] = p1.y() if p1.y() > p2.y() else p2.y()

                canvas.replot()

        pass
