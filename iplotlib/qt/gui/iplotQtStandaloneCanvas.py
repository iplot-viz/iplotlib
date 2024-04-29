"""
A standalone iplotlib Qt Canvas. It is useful to test preferences-window, toolbar among other things.
"""

# Author: Piotr Mazur
# Changelog:
#   Sept 2021: -Refactor qt classes [Jaswant Sai Panchumarti]
#              -Port to PySide2 [Jaswant Sai Panchumarti]
#              -Register VTK canvas.


from functools import partial
import importlib
import pkgutil
import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import (QGuiApplication, QKeySequence,
                           QAction, QActionGroup)

from iplotlib.core import Canvas
from iplotlib import examples as iplotExamples
from iplotlib.interface.iplotSignalAdapter import AccessHelper
from iplotlib.qt.gui.iplotQtCanvasFactory import IplotQtCanvasFactory
from iplotlib.qt.gui.iplotQtMainWindow import IplotQtMainWindow

import iplotLogging.setupLogger as Sl

logger = Sl.get_logger(__name__)


class QStandaloneCanvas:
    """
    A standalone canvas that is itself a Qt application that can be shown using the 
    :data:`~iplotlib.qt.iplotQtStandaloneCanvas.QStandaloneCanvas.run()` method.
    A Separate class is justified because instantiating `QObject` derived objects is not
    possible without instantiating a `QApplication`.
    """

    def __init__(self, impl_name=None, use_toolbar=True):
        super().__init__()
        self.impl_name = impl_name
        self.use_toolbar = use_toolbar
        self.app = None
        self.main_window = None

    def prepare(self, argv=sys.argv):
        """
        Prepares :data:~`iplotlib.qt.gui.iplotQtMainWindow.IplotQtMainWindow` but does not show it 
        to avoid blocking the main thread.
        
        Therefore after calling prepare() the developer can access app/main_window variables
        and add canvases.
        """

        QApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
        self.app = QApplication(argv)
        self.main_window = IplotQtMainWindow(show_toolbar=self.use_toolbar)
        self.fileMenu = self.main_window.menuBar().addMenu('&File')
        self.selectMenu = self.main_window.menuBar().addMenu('&Canvases')

        exit_action = QAction("Exit", self.main_window.menuBar())
        exit_action.setShortcuts(QKeySequence.Quit)
        exit_action.triggered.connect(QApplication.quit)

        self.fileMenu.addAction(exit_action)
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
        """
        Add the given abstract iplotlib canvas to the main window.
        """
        if not self.main_window:
            logger.warning("Not yet. Please prepare the Qt application. Call 'prepare'")
            return

        qt_canvas = IplotQtCanvasFactory.new(self.impl_name, parent=self.main_window, canvas=canvas)
        canvasIdx = self.main_window.canvasStack.count()
        self.main_window.canvasStack.addWidget(qt_canvas)

        act = QAction(str(canvasIdx + 1).zfill(2) + '-' + canvas.title, self.main_window)
        act.setCheckable(True)
        act.triggered.connect(partial(self.main_window.canvasStack.setCurrentIndex, canvasIdx))
        self.canvasActionGroup.addAction(act)
        self.selectMenu.addAction(act)

    def show(self):
        """
        Shows the qt window on the screen.
        If the event loop is not running, the window will be unresponsive.
        Calls prepare() if it was not called before
        """
        if self.app is None:
            self.prepare()

        # select the first canvas
        firstAct = self.canvasActionGroup.actions()[0]
        firstAct.trigger()
        self.main_window.resize(1920, 1080)
        self.main_window.show()

    def run(self) -> int:
        """
        Show the main window and run the event loop.
        """
        if self.app is None:
            self.prepare()
        self.show()
        logger.warning('The main thread is now blocked. You can no longer add canvases.')
        return self.app.exec_()


args = None


def proxy_main():
    """
    The real main function.
    """
    global args
    AccessHelper.num_samples_override = args.use_fallback_samples
    canvas_app = QStandaloneCanvas(args.impl, use_toolbar=True)
    canvas_app.prepare()

    for script in pkgutil.walk_packages(iplotExamples.__path__, iplotExamples.__name__ + '.'):
        module = importlib.import_module(script.name)
        if hasattr(module, 'skip'):
            continue
        if hasattr(module, 'plot'):
            canvas_app.add_canvas(module.plot())
    canvas_app.show()
    return canvas_app.run()


def main():
    """
    Calls proxy main inside a profiling context if profiler is enabled.
    """
    global args
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        '-impl', dest='impl', help="Specify a graphics backend.", default='matplotlib')
    parser.add_argument('-t', dest='toolbar', help="Place a toolbar with canvas specific actions on the top.",
                        action='store_true', default=False)
    parser.add_argument('-use-fallback-samples', dest='use_fallback_samples', action='store_true', default=False)
    parser.add_argument('-profile', dest='use_profiler', action='store_true', default=False)
    args = parser.parse_args()

    if args.use_profiler:
        import cProfile, pstats
        cProfile.runctx("proxy_main()", globals(), locals(), "{}.profile".format(__file__))
        s = pstats.Stats("{}.profile".format(__file__))
        s.strip_dirs()
        s.sort_stats("time").print_stats(10)
    else:
        sys.exit(proxy_main())


if __name__ == '__main__':
    main()
