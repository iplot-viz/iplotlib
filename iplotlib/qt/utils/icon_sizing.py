"""
Icon sizes that follow the application font.

Qt sizes tool bar icons from the style and the screen DPI, never from the
font: enlarge the UI font and the labels grow while the icons stay at 24
logical pixels. Deriving the size from the font metrics keeps them in step at
any DPI, point size or scale factor.
"""

from PySide6.QtCore import QEvent, QSize

#: Icon edge as a multiple of the font height, a little larger than the text
#: so the icon reads as an icon rather than as a glyph beside it.
DEFAULT_ICON_FACTOR = 1.3
#: Floor for tiny fonts.
MIN_ICON_PX = 16


def font_scaled_icon_size(widget, factor: float = DEFAULT_ICON_FACTOR) -> QSize:
    """An icon size proportional to ``widget``'s font height."""
    edge = max(MIN_ICON_PX, int(round(widget.fontMetrics().height() * factor)))
    return QSize(edge, edge)


class FontScaledIcons:
    """Mixin keeping a tool bar's icon size tied to its font.

    Mix in before the Qt class so ``changeEvent`` resolves here first, and
    call ``apply_icon_size`` once the widget is constructed. The size is what
    Qt asks the QIcon for: an 18x18 bitmap source is upscaled beyond that.
    """

    ICON_FACTOR = DEFAULT_ICON_FACTOR

    def apply_icon_size(self):
        self.setIconSize(font_scaled_icon_size(self, self.ICON_FACTOR))

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.FontChange:
            self.apply_icon_size()
