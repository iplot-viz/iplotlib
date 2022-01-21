# Description: Sets up a Qt application ready for testing.
# Author: Jaswant Sai Panchumarti

import unittest

from PySide2.QtWidgets import QApplication
_instance = None

class QAppTestAdapter(unittest.TestCase):
    """Helper class to provide QApplication instances"""

    qapplication = True

    def setUp(self):
        """Creates the QApplication instance"""

        # Simple way of making instance a singleton
        super().setUp()
        global _instance, _qvtk_canvas
        if _instance is None and not self.headless():
            _instance = QApplication([])

        self.app = _instance

    def headless(self):
        return True

    def tearDown(self):
        """Deletes the reference owned by self"""
        if not self.headless():
            del self.app
        super().tearDown()