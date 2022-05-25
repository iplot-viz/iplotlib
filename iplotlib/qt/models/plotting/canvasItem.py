"""
Container of Plots in the Model/View architecture
"""

# Author: Jaswant Sai Panchumarti

import typing

from PySide6.QtCore import Qt
from PySide6.QtGui import QStandardItem

from iplotlib.core import Canvas, Plot
from iplotlib.qt.models.plotting.plotItem import PlotItem

class CanvasItem(QStandardItem):
    def __init__(self, text: str, auto_name=False):
        super().__init__(text)
        self.auto_name = auto_name

    def setData(self, value: typing.Any, role: int = Qt.UserRole):
        super().setData(value, role=role)
        if not isinstance(value, Canvas):
            return
        
        if self.auto_name and value.title:
            self.setText(value.title)

        for column_idx in range(len(value.plots)):
            column = value.plots[column_idx]
            plotColumnItem = QStandardItem(f'Column {column_idx}')
            self.appendRow(plotColumnItem)
            
            if not isinstance(column, typing.Collection):
                continue

            for plot_idx, plot in enumerate(column):
                if not isinstance(plot, Plot):
                    continue
                plotItem = PlotItem(f'Plot {plot_idx}', self.auto_name)
                plotItem.setEditable(False)
                plotItem.setData(plot, Qt.UserRole)

                if self.auto_name and plot.title:
                    plotItem.setText(plot.title)
                
                plotColumnItem.appendRow(plotItem)
