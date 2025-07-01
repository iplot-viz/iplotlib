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
            {"label": "Number of ticks and labels", "property": "tick_number",
             "widget": self.default_ticknumber_widget()}
        ]
        super().__init__(fields=prototype, label="An axis", parent=parent, f=f)

    @Slot()
    def reset_prefs(self):
        py_object = self.widgetModel.data(QModelIndex(), BeanItemModel.PyObjectRole)

        if isinstance(py_object, Axis):
            py_object.reset_preferences()
        else:
            return

        self.widgetMapper.revert()
        super().reset_prefs()
