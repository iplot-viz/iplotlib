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
A helpful icon loader.
"""

# Author: Jaswant Sai Panchumarti

import pkgutil

from PySide6.QtGui import QPixmap, QIcon


def create_icon(name, ext: str = 'png') -> QIcon:
    pxmap = QPixmap()
    pxmap.loadFromData(pkgutil.get_data("iplotlib.qt", f"icons/{name}.{ext}"))
    return QIcon(pxmap)
