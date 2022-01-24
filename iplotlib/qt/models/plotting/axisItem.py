"""
Stubs for an axis.
"""

# Author: Jaswant Sai Panchumarti

import typing

from PySide2.QtCore import Qt
from PySide2.QtGui import QStandardItem


class AxisItem(QStandardItem):
    def __init__(self, text: str, auto_name=False):
        super().__init__(text)
        self.auto_name = auto_name

    def setData(self, value: typing.Any, role: int = Qt.UserRole):
        return super().setData(value, role=role)