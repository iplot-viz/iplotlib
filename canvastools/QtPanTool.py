from PyQt5 import QtCore
from PyQt5.QtCore import QPoint, Qt
from PyQt5.QtGui import QPainter

from qt.QtOverlayCanvasTool import QtOverlayCanvasTool
from qt.QtPlotCanvas import QtPlotCanvas


class QtOverlayPanTool(QtOverlayCanvasTool):

    def __init__(self):
        self.mouse_pressed: bool = False
        self.move_start: QPoint = None

    def process_paint(self, painter: QPainter):
        pass

    def process_event(self, canvas: QtPlotCanvas, event):
        if event.type() == QtCore.QEvent.MouseMove:
            if self.mouse_pressed:
                pos = canvas.scene_to_graph(event.localPos().x(), event.localPos().y())
                dx = self.move_start.x() - pos.x()
                dy = self.move_start.y() - pos.y()
                print("Pan tool: moving by ("+str(dx)+","+str(dy)+") canvas="+str(canvas))
                for a in canvas.axes_list():
                    if len(a) > 1:
                        a[0].begin += dx
                        a[0].end += dx
                        a[1].begin += dy
                        a[1].end += dy

                        canvas.replot()
            return True

        elif event.type() == QtCore.QEvent.Enter:
            pass
        elif event.type() == QtCore.QEvent.Leave:
            self.move_start = None
            self.mouse_pressed = False
            return True

        elif event.type() == QtCore.QEvent.MouseButtonPress:
            if event.button() == Qt.LeftButton:
                self.move_start = canvas.scene_to_graph(event.localPos().x(), event.localPos().y())
                self.mouse_pressed = True
            return True

        elif event.type() == QtCore.QEvent.MouseButtonRelease:
            if event.button() == Qt.LeftButton:
                self.mouse_pressed = False
            else:
                self.__reset(canvas)
            return True

        elif event.type() != 12:
            # print("UNKNOWN EVENT " + str(event.type()))
            pass

    @staticmethod
    def __reset(canvas: QtPlotCanvas):
        for c_axis, plot in zip(canvas.axes_list(), canvas.plots()):
            for index, axis in enumerate(plot.axes):
                c_axis[index].min = axis.min
                c_axis[index].max = axis.max
        canvas.replot()