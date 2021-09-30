# Description: Stubs for signal.
# Author: Jaswant Sai Panchumarti

import typing

from PySide2.QtCore import Qt
from PySide2.QtGui import QStandardItem

class SignalItem(QStandardItem):
    def __init__(self, text: str):
        super().__init__(text)

    def setData(self, value: typing.Any, role: int = Qt.UserRole):
        super().setData(value, role=role)