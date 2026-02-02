# Description: Sets up an application ready for testing in offscreen mode (headless CI).
# Author: Based on mint/tests/QAppOffscreenTestAdapter.py

from PySide6.QtWidgets import QApplication
from iplotlib.qt.testing import QAppTestAdapter

_instance = None


class QAppOffscreenTestAdapter(QAppTestAdapter):
    """Helper class to provide QApplication instances for headless testing"""

    qapplication = True

    def setUp(self):
        """Creates the QApplication instance in offscreen mode"""

        # Simple way of making instance a singleton
        super().setUp()
        global _instance
        if _instance is None:
            _instance = QApplication(['QAppOffscreenTestAdapter', '-platform', 'offscreen'])

        self.app = _instance

    def tearDown(self):
        """Deletes the reference owned by self"""
        del self.app
        super().tearDown()
