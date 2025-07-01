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
Container of axes, signals in the Model/View architecture
"""

# Author: Jaswant Sai Panchumarti

import typing

from PySide6.QtCore import Qt
from PySide6.QtGui import QStandardItem

from iplotlib.core import Axis, Plot
from iplotlib.qt.models.plotting.axisItem import AxisItem
from iplotlib.qt.models.plotting.signalItem import SignalItem


class PlotItem(QStandardItem):
    AXIS_NAMES = ['x', 'y', 'z']

    def __init__(self, text: str, auto_name=False):
        super().__init__(text)
        self.auto_name = auto_name

    def setData(self, value: typing.Any, role: int = Qt.UserRole):
        super().setData(value, role=role)

        if not isinstance(value, Plot):
            return

        # process signals..
        for stack_id, stack in enumerate(value.signals.values()):
            for signal_id, signal in enumerate(stack):
                signal_item = SignalItem(f'Signal {signal_id + 1} | stack {stack_id + 1}', self.auto_name)
                signal_item.setEditable(False)
                signal_item.setData(signal, Qt.UserRole)
                signal.id = stack_id + 1
                if self.auto_name and signal.title:
                    signal_item.setText(signal.title)
                self.appendRow(signal_item)

        # process axes..
        axis_plan = dict()
        for ax_id, ax in enumerate(value.axes):
            if isinstance(ax, typing.List):
                if len(ax) == 1:
                    name = f'Axis {self.AXIS_NAMES[ax_id]}'
                    axis_object = ax[0]
                    axis_plan.update({name: axis_object})
                else:
                    for subax_id, sub_ax in enumerate(ax):
                        name = f'Axis {self.AXIS_NAMES[ax_id]}{subax_id}'
                        axis_object = sub_ax
                        axis_plan.update({name: axis_object})
            elif isinstance(ax, Axis):
                name = f'Axis {self.AXIS_NAMES[ax_id]}'
                axis_object = ax
                axis_plan.update({name: axis_object})

        for name, axis_object in axis_plan.items():
            axis_item = AxisItem(name, self.auto_name)
            axis_item.setData(axis_object, Qt.UserRole)
            if self.auto_name and axis_object.label:
                axis_item.setText(axis_object.label)
            self.appendRow(axis_item)
