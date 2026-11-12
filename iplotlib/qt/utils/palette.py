"""
The colours that the canvases take from the application palette: in a dark one they draw in its colours what they
draw in black and white in a light one.
"""

from typing import Optional

from PySide6.QtGui import QColor, QGuiApplication, QPalette


def is_dark(palette: Optional[QPalette] = None) -> bool:
    """Whether a palette, the application's by default, draws light text on a dark window."""
    palette = QGuiApplication.palette() if palette is None else palette
    return (palette.color(QPalette.ColorRole.Window).lightness()
            < palette.color(QPalette.ColorRole.WindowText).lightness())


def blend(a, b, t: float) -> QColor:
    """The colour a fraction `t` of the way from colour `a` to colour `b`."""
    a, b = QColor(a), QColor(b)
    return QColor.fromRgbF(*(x + (y - x) * t for x, y in zip(a.getRgbF()[:3], b.getRgbF()[:3])))


def theme_colors() -> Optional[dict]:
    """The colours that the canvases draw with in a dark application palette, None in a light one: the background of
    the plots and their text, the grid and frames, the background of the mini-map and the grey of the icons."""
    if QGuiApplication.instance() is None or not is_dark():
        return None
    palette = QGuiApplication.palette()
    base, text = palette.color(QPalette.ColorRole.Base), palette.color(QPalette.ColorRole.Text)
    return {'background': base.name(),
            'text': text.name(),
            # The grid and frames contrast 3:1 with the background, as WCAG AA asks of lines.
            'grid': blend(base, text, 0.35).name(),
            # As a light mini-map is to white.
            'minimap': blend(base, text, 0.04).name(),
            'icon': blend(palette.color(QPalette.ColorRole.Window),
                          palette.color(QPalette.ColorRole.WindowText), 0.8).name()}
