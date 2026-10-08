"""
A helpful icon loader.
"""

# Author: Jaswant Sai Panchumarti

import pkgutil

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QIcon, QImage, QPainter, QPixmap

#: Logical sizes rendered from an SVG source. Covers 1x/1.5x/2x/3x of the 16-24
#: px range Qt asks for in tool bars and menus.
_SVG_RENDER_SIZES = (16, 24, 32, 48, 64)


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
    is loaded as is: tagging it with the device pixel ratio adds no detail, it
    only relabels an 18x18 image as fewer logical pixels, so the icon is drawn
    smaller rather than sharper.
    """
    data = pkgutil.get_data("iplotlib.qt", f"icons/{name}.{ext}")
    if ext.lower() == 'svg':
        return _icon_from_svg(data)

    pxmap = QPixmap()
    pxmap.loadFromData(QByteArray(data))
    return QIcon(pxmap)


def svg_icon_image(name: str, size: int) -> QImage:
    """A packaged SVG icon drawn on a transparent `size` x `size` pixel image, for
    canvases that draw icons themselves rather than through a QIcon."""
    from PySide6.QtSvg import QSvgRenderer

    image = QImage(size, size, QImage.Format.Format_RGBA8888)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    QSvgRenderer(QByteArray(pkgutil.get_data("iplotlib.qt", f"icons/{name}.svg"))).render(
        painter, QRectF(0, 0, size, size))
    painter.end()
    return image
