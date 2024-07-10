"""
Map properties of an Axis object to a form.
"""

# Author: Piotr Mazur
# Changelog:
#   Sept 2021: -Refactor qt classes [Jaswant Sai Panchumarti]
#              -Port to PySide2 [Jaswant Sai Panchumarti]

import typing

from PySide6.QtCore import QModelIndex, Qt, Slot
from PySide6.QtWidgets import QWidget

from iplotlib.core.axis import Axis
from iplotlib.qt.gui.forms.iplotPreferencesForm import IplotPreferencesForm
from iplotlib.qt.models.beanItemModel import BeanItemModel
from iplotlib.qt.utils.color_picker import ColorPicker


class AxisForm(IplotPreferencesForm):
    """
    Map the properties of an Axis object to the widgets in a GUI form.
    """

    def __init__(self, parent: typing.Optional[QWidget] = None, f: Qt.WindowFlags = Qt.Widget):

        prototype = [
            {"label": "Label", "property": "label", "widget": self.create_lineedit()},
            {"label": "Font size", "property": "font_size", "widget": self.default_fontsize_widget()},
            {"label": "Font color", "property": "font_color", "widget": ColorPicker("font_color")},
            {"label": "Min value", "property": "begin", "widget": self.create_lineedit()},
            {"label": "Max value", "property": "end", "widget": self.create_lineedit()},
            {"label": "Auto scale", "property": "autoscale", "widget": self.create_checkbox()},
            {"label": "Number of ticks and labels", "property": "tick_number",
             "widget": self.default_ticknumber_widget()}
        ]
        super().__init__(fields=prototype, label="An axis", parent=parent, f=f)

    @Slot()
    def resetPrefs(self):
        pyObject = self.widgetModel.data(QModelIndex(), BeanItemModel.PyObjectRole)

        if isinstance(pyObject, Axis):
            pyObject.reset_preferences()
        else:
            return

        self.widgetMapper.revert()
        super().resetPrefs()
