import sys

from PyQt5.QtWidgets import QApplication, QHBoxLayout, QVBoxLayout, QWidget

from iplotlib.core.canvas import Canvas
from iplotlib.core.plot import PlotXY
from iplotlib.core.signal import ArraySignal
from iplotlib.impl.matplotlib.qt.qtMatplotlibCanvas import QtMatplotlibCanvas
from iplotlib.qt.qtCanvasToolbar import CanvasToolbar
from iplotlib.qt.qtPlotCanvas import QtPlotCanvas


def createCanvas():
    canvas = Canvas()
    plot1 = PlotXY()

    signal3 = ArraySignal(color="blue")
    signal3.set_data([[1600327627340000000, 1600328627340000000, 1600329627340000000], [2550, 2600, 2580]])
    plot1.add_signal(signal3)
    canvas.add_plot(plot1)
    return QtMatplotlibCanvas(canvas=canvas)

app = QApplication(sys.argv)

# One toolbar, one canvas
toolbar1 = CanvasToolbar()
canvas1 = createCanvas()
toolbar1.connect(canvas1)

widget1 = QWidget()
widget1.setStyleSheet("background-color: red")
widget1.setLayout(QVBoxLayout())
widget1.layout().addWidget(toolbar1)
widget1.layout().addWidget(canvas1)

# Two toolbars, one canvas
toolbar2_1 = CanvasToolbar()
toolbar2_2 = CanvasToolbar()
canvas2 = createCanvas()
toolbar2_1.connect(canvas2)
toolbar2_2.connect(canvas2)

widget2 = QWidget()
widget2.setStyleSheet("background-color: green")
widget2.setLayout(QVBoxLayout())
widget2.layout().addWidget(toolbar2_1)
widget2.layout().addWidget(canvas2)
widget2.layout().addWidget(toolbar2_2)

# One toolbar, two canvases


toolbar3 = CanvasToolbar()
canvas3_1 = createCanvas()
canvas3_2 = createCanvas()
toolbar3.connect(canvas3_1)
toolbar3.connect(canvas3_2)

widget3 = QWidget()
widget3.setStyleSheet("background-color: blue")
widget3.setLayout(QVBoxLayout())
widget3_1 = QWidget()
widget3_1.setLayout(QHBoxLayout())
widget3_1.layout().addWidget(canvas3_1)
widget3_1.layout().addWidget(canvas3_2)
widget3.layout().addWidget(toolbar3)
widget3.layout().addWidget(widget3_1)

# Main layout
main_widget = QWidget()
main_widget.setLayout(QVBoxLayout())
main_widget.layout().addWidget(widget1)
main_widget.layout().addWidget(widget2)
main_widget.layout().addWidget(widget3)

main_widget.show()
sys.exit(app.exec_())
