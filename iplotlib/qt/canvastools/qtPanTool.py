from qtpy import QtCore
from qtpy.QtCore import QPointF, Qt, Signal
from qtpy.QtGui import QPainter
from iplotlib.qt.qtOverlayCanvasTool import QtOverlayCanvasTool


class QtOverlayPanTool(QtOverlayCanvasTool):

    panAction = Signal(float,float,float,float)

    def __init__(self):
        super().__init__()
        self.mouse_pressed: bool = False
        self.move_start: QPointF = None

    def process_paint(self, widget, painter: QPainter):
        pass

    def process_event(self, widget, event):
        if event.type() == QtCore.QEvent.MouseMove:
            if self.mouse_pressed:
                pos = QPointF(*widget._gnuplot_canvas.to_graph(event.localPos().x(), event.localPos().y()))
                delta = self.move_start - pos
                bounds = widget._gnuplot_canvas.plot_range
                widget._gnuplot_canvas.set_bounds(bounds[0]+delta.x(), bounds[1]+delta.y(), bounds[2]+delta.x(), bounds[3]+delta.y(), replot=True)
                self.panAction.emit(bounds[0]+delta.x(), bounds[1]+delta.y(), bounds[2]+delta.x(), bounds[3]+delta.y())
            return True

        elif event.type() == QtCore.QEvent.Enter:
            pass
        elif event.type() == QtCore.QEvent.Leave:
            self.move_start = None
            self.mouse_pressed = False
            return True

        elif event.type() == QtCore.QEvent.MouseButtonPress:
            if event.button() == Qt.LeftButton:
                self.move_start = QPointF(*widget._gnuplot_canvas.to_graph(event.localPos().x(), event.localPos().y()))
                self.mouse_pressed = True
            return True

        elif event.type() == QtCore.QEvent.MouseButtonRelease:
            if event.button() == Qt.LeftButton:
                self.mouse_pressed = False
            return True

        elif event.type() == QtCore.QEvent.MouseButtonDblClick:
            if event.button() == Qt.LeftButton:
                widget._gnuplot_canvas.reset_bounds()
        elif event.type() != 12:
            # print("UNKNOWN EVENT " + str(event.type()))
            pass
