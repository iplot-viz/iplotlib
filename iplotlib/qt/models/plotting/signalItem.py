# Copyright (c) 2020-2025 ITER Organization,
#               CS 90046
#               13067 St Paul Lez Durance Cedex
#               France
# Author IO
#
# This file is part of iplotlib module.
# iplotlib python module is free software: you can redistribute it and/or modify it under
# the terms of the MIT license.
#
# This file is part of ITER CODAC software.
# For the terms and conditions of redistribution or use of this software
# refer to the file LICENSE located in the top level directory
# of the distribution package
#


"""
Stubs for signal.
"""

# Author: Jaswant Sai Panchumarti

import typing

from PySide6.QtCore import Qt
from PySide6.QtGui import QStandardItem


class SignalItem(QStandardItem):
    def __init__(self, text: str, auto_name=False):
        super().__init__(text)
        self.auto_name = auto_name

    def setData(self, value: typing.Any, role: int = Qt.UserRole):
        super().setData(value, role=role)
