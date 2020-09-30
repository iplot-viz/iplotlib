from PyQt5.QtCore import QSize
from PyQt5.QtWidgets import QWidget

"""
Main abstraction of a Qt plot canvas.
A Qt plot canvas is used to plot multiple plots and present them in form of a Qt widget
"""


class QtPlotCanvas(QWidget):

    # This will be applied as initial size
    #TODO: Can be directly related to the size of the canvas grid
    def sizeHint(self):
        return QSize(900, 400)


