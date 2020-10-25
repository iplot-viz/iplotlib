from PyQt5.QtCore import QPoint, QPointF
from PyQt5.QtGui import QResizeEvent
from qt.gnuplotwidget.pyqt5gnuplotwidget.PyGnuplotWidget import QtGnuplotWidget

"""
This wrapper class is needed in order to change terminal size when widget itself is resized
This functionality is broken in orgiginal cpp widget
"""


class QtGnuplotWidget2(QtGnuplotWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("border: 0px none")

    def cleanup(self):
        if hasattr(self, "_gnuplot_canvas"):
            self._gnuplot_canvas.cleanup()

    def resizeEvent(self, event: QResizeEvent) -> None:
        # print("GNUPLOT2::Resize: serverName={} size={} visible={} oldSize={}".format(self.serverName(), event.size(), self.isVisible(), event.oldSize()))

        if hasattr(self, "_gnuplot_canvas"):
            self._gnuplot_canvas.write("set term qt widget '{}' size {},{} font 'Arial,8' noenhanced"
                                       .format(self.serverName(), self.geometry().width(), self.geometry().height()), True)
            self._gnuplot_canvas.process_layout()


    def screen_to_graph(self, point: QPoint):
        graph_bounds = self._gnuplot_canvas.plot_range
        screen_bounds = self._gnuplot_canvas.terminal_range
        if graph_bounds and screen_bounds:
            dx = (graph_bounds[2]-graph_bounds[0])/(screen_bounds[2]-screen_bounds[0])
            dy = (graph_bounds[3]-graph_bounds[1])/(screen_bounds[3]-screen_bounds[1])

            x = graph_bounds[0]+(point.x()-screen_bounds[0])*dx
            y = graph_bounds[1] + (self.geometry().height()-point.y()-screen_bounds[1])*dy
            return QPointF(x, y)

    def graph_to_screen(self, point: QPointF):
        graph_bounds = self._gnuplot_canvas.plot_range
        screen_bounds = self._gnuplot_canvas.terminal_range
        if graph_bounds and screen_bounds:
            dx = (screen_bounds[2]-screen_bounds[0])/(graph_bounds[2]-graph_bounds[0])
            dy = (screen_bounds[3]-screen_bounds[1])/(graph_bounds[3]-graph_bounds[1])
            x = screen_bounds[0]+(point.x()-graph_bounds[0])*dx
            y = self.geometry().height() - (screen_bounds[1] + (point.y()-graph_bounds[1])*dy)
            return QPointF(x, y)