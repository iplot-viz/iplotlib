"""
Map properties of a Signal object to a form.
"""

# Author: Piotr Mazur
# Changelog:
#   Sept 2021: -Refactor qt classes [Jaswant Sai Panchumarti]
#              -Port to PySide2 [Jaswant Sai Panchumarti]

import typing

from PySide6.QtCore import QModelIndex, Qt, Slot
from PySide6.QtWidgets import QWidget

from iplotlib.core.signal import Signal
from iplotlib.qt.gui.forms.iplotPreferencesForm import IplotPreferencesForm
from iplotlib.qt.models.beanItemModel import BeanItemModel
from iplotlib.qt.utils.color_picker import ColorPicker


class SignalForm(IplotPreferencesForm):
    """
    Map the properties of a Signal object to the widgets in a GUI form.
    """

    def __init__(self, parent: typing.Optional[QWidget] = None, f: Qt.WindowFlags = Qt.Widget):
        prototype = [
            {"label": "Label", "property": "label",
             "widget": self.create_lineedit()},
            {"label": "Varname", "property": "varname",
             "widget": self.create_lineedit(readonly=True)},
            {"label": "Color", "property": "color", "widget": ColorPicker("color")},
            {"label": "Line style", "property": "line_style",
             "widget": self.default_linestyle_widget()},
            {"label": "Line size", "property": "line_size",
             "widget": self.default_linesize_widget()},
            {"label": "Marker", "property": "marker",
             "widget": self.default_marker_widget()},
            {"label": "Marker size", "property": "marker_size",
             "widget": self.default_markersize_widget()},
            {"label": "Line Path", "property": "step", "widget": self.default_linepath_widget()}]
        super().__init__(fields=prototype, label="A signal", parent=parent, f=f)

    @Slot()
    def resetPrefs(self):
        pyObject = self.widgetModel.data(QModelIndex(), BeanItemModel.PyObjectRole)

        if isinstance(pyObject, Signal):
            pyObject.reset_preferences()
        else:
            return

        self.widgetMapper.revert()
        super().resetPrefs()
