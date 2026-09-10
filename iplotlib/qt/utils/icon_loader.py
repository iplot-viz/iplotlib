"""
A helpful icon loader.
"""

# Author: Jaswant Sai Panchumarti
# Changelog:
#   HiDPI: render SVG sources at several sizes and tag bitmap sources with the
#          device pixel ratio, so toolbar icons stay sharp on a 4K panel.

import pkgutil

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QGuiApplication, QIcon, QPainter, QPixmap

#: Logical sizes rendered from an SVG source. Covers 1x/1.5x/2x/3x of the 16-24
#: px range Qt asks for in tool bars and menus.
_SVG_RENDER_SIZES = (16, 24, 32, 48, 64)


def _device_pixel_ratio() -> float:
    if QGuiApplication.instance() is None:
        return 1.0
    screen = QGuiApplication.primaryScreen()
    return float(screen.devicePixelRatio()) if screen is not None else 1.0


def _icon_from_svg(data: bytes) -> QIcon:
    try:
        from PySide6.QtSvg import QSvgRenderer
    except ImportError:
        pxmap = QPixmap()
        pxmap.loadFromData(QByteArray(data), 'svg')
        return QIcon(pxmap)

    renderer = QSvgRenderer(QByteArray(data))
    icon = QIcon()
    for size in _SVG_RENDER_SIZES:
        pxmap = QPixmap(size, size)
        pxmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pxmap)
        renderer.render(painter, QRectF(0, 0, size, size))
        painter.end()
        icon.addPixmap(pxmap)
    return icon


def create_icon(name, ext: str = 'png') -> QIcon:
    """Load a packaged icon as a QIcon.

    An SVG source is rendered at a range of sizes so Qt can pick the one closest
    to what it needs instead of scaling a single rasterisation. A bitmap source
    gets its device pixel ratio tagged: without it Qt reads an 18x18 PNG as 18
    *logical* pixels and upscales it to 36 device pixels on a 200% display,
    which is what makes the tool bar look soft there.
    """
    data = pkgutil.get_data("iplotlib.qt", f"icons/{name}.{ext}")
    if ext.lower() == 'svg':
        return _icon_from_svg(data)

    pxmap = QPixmap()
    pxmap.loadFromData(QByteArray(data))
    ratio = _device_pixel_ratio()
    if ratio > 1.0:
        pxmap.setDevicePixelRatio(ratio)
    return QIcon(pxmap)
