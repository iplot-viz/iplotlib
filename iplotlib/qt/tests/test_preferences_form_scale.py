# Description: The preferences forms show sizes as rendered and store them unscaled.

import unittest

from PySide6.QtCore import QModelIndex

from iplotlib.core import Canvas
from iplotlib.core.display import DisplayScale, MODE_FIXED
from iplotlib.impl.matplotlib.tests.QAppOffscreenTestAdapter import QAppOffscreenTestAdapter
from iplotlib.qt.gui.forms.plotting.canvasForm import CanvasForm
from iplotlib.qt.models import BeanItem
from iplotlib.qt.models.beanItemModel import BeanItemModel


class PreferencesFormScaleTests(QAppOffscreenTestAdapter):
    """The form shows the size the user sees on this display, while the
    canvas keeps the configured value: submitting an untouched form must not
    grow anything, and an edited size is stored so that it renders as typed."""

    def setUp(self):
        super().setUp()
        DisplayScale.reset()
        self._configure(2.0)
        self.canvas = Canvas(font_size=8)
        self.form = CanvasForm()
        self.form.widgetModel.setData(QModelIndex(), self.canvas, BeanItemModel.PyObjectRole)
        self.form.widgetMapper.toFirst()

    def tearDown(self):
        DisplayScale.reset()
        super().tearDown()

    @staticmethod
    def _configure(factor):
        DisplayScale.instance().configure(mode=MODE_FIXED, value=factor, force=True)

    def _widget(self, property_name):
        model = self.form.widgetModel
        for column in range(model.columnCount()):
            item = model.item(0, column)
            if item.data(BeanItem.PropertyRole) == property_name:
                return item.data(BeanItem.WidgetRole)
        raise AssertionError(f"no widget for {property_name}")

    def test_form_shows_the_rendered_font_size(self):
        self.assertEqual(self._widget('font_size').value(), 16)

    def test_untouched_submit_keeps_the_configured_font_size(self):
        self.form.widgetMapper.submit()
        self.assertEqual(self.canvas.font_size, 8)
        self.assertEqual(self.form._pm.get_value(self.canvas, 'font_size'), 16)

    def test_an_edited_size_is_stored_unscaled_and_renders_as_typed(self):
        self._widget('font_size').setValue(20)
        self.form.widgetMapper.submit()
        self.assertEqual(self.canvas.font_size, 10)
        self.assertEqual(self.form._pm.get_value(self.canvas, 'font_size'), 20)
        self.form.widgetMapper.toFirst()
        self.assertEqual(self._widget('font_size').value(), 20)

    def test_a_fractional_factor_does_not_drift_an_untouched_size(self):
        # 9 x 1.75 shows as 16; writing 16 / 1.75 back would turn 9 into 9.14.
        self._configure(1.75)
        self.canvas.font_size = 9
        self.form.widgetMapper.toFirst()
        self.assertEqual(self._widget('font_size').value(), 16)
        self.form.widgetMapper.submit()
        self.assertEqual(self.canvas.font_size, 9)


if __name__ == '__main__':
    unittest.main()
