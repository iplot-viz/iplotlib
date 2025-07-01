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
This module is deprecated and unused.
"""
from PySide6.QtCore import QObject
from PySide6.QtGui import QPainter

"""
This abstract class represents a canvas tool, usually interacts with events such as keyboard or mouse
TODO: Is it possible to make this independent from widget library?
TODO: Tools should redraw when size of the canvas changes in order to reflect range changes
"""


class QtOverlayCanvasTool(QObject):

    def __init__(self):
        super().__init__()

    def process_paint(self, widget, painter: QPainter):
        pass

    def process_event(self, widget, event):
        pass

    def __repr__(self):
        return type(self).__class__.__name__
