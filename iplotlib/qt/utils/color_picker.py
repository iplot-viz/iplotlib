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
A color dialog box.
"""
import logging
import iplotlib.qt.utils.color_constants as cc

# Author: Piotr Mazur
# Changelog:
#   Sept 2021: -Refactor qt classes [Jaswant Sai Panchumarti]
#              -Port to PySide2 [Jaswant Sai Panchumarti]


from PySide6.QtCore import QMargins, QEvent, Qt, Property
from PySide6.QtGui import QColor, QKeyEvent
from PySide6.QtWidgets import QApplication, QColorDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QWidget


class ColorPicker(QWidget):
    """
    A color dialog box.
    """

    def __init__(self, name_property):
        super().__init__()
        self.setLayout(QHBoxLayout())
        self.layout().setContentsMargins(QMargins())

        self.name = name_property

        self.selectButton = QPushButton("Select color", self)
        self.selectButton.clicked.connect(self.openColorDialog)

        self.colorWindow = QLabel('', self)
        self.colorWindow.setFrameShape(QFrame.Shape.StyledPanel)
        self.colorWindow.setFrameShadow(QFrame.Shadow.Raised)
        self.colorWindow.setFixedWidth(40)
        self.colorWindow.setFixedHeight(40)
        self.layout().addWidget(self.selectButton)
        self.layout().addWidget(self.colorWindow)

        self.colorDialog = QColorDialog(self)
        self.colorDialog.currentColorChanged.connect(self.indicateColorChange)
        self._rgbValue = None
        self.is_initial_color_set = False
        self._fromParentUpdate = False

    def openColorDialog(self):
        self.colorDialog.show()

    def indicateColorChange(self, color: QColor):
        self._rgbValue = '#{:02X}{:02X}{:02X}'.format(color.red(), color.green(), color.blue())
        self.colorWindow.setStyleSheet("background-color: {}".format(self._rgbValue))

        if not self._fromParentUpdate:
            QApplication.postEvent(self, QKeyEvent(QEvent.KeyPress, Qt.Key_Enter, Qt.NoModifier))

    def current_color(self) -> str:
        return self._rgbValue

    def setCurrentColor(self, color):
        if not self.is_initial_color_set:
            self.is_initial_color_set = True  # Disables the call at startup
            return
        self._fromParentUpdate = True
        try:
            if not isinstance(color, str):
                color = "#000000"
            if len(color) and color[0] != "#":
                color = cc.name_to_hex(color)
            if not len(color) or color is None:
                logging.warning("Received color='%s' for color_picker has a wrong format. Setting default color", color)
                if self.name == "crosshair_color":
                    color = "#ff0000"
                elif self.name == "font_color":
                    color = "#000000"
                elif self.name == "background_color":
                    color = "#FFFFFF"  # Default color for background of plot will be white
                else:
                    color = "#000000"
            if color[0] == "#" and len(color) == 7:
                r, g, b = tuple(int(color[i:i + 2], 16) for i in range(1, 7, 2))
                self.colorDialog.setCurrentColor(QColor(r, g, b))
            else:
                return self.indicateColorChange(self.colorDialog.currentColor())
        finally:
            self._fromParentUpdate = False

    currentColor = Property(str, current_color, setCurrentColor, user=True)
