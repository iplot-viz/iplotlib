# Description: Sets up an application ready for testing in offscreen mode (headless CI).

from iplotlib.qt.testing import QAppTestAdapter, ensure_qapp


class QAppOffscreenTestAdapter(QAppTestAdapter):
    """Helper class to provide QApplication instances for headless testing"""

    qapplication = True

    def setUp(self):
        """Creates (or reuses) the QApplication instance in offscreen mode."""
        super().setUp()
        self.app = ensure_qapp()

    def tearDown(self):
        """Deletes the reference owned by self"""
        del self.app
        super().tearDown()
