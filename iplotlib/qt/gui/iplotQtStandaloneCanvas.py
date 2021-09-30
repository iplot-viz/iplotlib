# Description: A standalone iplotlib Qt Canvas. It is useful to test preferences-window, toolbar among other things.
# Author: Piotr Mazur
# Changelog:
#   Sept 2021: -Refactor qt classes [Jaswant Sai Panchumarti]
#              -Port to PySide2 [Jaswant Sai Panchumarti]
#              -Register VTK canvas.


import sys

from PySide2.QtCore import Qt
from PySide2.QtWidgets import QApplication

from iplotlib.qt.gui.iplotQtMainWindow import IplotQtMainWindow

import iplotLogging.setupLogger as ls

logger = ls.get_logger(__name__)


class QStandaloneCanvas:
    """A standalone canvas that is itself a Qt application that can be shown using the run method,
    separate class is needed for this since instantiating anything that extends QObject is not
    possible without instantiating a QApplication first"""

    impl_registry = dict()

    @staticmethod
    def register_implementation(impl_type, impl_alias):
        logger.info(
            F"Registering implementation {impl_type} as '{impl_alias}'")
        QStandaloneCanvas.impl_registry[impl_alias] = impl_type

    def __init__(self, impl_name=None, canvas=None, use_toolbar=True):
        super().__init__()
        self.implementation = impl_name
        self.canvas = canvas
        self.use_toolbar = use_toolbar
        self.qt_canvas = None
        self.app = None
        self.main_window = None

    def prepare(self, canvas=None):
        """Prepares qt canvas but does not show it not to block the main thread
        Therefore after calling prepare() the developer can access app/qt_canvas/main_window variables"""

        if canvas is not None:
            self.canvas = canvas

        widget_impl = self.impl_registry.get(self.implementation)
        if widget_impl:
            QApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
            self.app = QApplication(sys.argv)
            self.main_window = IplotQtMainWindow(show_toolbar=self.use_toolbar)

            self.qt_canvas = widget_impl(canvas=self.canvas)
            self.main_window.canvasStack.addWidget(self.qt_canvas)
        else:
            logger.error(
                F"No implementation found for string '{self.implementation}'. Available implementations: {self.impl_registry}")

    def show(self):
        """Shows the qt canvas on the screen. Calls prepare() if it was not called before"""
        if self.app is None:
            self.prepare()
        self.main_window.show()
        sys.exit(self.app.exec_())


def register(impl):
    try:
        if impl.lower() in ["matplotlib", "mpl", "mplot"]:
            from iplotlib.impl.matplotlib.qt.qtMatplotlibCanvas import QtMatplotlibCanvas
            QStandaloneCanvas.register_implementation(
                QtMatplotlibCanvas, impl.lower())
        elif impl.lower() == "vtk":
            from iplotlib.impl.vtk.qt.qtVTKCanvas import QtVTKCanvas
            QStandaloneCanvas.register_implementation(QtVTKCanvas, "vtk")
        else:
            logger.error(f"Invalid implementation: {impl}")
    except ModuleNotFoundError:
        logger.error(f"No {impl.lower()} canvas implementation found")


def main():
    import argparse
    import os
    import numpy as np
    from iplotlib.core import Canvas
    from iplotlib.core.signal import ArraySignal
    from iplotlib.core.plot import PlotXY

    parser = argparse.ArgumentParser()
    parser.add_argument(
        '-impl', dest='impl', help="Specify a graphics backend.", default='matplotlib')
    parser.add_argument('-t', dest='toolbar', help="Place a toolbar with canvas specific actions on the top.",
                        action='store_true', default=False)
    args = parser.parse_args()

    ts = 1_000_000_000
    te = ts + 8 * 32
    xs = np.arange(ts, te, 8, dtype=np.uint64)
    ys = np.sin(np.linspace(-1, 1, len(xs)))

    # A 2col x 2row canvas
    canvas = Canvas(2, 2, title=os.path.basename(__file__))

    # A plot in top-left with 1 signal.
    signal11 = ArraySignal(title="Signal1.1", hi_precision_data=True)
    signal11.set_data([xs, ys])
    plot11 = PlotXY(title="DateTime=True, HiPrecision=True")
    plot11.axes[0].is_date = True
    plot11.add_signal(signal11)
    canvas.add_plot(plot11, 0)

    # A plot in bottom-left with 2 stacked signal.
    signal121 = ArraySignal(title="Signal1.2.1")
    signal121.set_data([xs, ys])
    plot12 = PlotXY(title="DateTime=True, HiPrecision=True",
                    hi_precision_data=True)
    plot12.axes[0].is_date = True
    plot12.add_signal(signal121)
    signal122 = ArraySignal(title="Signal1.2.2")
    signal122.set_data([xs, ys + np.sin(xs)])
    plot12.add_signal(signal122, 2)
    canvas.add_plot(plot12, 0)

    # A plot in top-right with 1 signal.
    signal21 = ArraySignal(title="Signal2.1", hi_precision_data=True)
    signal21.set_data([xs, ys])
    plot21 = PlotXY(title="DateTime=True, HiPrecision=True")
    plot21.axes[0].is_date = True
    plot21.add_signal(signal21)
    canvas.add_plot(plot21, 1)

    # A plot in bottom-right with 1 signal.
    signal22 = ArraySignal(title="Signal2.2")
    signal22.set_data([xs, ys])
    plot22 = PlotXY(title="DateTime=False, HiPrecision=True",
                    hi_precision_data=True)
    plot22.add_signal(signal22)
    canvas.add_plot(plot22, 1)

    register(args.impl)
    pcan = QStandaloneCanvas(args.impl, canvas=canvas,
                             use_toolbar=args.toolbar)
    pcan.prepare()
    pcan.show()
