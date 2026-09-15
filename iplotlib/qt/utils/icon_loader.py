"""
A helpful icon loader.
"""

# Author: Jaswant Sai Panchumarti
# Changelog:
#   HiDPI: render SVG sources at several sizes so toolbar icons stay sharp on a
#          4K panel. Bitmap sources are returned untagged, see create_icon.

import pkgutil

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap

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
    to what it needs instead of scaling a single rasterisation. Bitmap sources
    are returned as-is; see the comment below for why they are not tagged with
    the device pixel ratio.
    """
    data = pkgutil.get_data("iplotlib.qt", f"icons/{name}.{ext}")
    if ext.lower() == 'svg':
        return _icon_from_svg(data)

    # Deliberately left untagged. Setting a device pixel ratio on a single
    # resolution bitmap does not add detail: it relabels an 18x18 image as
    # ~10 logical pixels, so the icon is drawn smaller rather than sharper, and
    # it makes the icon's logical size depend on the screen, which upsets styles
    # that lay out icon columns (menus in particular). Sharp bitmap icons need
    # higher resolution sources, not a different label on the same pixels.
    pxmap = QPixmap()
    pxmap.loadFromData(QByteArray(data))
    return QIcon(pxmap)
