from PyQt5 import QtCore
from PyQt5.QtCore import QPoint, QPointF, Qt, QRect, pyqtSignal
from PyQt5.QtGui import QPainter, QPen, QColor


from iplotlib.qt.qtOverlayCanvasTool import QtOverlayCanvasTool


class QtOverlayCrosshairTool(QtOverlayCanvasTool):

    crosshairMoved = pyqtSignal(QPointF)
    crosshairLeave = pyqtSignal()

    def __init__(self, vertical=True, horizontal=True, linewidth=1, color="red"):
        super().__init__()
        self.vertical = vertical
        self.horizontal = horizontal
        self.linewidth = linewidth
        self.color = color
        self.graph_pos: QPoint = None
        self.graph_screen_bounds = None
        self.graph_bounds = None
        self.mouse_stay: bool = False
        self.tooltip_color: int = Qt.red
        self.tooltip_background: int = QColor(200, 200, 200, 200)
        self.tooltip_rect: QRect = QRect(10, 15, 10, 10)

    def process_paint(self, widget, painter: QPainter):

        if self.graph_pos is not None:
            screen_pos = widget.graph_to_screen(self.graph_pos)

            if screen_pos is not None:
                painter.setPen(QPen(QColor(self.color), self.linewidth, Qt.SolidLine))
                min_x, min_y, max_x, max_y = (0, 0, painter.viewport().width(), painter.viewport().height())
                if self.graph_screen_bounds:
                    min_x, min_y, max_x, max_y = self.graph_screen_bounds
                if self.vertical and min_x <= screen_pos.x() <= max_x:
                    painter.drawLine(screen_pos.x(), painter.viewport().height()-min_y, screen_pos.x(), painter.viewport().height()-max_y)
                if self.horizontal and (painter.viewport().height()-max_y) <= screen_pos.y() <= (painter.viewport().height()-min_y):
                    painter.drawLine(min_x, screen_pos.y(), max_x, screen_pos.y())

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

    def process_event(self, widget, event):

        if hasattr(widget, "_gnuplot_canvas"):
            self.graph_screen_bounds = widget._gnuplot_canvas.terminal_range
            self.graph_bounds = widget._gnuplot_canvas.plot_range

        if event.type() == QtCore.QEvent.MouseMove:
            if not self.mouse_stay:
                self.graph_pos = widget.screen_to_graph(event.localPos())
                if self.graph_pos is not None:
                    self.crosshairMoved.emit(self.graph_pos)

            return True

        elif event.type() == QtCore.QEvent.Leave:
            if not self.mouse_stay:
                self.graph_pos = None
                self.crosshairLeave.emit()
            return True

        elif event.type() != 12:
            # print("UNKNOWN EVENT " + str(event.type()))
            pass
