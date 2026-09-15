"""Tool bar icons must follow the application font, not the screen DPI."""

import unittest

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QToolBar

from iplotlib.qt.utils.icon_sizing import (MIN_ICON_PX, FontScaledIcons,
                                           font_scaled_icon_size)


class ScaledToolBar(FontScaledIcons, QToolBar):
    def __init__(self):
        QToolBar.__init__(self)
        self.apply_icon_size()


class IconSizingTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self._font = self.app.font()

    def tearDown(self):
        self.app.setFont(self._font)

    def test_icon_size_tracks_the_font(self):
        tb = ScaledToolBar()
        small = tb.iconSize().width()
        font = tb.font()
        font.setPointSizeF(font.pointSizeF() * 2.5)
        tb.setFont(font)
        self.app.processEvents()
        self.assertGreater(tb.iconSize().width(), small)

    def test_icon_is_at_least_as_tall_as_the_text(self):
        # The regression: at 26pt the style still asked for 24px icons.
        tb = ScaledToolBar()
        font = QFont(tb.font())
        font.setPointSizeF(26.0)
        tb.setFont(font)
        self.app.processEvents()
        self.assertGreaterEqual(tb.iconSize().height(), tb.fontMetrics().height())

    def test_never_smaller_than_the_ordinary_default(self):
        tb = ScaledToolBar()
        font = QFont(tb.font())
        font.setPointSizeF(4.0)
        tb.setFont(font)
        self.app.processEvents()
        self.assertGreaterEqual(tb.iconSize().width(), MIN_ICON_PX)

    def test_helper_is_square(self):
        tb = ScaledToolBar()
        size = font_scaled_icon_size(tb)
        self.assertEqual(size.width(), size.height())


if __name__ == '__main__':
    unittest.main()
