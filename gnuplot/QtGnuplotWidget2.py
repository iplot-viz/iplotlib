from PyQt5.QtGui import QResizeEvent
from qt.gnuplotwidget.pyqt5gnuplotwidget.PyGnuplotWidget import QtGnuplotWidget

"""
This wrapper class is needed in order to change terminal size when widget itself is resized
This functionality is broken in orgiginal cpp widget
"""


class QtGnuplotWidget2(QtGnuplotWidget):


    def cleanup(self):
        if hasattr(self, "_gnuplot_canvas"):
            self._gnuplot_canvas.cleanup()

    def resizeEvent(self, event: QResizeEvent) -> None:
        print("GNUPLOT2::Resize: serverName={} size={} visible={} oldSize={}".format(self.serverName(), event.size(), self.isVisible(), event.oldSize()))

        if hasattr(self, "_gnuplot_canvas"):
            self._gnuplot_canvas.write("set term qt widget '{}' size {},{} font 'Arial,8' noenhanced"
                                       .format(self.serverName(), self.geometry().width(), self.geometry().height()), True)
            self._gnuplot_canvas.process_layout()
