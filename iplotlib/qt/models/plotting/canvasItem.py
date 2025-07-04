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
            plot_column_item = QStandardItem(f'Column {column_idx + 1}')
            self.appendRow(plot_column_item)

            if not isinstance(column, typing.Collection):
                continue

            for plot_idx, plot in enumerate(column):
                if not isinstance(plot, Plot):
                    continue
                plot_item = PlotItem(f'Plot {plot_idx + 1}', self.auto_name)
                plot_item.setEditable(False)
                plot_item.setData(plot, Qt.UserRole)
                plot.id = [column_idx + 1, plot_idx + 1]

                if self.auto_name and plot.plot_title:
                    plot_item.setText(plot.plot_title)

                plot_column_item.appendRow(plot_item)
