"""
Icon sizes that follow the application font.

Qt derives PM_ToolBarIconSize from the style and the screen's logical DPI, not
from the font, so it is a constant 24 logical pixels whatever size the text is.
On a session whose UI font has been enlarged for a high-resolution panel, the
labels grow and the icons do not: at 26pt the text is 40px tall next to a 24px
icon, and on a screen reporting 72 DPI that icon shrinks further to 18px.

Deriving the size from font metrics instead makes icons track the text at any
DPI, point size or scale factor, without depending on the session reporting a
sensible DPI.
"""

# Author: added for HiDPI/4K support

from PySide6.QtCore import QEvent, QSize

#: Icon edge as a multiple of the font height. A little larger than the text so
#: the icon reads as an icon rather than as a glyph beside it.
DEFAULT_ICON_FACTOR = 1.3
#: Never go below what the style would have chosen on an ordinary display.
MIN_ICON_PX = 16


def font_scaled_icon_size(widget, factor: float = DEFAULT_ICON_FACTOR) -> QSize:
    """An icon size proportional to ``widget``'s font height."""
    edge = max(MIN_ICON_PX, int(round(widget.fontMetrics().height() * factor)))
    return QSize(edge, edge)


class FontScaledIcons:
    """Mixin keeping a tool bar's icon size tied to the current font.

    Mix in *before* the Qt class so ``changeEvent`` resolves here first::

        class MyToolBar(FontScaledIcons, QToolBar):
            ...
            self.apply_icon_size()   # once the actions are added

    Note this sets the size Qt asks the QIcon for; whether the result is sharp
    depends on the icon having pixels at that resolution. The packaged bitmap
    sources are 18x18, so a large size will be an upscale until they are
    replaced with SVG or higher resolution exports.
    """

    ICON_FACTOR = DEFAULT_ICON_FACTOR

    def apply_icon_size(self):
        self.setIconSize(font_scaled_icon_size(self, self.ICON_FACTOR))

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.FontChange:
            self.apply_icon_size()
