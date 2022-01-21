# Description: Sets up a Qt application ready to test with a QtVTKCanvas.
# Author: Jaswant Sai Panchumarti
# Changelog:
#   Sept 2021: -Port to PySide2

from iplotlib.impl.vtk.qt import QtVTKCanvas
from iplotlib.qt.testing import QAppTestAdapter
from iplotlib.impl.vtk.tests.vtk_hints import vtk_is_headless
_instance = None
_qvtk_canvas = None

class QVTKAppTestAdapter(QAppTestAdapter):
    """Helper class to provide QApplication instances"""

    qapplication = True

    def setUp(self):
        """Creates the QApplication instance"""

        # Simple way of making instance a singleton
        global _instance, _qvtk_canvas
        super().setUp()
        if _qvtk_canvas is None and not self.headless():
            _qvtk_canvas = QtVTKCanvas()
            _qvtk_canvas.setFixedSize(800, 800)

        self.canvas = _qvtk_canvas

    def headless(self):
        return vtk_is_headless()

    def tearDown(self):
        """Deletes the reference owned by self"""
        if not self.headless():
            self.canvas.hide()
            del self.canvas 
        super().tearDown()