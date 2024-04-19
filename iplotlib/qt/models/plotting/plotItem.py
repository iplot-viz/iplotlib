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
                signalItem = SignalItem(f'Signal {signal_id} | stack {stack_id}', self.auto_name)
                signalItem.setEditable(False)
                signalItem.setData(signal, Qt.UserRole)
                if self.auto_name and signal.title:
                    signalItem.setText(signal.title)
                self.appendRow(signalItem)

        # process axes..
        axisPlan = dict()
        for ax_id, ax in enumerate(value.axes):
            if isinstance(ax, typing.Collection):
                if len(ax) == 1:
                    name = f'Axis {self.AXIS_NAMES[ax_id]}'
                    axisObject = ax[0]
                    axisPlan.update({name: axisObject})
                else:
                    for subax_id, sub_ax in enumerate(ax):
                        name = f'Axis {self.AXIS_NAMES[ax_id]}{subax_id}'
                        axisObject = sub_ax
                        axisPlan.update({name: axisObject})
            elif isinstance(ax, Axis):
                name = f'Axis {self.AXIS_NAMES[ax_id]}'
                axisObject = ax
                axisPlan.update({name: axisObject})

        for name, axisObject in axisPlan.items():
            axisItem = AxisItem(name, self.auto_name)
            axisItem.setData(axisObject, Qt.UserRole)
            if self.auto_name and axisObject.label:
                axisItem.setText(axisObject.label)
            self.appendRow(axisItem)
