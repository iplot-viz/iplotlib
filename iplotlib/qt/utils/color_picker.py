# Description: A color dialog box.
# Author: Piotr Mazur
# Changelog:
#   Sept 2021: -Refactor qt classes [Jaswant Sai Panchumarti]
#              -Port to PySide2 [Jaswant Sai Panchumarti]


from PySide2.QtCore import QMargins, QEvent, Qt, Property
from PySide2.QtGui import QColor, QKeyEvent
from PySide2.QtWidgets import QApplication, QColorDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QWidget

class ColorPicker(QWidget):

    def __init__(self):
        super().__init__()
        self.setLayout(QHBoxLayout())
        self.layout().setContentsMargins(QMargins())

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
            return
        elif not len(color):
            return
        if color[0] == "#" and len(color) == 7:
            # Convert hex string to RGB
            r, g, b = tuple(int(color[i:i + 2], 16) for i in range(1, 7, 2))
            self.colorDialog.setCurrentColor(QColor(r, g, b))
        else:
            return self.indicateColorChange(self.colorDialog.currentColor())

    currentColor = Property(str, currentcolor, setCurrentColor, user=True)

