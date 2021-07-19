import sys

from qtpy.QtCore import Qt
from qtpy.QtWidgets import QApplication, QMainWindow

import iplotLogging.setupLogger as ls
from iplotlib.qt.qtCanvasToolbar import CanvasToolbar

logger = ls.get_logger(__name__)


class QStandaloneCanvas:
    """A standalone canvas that is itself a Qt application that can be shown using the run method,
    separate class is needed for this since instantiating anything that extends QObject is not
    possible without instantiating a QApplication first"""

    impl_registry = dict()

    @staticmethod
    def register_implementation(impl_type, impl_alias):
        logger.info(F"Registering implementation {impl_type} as '{impl_alias}'")
        QStandaloneCanvas.impl_registry[impl_alias] = impl_type

    def __init__(self, impl_name=None, canvas=None, toolbar=True):
        super().__init__()
        self.implementation = impl_name
        self.canvas = canvas
        self.toolbar = toolbar
        self.impl = None
        self.qt_app = None
        self.qt_main_widget = None

    def prepare(self, canvas=None):
        """Prepares qt canvas but does not show it not to block the main thread
        Therefore after calling prepare() the developer can access qt_app/qt_canvas/qt_main_widget variables"""

        if canvas is not None:
            self.canvas = canvas

        widget_impl = self.impl_registry.get(self.implementation)
        if widget_impl:
            QApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
            self.qt_app = QApplication(sys.argv)
            self.qt_main_widget = QMainWindow()
            self.impl = widget_impl(canvas=self.canvas)
            if self.toolbar:
                self.qt_main_widget.addToolBar(CanvasToolbar(qt_canvas=self.impl))
            self.qt_main_widget.setCentralWidget(self.impl)

        else:
            logger.error(F"No implementation found for string '{self.implementation}'. Available implementations: {self.impl_registry}")

    def show(self):
        """Shows the qt canvas on the screen. Calls prepare() if it was not called before"""
        if self.qt_app is None:
            self.prepare()
        self.qt_main_widget.show()
        sys.exit(self.qt_app.exec_())


try:
    from iplotlib.impl.matplotlib.qt.qtMatplotlibCanvas import QtMatplotlibCanvas

    QStandaloneCanvas.register_implementation(QtMatplotlibCanvas, "MATPLOTLIB")
except ModuleNotFoundError:
    logger.error("No matplotlib canvas implementation found")
