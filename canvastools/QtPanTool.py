from PyQt5 import QtCore
from PyQt5.QtCore import QPoint, Qt, QPointF
from PyQt5.QtGui import QPainter

from qt.QtOverlayCanvasTool import QtOverlayCanvasTool
from qt.QtPlotCanvas import QtPlotCanvas


class QtOverlayPanTool(QtOverlayCanvasTool):

    def __init__(self):
        self.mouse_pressed: bool = False
        self.move_start: QPointF = None

    def process_paint(self, painter: QPainter):
        pass

    def process_event(self, canvas: QtPlotCanvas, event):
        if event.type() == QtCore.QEvent.MouseMove:
            if self.mouse_pressed:
                pos = QPointF(*canvas._gnuplot_canvas.to_graph(event.localPos().x(), event.localPos().y()))
                delta = self.move_start - pos
                bounds = canvas._gnuplot_canvas.plot_range
                print("Pan tool: moving by " + str(delta) + " Current: " + str(bounds))
                canvas._gnuplot_canvas.set_bounds(bounds[0]+delta.x(), bounds[1]+delta.y(), bounds[2]+delta.x(), bounds[3]+delta.y())
            return True

        elif event.type() == QtCore.QEvent.Enter:
            pass
        elif event.type() == QtCore.QEvent.Leave:
            self.move_start = None
            self.mouse_pressed = False
            return True

        elif event.type() == QtCore.QEvent.MouseButtonPress:
            if event.button() == Qt.LeftButton:
                self.move_start = QPointF(*canvas._gnuplot_canvas.to_graph(event.localPos().x(), event.localPos().y()))
                self.mouse_pressed = True
            return True

        elif event.type() == QtCore.QEvent.MouseButtonRelease:
            if event.button() == Qt.LeftButton:
                self.mouse_pressed = False
            return True

        elif event.type() == QtCore.QEvent.MouseButtonDblClick:
            if event.button() == Qt.LeftButton:
                canvas._gnuplot_canvas.reset_bounds()
        elif event.type() != 12:
            # print("UNKNOWN EVENT " + str(event.type()))
            pass
