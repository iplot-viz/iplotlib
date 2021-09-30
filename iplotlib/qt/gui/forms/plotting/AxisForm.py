# Description: Map properties of an Axis object to a form.
# Author: Piotr Mazur
# Changelog:
#   Sept 2021: -Refactor qt classes [Jaswant Sai Panchumarti]
#              -Port to PySide2 [Jaswant Sai Panchumarti]

import typing

from PySide2.QtCore import Qt
from PySide2.QtWidgets import QWidget

from iplotlib.qt.gui.forms.iplotPreferencesForm import IplotPreferencesForm
from iplotlib.qt.utils.color_picker import ColorPicker


class AxisForm(IplotPreferencesForm):

    def __init__(self, parent: typing.Optional[QWidget] = None, f: Qt.WindowFlags = Qt.Widget):

        prototype = [
            {"label": "Label", "property": "label",
                "widget": self.create_lineedit()},
            {"label": "Font size", "property": "font_size",
                "widget": self.default_fontsize_widget()},
            {"label": "Font color", "property": "font_color", "widget": ColorPicker()},
            {"label": "Min value", "property": "begin",
                "widget": self.create_lineedit()},
            {"label": "Max value", "property": "end",
                "widget": self.create_lineedit()}
        ]
        super().__init__(fields=prototype, label="An axis", parent=parent, f=f)
