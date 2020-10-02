from PyQt5 import QtCore
from PyQt5.QtCore import QPoint, Qt, QRect
from PyQt5.QtGui import QPainter, QPen, QBrush, QColor
from PyQt5.QtWidgets import QWidget

from qt.QtOverlayCanvasTool import QtOverlayCanvasTool
from qt.QtPlotCanvas import QtPlotCanvas


class QtOverlayCrosshairTool(QtOverlayCanvasTool):

    def __init__(self, vertical=True, horizontal=True, linewidth=1, color="red"):
        self.vertical = vertical
        self.horizontal = horizontal
        self.linewidth = linewidth
        self.color = color
        self.mouse_pos: QPoint = None
        self.graph_pos: QPoint = None
        self.graph_bounds = None
        self.mouse_stay: bool = False
        self.tooltip_color: int = Qt.red
        self.tooltip_background: int = QColor(200, 200, 200)
        self.tooltip_rect: QRect = QRect(10, 15, 10, 10)


    def process_paint(self, painter: QPainter):
        if self.mouse_pos is not None:
            painter.setPen(QPen(QColor(self.color), self.linewidth, Qt.SolidLine))
            min_x, min_y, max_x, max_y = (0, 0, painter.viewport().width(), painter.viewport().height())
            if self.graph_bounds:
                min_x, min_y, max_x, max_y = self.graph_bounds
            if self.vertical and min_x <= self.mouse_pos.x() <= max_x:
                painter.drawLine(self.mouse_pos.x(), painter.viewport().height()-min_y, self.mouse_pos.x(), painter.viewport().height()-max_y)
            if self.horizontal and (painter.viewport().height()-max_y) <= self.mouse_pos.y() <= (painter.viewport().height()-min_y):
                painter.drawLine(min_x, self.mouse_pos.y(), max_x, self.mouse_pos.y())

        if self.graph_pos is not None:
            painter.setPen(QPen(self.tooltip_color, 1, Qt.SolidLine))
            x: str = " " + str(self.graph_pos.x()) + " "
            y: str = " " + str(self.graph_pos.y()) + " "

            x_rect = painter.boundingRect(self.tooltip_rect, Qt.AlignLeft | Qt.AlignTop, x)
            painter.fillRect(x_rect, self.tooltip_background)
            painter.drawText(x_rect, Qt.AlignLeft | Qt.AlignTop, x)

            y_rect = painter.boundingRect(QRect(self.tooltip_rect.x(), self.tooltip_rect.y()+2+x_rect.height(), 10, 10), Qt.AlignLeft | Qt.AlignTop, y)
            painter.fillRect(y_rect, self.tooltip_background)
            painter.drawText(y_rect, Qt.AlignLeft | Qt.AlignTop, y)

    def process_event(self, canvas: QtPlotCanvas, event):

        if hasattr(canvas, "_gnuplot_canvas"):
            self.graph_bounds = canvas._gnuplot_canvas.terminal_range

        if event.type() == QtCore.QEvent.MouseMove:
            if not self.mouse_stay:
                self.mouse_pos = event.localPos()
                # self.graph_pos = canvas.scene_to_graph(event.localPos().x(), event.localPos().y())
            return True

        elif event.type() == QtCore.QEvent.Enter:
            pass

        elif event.type() == QtCore.QEvent.Leave:
            if not self.mouse_stay:
                self.mouse_pos = None
                self.graph_pos = None
            return True

        elif event.type() == QtCore.QEvent.MouseButtonPress:
            self.mouse_stay = not self.mouse_stay
            if not self.mouse_stay:
                self.mouse_pos = event.localPos()
            return True

        elif event.type() != 12:
            # print("UNKNOWN EVENT " + str(event.type()))
            pass
