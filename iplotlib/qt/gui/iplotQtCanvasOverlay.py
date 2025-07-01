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
from PySide6 import QtCore
from PySide6.QtCore import *
from PySide6.QtGui import *
from PySide6.QtWidgets import *
from iplotlib.qt.gui.iplotOverlayCanvasTool import QtOverlayCanvasTool


class QtCanvasOverlay(QWidget):
    """
    This class represents an overlay layer that is put on plot canvas
    Additional objects such as crosshair are drawn on this overlay
    """

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.dependentOverlays = []
        self.activeTool: QtOverlayCanvasTool = None
        self.setMouseTracking(True)
        self.installEventFilter(self)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setGeometry(0, 0, self.parent().geometry().width(), self.parent().geometry().height())
        self.setFocusPolicy(Qt.StrongFocus)

    def activate_tool(self, tool: QtOverlayCanvasTool):
        self.activeTool = tool

    def paintEvent(self, e):
        self.setGeometry(0, 0, self.parent().geometry().width(), self.parent().geometry().height())
        # TODO: Can actually be done only on resize, not needed for every paint

        if self.activeTool is not None:
            self.activeTool.process_paint(self.parent(), QPainter(self))
            for overlay in self.dependentOverlays:
                if overlay is not self:
                    overlay.update()
            pass

    def eventFilter(self, source, event):
        # print("E" + str(event) + " type: " + str(event.type())  + " vs: " + str(QtGui.QKeyEvent))

        if event.type() == QtCore.QEvent.KeyPress:
            if event.text() == 'p':
                self.parent()._gnuplot_canvas.prev()
            elif event.text() == 'n':
                self.parent()._gnuplot_canvas.next()

        if self.activeTool is not None:
            if self.activeTool.process_event(self.parent(), event):
                self.update()

        return False
