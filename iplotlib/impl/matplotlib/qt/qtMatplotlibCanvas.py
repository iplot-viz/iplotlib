from threading import Timer

import matplotlib
from qtpy import QtGui
from qtpy.QtCore import QMargins, QMetaObject, Qt, Slot
from qtpy.QtWidgets import QSizePolicy, QStyle, QVBoxLayout
from matplotlib.backend_bases import _Mode
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar

from iplotlib.core.canvas import Canvas
from iplotlib.impl.matplotlib.matplotlibCanvas import MatplotlibCanvas
from iplotlib.qt.qtPlotCanvas import QtPlotCanvas


class QtMatplotlibCanvas(QtPlotCanvas):
    """Qt widget that internally uses MatplotlibCanvas as backend"""

    def __init__(self, parent=None, **kwargs):
        super().__init__(parent, **kwargs)

        self.figure_canvas = None
        self.mpl_toolbar = None
        self.mouse_mode = None
        self.tight_layout = kwargs.get('tight_layout')

        self.matplotlib_canvas = MatplotlibCanvas(tight_layout=self.tight_layout, mpl_flush_method=self.draw_in_main_thread)
        self.figure_canvas = FigureCanvas(self.matplotlib_canvas.figure)
        self.figure_canvas.setSizePolicy(QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding))
        self.mpl_toolbar = NavigationToolbar(self.figure_canvas, self)
        self.mpl_toolbar.setVisible(False)

        self.setLayout(QVBoxLayout())
        self.layout().setAlignment(Qt.AlignTop)
        self.layout().setContentsMargins(QMargins())
        self.layout().addWidget(self.figure_canvas)

        self.set_canvas(kwargs.get('canvas'))

        self.refresh_timer = None

    def draw_in_main_thread(self):
        QMetaObject.invokeMethod(self, "flush_draw_queue")

    @Slot()
    def flush_draw_queue(self):
        if self.matplotlib_canvas:
            self.matplotlib_canvas.process_work_queue()

    def set_canvas(self, canvas, focus_plot=None):
        super().set_canvas(canvas)
        self.matplotlib_canvas.deactivate_cursor()

        if canvas:
            self.matplotlib_canvas.process_iplotlib_canvas(canvas)
            self.set_mouse_mode(self.mouse_mode or canvas.mouse_mode)
            QMetaObject.invokeMethod(self, "apply_tight_layout")

    def get_canvas(self):
        return self.matplotlib_canvas.canvas if self.matplotlib_canvas else None

    @Slot()
    def apply_tight_layout(self):
        self.matplotlib_canvas.figure.tight_layout()
        self.matplotlib_canvas.figure.canvas.draw()

    def process_canvas_toolbar(self, toolbar):
        toolbar.addSeparator()
        toolbar.addAction(self.style().standardIcon(getattr(QStyle, "SP_FileDialogListView")), "Layout", self.apply_tight_layout)

    def set_mouse_mode(self, mode: str):
        self.mouse_mode = mode

        def reset_tool():
            if self.mpl_toolbar:
                self.mpl_toolbar.mode = _Mode.NONE
                self.matplotlib_canvas.deactivate_cursor()

        reset_tool()

        if self.mpl_toolbar and self.mouse_mode is not None:
            if mode == Canvas.MOUSE_MODE_CROSSHAIR:
                self.mpl_toolbar.canvas.widgetlock.release(self.mpl_toolbar)
                self.matplotlib_canvas.activate_cursor()
                self.matplotlib_canvas.figure.canvas.mpl_connect('button_press_event', self.click)

            elif mode == Canvas.MOUSE_MODE_PAN:
                self.matplotlib_canvas.deactivate_cursor()
                self.mpl_toolbar.pan()
                self.matplotlib_canvas.figure.canvas.mpl_connect('button_press_event', self.click)
            elif mode == Canvas.MOUSE_MODE_ZOOM:
                self.matplotlib_canvas.deactivate_cursor()
                self.mpl_toolbar.zoom()
                self.matplotlib_canvas.figure.canvas.mpl_connect('button_press_event', self.click)
            elif mode == Canvas.MOUSE_MODE_SELECT:
                self.matplotlib_canvas.figure.canvas.mpl_connect('button_press_event', self.click)
                pass

    def click(self, event):
        """Additional callback to allow for focusing on one plot and returning home after double click"""
        if event.dblclick:
            if self.mouse_mode == Canvas.MOUSE_MODE_SELECT and event.button == 1 and event.inaxes is not None:
                self.focus_plot(event.inaxes._plot)
            else:
                self.mpl_toolbar.home()

    def keyPressEvent(self, event: QtGui.QKeyEvent):
        if event.text() == 'n':
            self.mpl_toolbar.forward()
        elif event.text() == 'p':
            self.mpl_toolbar.back()

    def back(self):
        if self.mpl_toolbar:
            self.mpl_toolbar.back()

    def forward(self):
        if self.mpl_toolbar:
            self.mpl_toolbar.forward()

    def focus_plot(self, plot):
        """Toggle focus on one plot on/off"""
        if self.matplotlib_canvas.focused_plot is None:
            self.matplotlib_canvas.focus_plot(plot)
        else:
            self.matplotlib_canvas.unfocus_plot()

        self.matplotlib_canvas.figure.canvas.draw()
