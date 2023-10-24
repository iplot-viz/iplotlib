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

        # TODO: Find out if this button can be replaced with a colored box.
        self.selectButton = QPushButton("Select color", self)
        self.selectButton.clicked.connect(self.openColorDialog)

        self.colorWindow = QLabel('', self)
        self.colorWindow.setFrameShape(QFrame.StyledPanel)
        self.colorWindow.setFrameShadow(QFrame.Raised)
        self.colorWindow.setFixedWidth(40)
        self.colorWindow.setFixedHeight(40)
        self.layout().addWidget(self.selectButton)
        self.layout().addWidget(self.colorWindow)
        
        self.colorDialog = QColorDialog(self)
        self.colorDialog.currentColorChanged.connect(self.indicateColorChange)
        self._rgbValue = '#FFFFFF'

    def openColorDialog(self):
        self.colorDialog.show()

    def indicateColorChange(self, color: QColor):
        self._rgbValue = '#{:02X}{:02X}{:02X}'.format(color.red(), color.green(), color.blue())
        self.colorWindow.setStyleSheet("background-color: {}".format(self._rgbValue))
        QApplication.postEvent(
            self, QKeyEvent(QEvent.KeyPress, Qt.Key_Enter, Qt.NoModifier))
    
    def currentcolor(self) -> str:
        return self._rgbValue

    def setCurrentColor(self, color):
        if not isinstance(color, str):
            color = "#000000"
        if len(color) and color[0] != "#":
            color=cc.name_to_hex(color)
        if not len(color) or color is None:
        #elif not len(color):
            logging.warning("Received color='%s' for color_picker has a wrong format. Setting default color",color)
            if self.name == "crosshair_color":
                color = "#ff0000"  # Default color for crosshair will be red
            elif self.name == "font_color":
                color = "#000000"  # Default color for font will be black
            elif color == "background_color":
                color = "#FFFFFF"  # Default color for background of plot will be white
            else:
                color = "#000000"
        if color[0] == "#" and len(color) == 7:
            # Convert hex string to RGB
            r, g, b = tuple(int(color[i:i + 2], 16) for i in range(1, 7, 2))
            self.colorDialog.setCurrentColor(QColor(r, g, b))
        else:
            return self.indicateColorChange(self.colorDialog.currentColor())

    currentColor = Property(str, currentcolor, setCurrentColor, user=True)

