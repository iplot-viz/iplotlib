from abc import ABC
from qt.QtPlotCanvas import QtPlotCanvas


class QtOverlayPlotCanvas(QtPlotCanvas):

    def __init__(self):
        super().__init__()
