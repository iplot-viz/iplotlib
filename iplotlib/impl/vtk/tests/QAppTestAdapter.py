import unittest

from qtpy.QtWidgets import QApplication
from iplotlib.impl.vtk.qt.qtVTKCanvas import QtVTKCanvas
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
        if _instance is None:
            _instance = QApplication([])
        if _qvtk_canvas is None:
            _qvtk_canvas = QtVTKCanvas()

        self.app = _instance
        self.canvas = _qvtk_canvas

    def tearDown(self):
        """Deletes the reference owned by self"""
        del self.canvas
        del self.app
        super(QAppTestAdapter, self).tearDown()