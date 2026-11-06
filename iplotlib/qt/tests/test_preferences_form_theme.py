# Description: The preferences forms show the colours of the theme and store those configured.

import unittest

from PySide6.QtCore import QModelIndex
from PySide6.QtGui import QColor

from iplotlib.core import Canvas
from iplotlib.core import property_manager
from iplotlib.impl.matplotlib.tests.QAppOffscreenTestAdapter import QAppOffscreenTestAdapter
from iplotlib.qt.gui.forms.plotting.canvasForm import CanvasForm
from iplotlib.qt.models import BeanItem
from iplotlib.qt.models.beanItemModel import BeanItemModel


class PreferencesFormThemeTests(QAppOffscreenTestAdapter):
    """In a dark theme the form shows the colour the plots are drawn in, while the canvas keeps the configured one:
    submitting an untouched form must not store the colours of the theme, which would stay in another one."""

    def setUp(self):
        super().setUp()
        property_manager.set_theme_colors({'background_color': '#2d2d2d', 'font_color': '#ffffff'})
        self.addCleanup(property_manager.set_theme_colors, {})
        self.canvas = Canvas()
        self.form = CanvasForm()
        self.form.widgetModel.setData(QModelIndex(), self.canvas, BeanItemModel.PyObjectRole)
        self.form.widgetMapper.toFirst()

    def _widget(self, property_name):
        model = self.form.widgetModel
        for column in range(model.columnCount()):
            item = model.item(0, column)
            if item.data(BeanItem.PropertyRole) == property_name:
                return item.data(BeanItem.WidgetRole)
        raise AssertionError(f"no widget for {property_name}")

    def test_an_untouched_colour_keeps_its_configured_value(self):
        self.form.widgetMapper.submit()
        self.assertEqual(self.form._pm.get_raw_value(self.canvas, 'background_color').upper(), '#FFFFFF')
        self.assertEqual(self.form._pm.get_value(self.canvas, 'background_color'), '#2d2d2d')

    def test_an_edited_colour_is_stored_as_chosen(self):
        self._widget('background_color').colorDialog.setCurrentColor(QColor('#123456'))
        self.form.widgetMapper.submit()
        self.assertEqual(self.canvas.background_color.upper(), '#123456')
        self.assertEqual(self.form._pm.get_value(self.canvas, 'background_color').upper(), '#123456')


if __name__ == '__main__':
    unittest.main()
