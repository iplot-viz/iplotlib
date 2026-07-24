"""Tests for IplotQtCanvasToolbar — specifically the createPulseAction
that hosting applications can opt-in to (e.g. MINT when UDA write API
is available)."""
import unittest

from iplotlib.impl.matplotlib.tests.QAppOffscreenTestAdapter import QAppOffscreenTestAdapter
from iplotlib.qt.gui.iplotCanvasToolbar import IplotQtCanvasToolbar


class CreatePulseActionTests(QAppOffscreenTestAdapter):
    def setUp(self):
        super().setUp()
        self.toolbar = IplotQtCanvasToolbar()

    def tearDown(self):
        self.toolbar.deleteLater()
        super().tearDown()

    def test_action_exists(self):
        self.assertTrue(hasattr(self.toolbar, "createPulseAction"))

    def test_action_hidden_by_default(self):
        # Host app decides visibility based on data-source capabilities.
        self.assertFalse(self.toolbar.createPulseAction.isVisible())

    def test_action_has_user_facing_text_and_tooltip(self):
        self.assertIn("Create Pulse", self.toolbar.createPulseAction.text())
        self.assertTrue(self.toolbar.createPulseAction.statusTip())

    def test_action_can_be_made_visible(self):
        self.toolbar.show()
        self.toolbar.createPulseAction.setVisible(True)
        self.assertTrue(self.toolbar.createPulseAction.isVisible())

    def test_action_triggers_signal(self):
        received = []
        self.toolbar.createPulseAction.triggered.connect(lambda: received.append(True))
        self.toolbar.createPulseAction.trigger()
        self.assertEqual(received, [True])


if __name__ == "__main__":
    unittest.main()
