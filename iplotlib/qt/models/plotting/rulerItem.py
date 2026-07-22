"""Tree item for a Ruler in the Preferences window."""

import typing

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QColor, QIcon, QPixmap, QStandardItem


class RulerItem(QStandardItem):
    def __init__(self, text: str, auto_name: bool = False):
        super().__init__(text)
        self.auto_name = auto_name

    def setData(self, value: typing.Any, role: int = Qt.ItemDataRole.UserRole):
        super().setData(value, role=role)
        if role == Qt.ItemDataRole.UserRole and hasattr(value, 'color') and value.color:
            pixmap = QPixmap(QSize(12, 12))
            pixmap.fill(QColor(value.color))
            self.setIcon(QIcon(pixmap))
