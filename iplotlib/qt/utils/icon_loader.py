# Description: A helpful icon loader.
# Author: Jaswant Sai Panchumarti

import pkgutil

from PySide2.QtGui import QPixmap, QIcon


def create_icon(name) -> QIcon:
    pxmap = QPixmap()
    pxmap.loadFromData(pkgutil.get_data("iplotlib.qt", f"icons/{name}.png"))
    return QIcon(pxmap)
