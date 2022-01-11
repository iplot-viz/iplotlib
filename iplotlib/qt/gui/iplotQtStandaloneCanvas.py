# Description: A standalone iplotlib Qt Canvas. It is useful to test preferences-window, toolbar among other things.
# Author: Piotr Mazur
# Changelog:
#   Sept 2021: -Refactor qt classes [Jaswant Sai Panchumarti]
#              -Port to PySide2 [Jaswant Sai Panchumarti]
#              -Register VTK canvas.


from functools import partial
import importlib
import os
import pkgutil
import sys

from PySide2.QtCore import Qt
from PySide2.QtWidgets import QAction, QActionGroup, QApplication
from PySide2.QtGui import QGuiApplication

from iplotlib.core import Canvas
from iplotlib import examples as iplotExamples
from iplotlib.interface.iplotSignalAdapter import AccessHelper
from iplotlib.qt.gui.iplotQtCanvasFactory import IplotQtCanvasFactory
from iplotlib.qt.gui.iplotQtMainWindow import IplotQtMainWindow

import iplotLogging.setupLogger as ls

logger = ls.get_logger(__name__)


class QStandaloneCanvas:
    """A standalone canvas that is itself a Qt application that can be shown using the run method,
    separate class is needed for this since instantiating anything that extends QObject is not
    possible without instantiating a QApplication first"""

    def __init__(self, impl_name=None, use_toolbar=True):
        super().__init__()
        self.impl_name = impl_name
        self.use_toolbar = use_toolbar
        self.app = None
        self.main_window = None

    def prepare(self, argv=sys.argv):
        """Prepares IplotQtMainWindow but does not show it not to block the main thread
        Therefore after calling prepare() the developer can access app/qt_canvas/main_window variables"""

        QApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
        self.app = QApplication(argv)
        self.main_window = IplotQtMainWindow(show_toolbar=self.use_toolbar)
        self.selectMenu = self.main_window.menuBar().addMenu('&Canvases')
        self.canvasActionGroup = QActionGroup(self.main_window)
        self.canvasActionGroup.setExclusive(True)

        logger.debug(f"Detected {len(QGuiApplication.screens())} screen (s)")
        max_width = 0
        for screen in QGuiApplication.screens():
            max_width = max(screen.geometry().width(), max_width)
        logger.debug(f"Detected max screen width: {max_width}")
        AccessHelper.num_samples = max_width
        logger.info(f"Fallback dec_samples : {AccessHelper.num_samples}")

    def add_canvas(self, canvas: Canvas):
        if not self.main_window:
            logger.warning(
                "Not yet. Please prepare the Qt5 application. Call 'prepare'")
            return

        qt_canvas = IplotQtCanvasFactory.new(
            self.impl_name, parent=self.main_window, canvas=canvas)
        canvasIdx = self.main_window.canvasStack.count()
        self.main_window.canvasStack.addWidget(qt_canvas)

        act = QAction(str(canvasIdx + 1).zfill(2) + '-' +
                      canvas.title, self.main_window)
        act.setCheckable(True)
        act.triggered.connect(
            partial(self.main_window.canvasStack.setCurrentIndex, canvasIdx))
        self.canvasActionGroup.addAction(act)
        self.selectMenu.addAction(act)


    def show(self):
        """Shows the qt canvas on the screen. Calls prepare() if it was not called before"""
        if self.app is None:
            self.prepare()
        
        # select the first canvas
        try:
            firstAct = self.canvasActionGroup.actions()[0]
            firstAct.trigger()
        except IndexError:
            logger.warning('The main thread is now blocked. You can no longer add canvases.')

        self.main_window.show()
        sys.exit(self.app.exec_())


def main():
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        '-impl', dest='impl', help="Specify a graphics backend.", default='matplotlib')
    parser.add_argument('-t', dest='toolbar', help="Place a toolbar with canvas specific actions on the top.",
                        action='store_true', default=False)
    parser.add_argument('-use-fallback-samples', dest='use_fallback_samples', action='store_true', default=False)
    args = parser.parse_args()

    AccessHelper.num_samples_override = args.use_fallback_samples
    canvas_app = QStandaloneCanvas(args.impl, use_toolbar=args.toolbar)
    canvas_app.prepare()

    for script in  pkgutil.walk_packages(iplotExamples.__path__, iplotExamples.__name__ + '.'):
        module = importlib.import_module(script.name)
        if hasattr(module, 'skip'):
            continue
        if hasattr(module, 'plot'):
            canvas_app.add_canvas(module.plot())
    canvas_app.show()
