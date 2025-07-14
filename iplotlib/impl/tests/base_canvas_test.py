# iplotlib/impl/tests/base_canvas_test.py

from iplotlib.qt.testing.qAppTestAdapter import QAppTestAdapter

# Module‐level cache of one QtCanvas instance
_qt_canvas = None

class BaseCanvasTest(QAppTestAdapter):
    """
    Mixin that starts a single QApplication and reuses
    one QtCanvas instance across all tests.

    Subclasses must set `canvas_class` to the QtCanvas type.
    """
    canvas_class = None

    def setUp(self):
        """
        Ensure a single canvas is created only once and available as self.canvas.
        """
        global _qt_canvas
        super().setUp()
        # create the canvas singleton if it does not exist
        if _qt_canvas is None and not self.headless():
            _qt_canvas = self.canvas_class()
            _qt_canvas.setFixedSize(800, 800)
        # assign the shared canvas to this test instance
        self.canvas = _qt_canvas

    def headless(self):
        """
        Override default headless behavior: always run with a display.
        """
        return False

    def tearDown(self):
        """
        Hide and delete the reference after each test, then tear down the app.
        """
        if not self.headless():
            try:
                # hide the widget between tests
                self.canvas.hide()
            except Exception:
                pass
            # remove this instance’s reference
            del self.canvas
        super().tearDown()
