# Description: The preferences forms must show and store unscaled sizes.

import unittest

from PySide6.QtCore import QModelIndex

from iplotlib.core import Canvas
from iplotlib.core.display import DisplayScale, MODE_FIXED
from iplotlib.impl.matplotlib.tests.QAppOffscreenTestAdapter import QAppOffscreenTestAdapter
from iplotlib.qt.gui.forms.plotting.canvasForm import CanvasForm
from iplotlib.qt.models import BeanItem
from iplotlib.qt.models.beanItemModel import BeanItemModel


class PreferencesFormScaleTests(QAppOffscreenTestAdapter):
    """A display scale changes what is rendered, never what the user edits:
    the form shows the configured size and submitting it back must not grow
    the canvas."""

    def setUp(self):
        super().setUp()
        DisplayScale.reset()
        DisplayScale.instance().configure(mode=MODE_FIXED, value=2.0, force=True)
        self.canvas = Canvas(font_size=8)
        self.form = CanvasForm()
        self.form.widgetModel.setData(QModelIndex(), self.canvas, BeanItemModel.PyObjectRole)
        self.form.widgetMapper.toFirst()

    def tearDown(self):
        DisplayScale.reset()
        super().tearDown()

    def _widget(self, property_name):
        model = self.form.widgetModel
        for column in range(model.columnCount()):
            item = model.item(0, column)
            if item.data(BeanItem.PropertyRole) == property_name:
                return item.data(BeanItem.WidgetRole)
        raise AssertionError(f"no widget for {property_name}")

    def test_form_shows_the_configured_font_size(self):
        self.assertEqual(self._widget('font_size').value(), 8)

    def test_submit_keeps_the_configured_font_size(self):
        self.form.widgetMapper.submit()
        self.assertEqual(self.canvas.font_size, 8)
        self.assertEqual(self.form._pm.get_value(self.canvas, 'font_size'), 16)
