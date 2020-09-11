from PyQt5 import QtCore
from PyQt5.QtCore import QPoint, Qt, QRect
from PyQt5.QtGui import QPainter, QPen, QBrush, QColor
from PyQt5.QtWidgets import QWidget

from qt.QtCanvasTool import QtCanvasTool
from qt.QtPlotCanvas import QtPlotCanvas


class QtCrosshairTool(QtCanvasTool):

    tooltip_color: int = Qt.red
    tooltip_background: int = QColor(200,200,200)
    tooltip_rect: QRect = QRect(10, 15, 10, 10)

    mouse_pos: QPoint = None
    graph_pos: QPoint = None
    mouse_stay: bool = False

    def process_paint(self, painter: QPainter):
        if self.mouse_pos is not None:
            painter.setPen(QPen(Qt.green, 1, Qt.DashLine))
            painter.drawLine(self.mouse_pos.x(), 0, self.mouse_pos.x(), painter.viewport().height()) #TODO: We need to know plot bounds!
            painter.drawLine(0, self.mouse_pos.y(), painter.viewport().width(), self.mouse_pos.y())  # TODO: We need to know plot bounds!

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
        if event.type() == QtCore.QEvent.MouseMove:
            if not self.mouse_stay:
                self.mouse_pos = event.localPos()
                self.graph_pos = canvas.scene_to_graph(event.localPos().x(), event.localPos().y())

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
