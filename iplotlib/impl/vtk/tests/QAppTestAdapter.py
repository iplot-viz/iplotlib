import unittest

from qtpy.QtWidgets import QApplication
from iplotlib.impl.vtk.qt import QtVTKCanvas
from iplotlib.impl.vtk.tests.vtk_hints import vtk_is_headless
_instance = None
_qvtk_canvas = None

class QAppTestAdapter(unittest.TestCase):
    """Helper class to provide QApplication instances"""

    qapplication = True

    def setUp(self):
        """Creates the QApplication instance"""

        # Simple way of making instance a singleton
        super(QAppTestAdapter, self).setUp()
        global _instance, _qvtk_canvas
        if _instance is None and not vtk_is_headless():
            _instance = QApplication([])
        if _qvtk_canvas is None and not vtk_is_headless():
            _qvtk_canvas = QtVTKCanvas()
            _qvtk_canvas.setFixedSize(800, 800)

        self.app = _instance
        self.canvas = _qvtk_canvas


    def tearDown(self):
        """Deletes the reference owned by self"""
        if not vtk_is_headless():
            del self.canvas 
            del self.app
        super(QAppTestAdapter, self).tearDown()