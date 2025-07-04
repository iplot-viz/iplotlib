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
Map properties of a Plot object to a form.
"""

# Author: Piotr Mazur
# Changelog:
#   Sept 2021:  -Refactor qt classes [Jaswant Sai Panchumarti]
#               -Port to PySide2 [Jaswant Sai Panchumarti]
#   Jan 2023:   -Added legend position and layout options [Alberto Luengo]

import typing

from PySide6.QtCore import QModelIndex, Qt, Slot
from PySide6.QtWidgets import QWidget

from iplotlib.core.plot import PlotXY, PlotContour
from iplotlib.qt.gui.forms.iplotPreferencesForm import IplotPreferencesForm
from iplotlib.qt.models.beanItemModel import BeanItemModel
from iplotlib.qt.utils.color_picker import ColorPicker


class PlotXYForm(IplotPreferencesForm):
    """
    Map the properties of a Plot object to the widgets in a GUI form.
    """

    def __init__(self, parent: typing.Optional[QWidget] = None, f: Qt.WindowFlags = Qt.Widget):
        prototype = [
            {"label": "Title", "property": "plot_title",
             "widget": self.create_lineedit()},
            {"label": "Log scale", "property": "log_scale",
             "widget": self.create_checkbox()},
            {"label": "Grid", "property": "grid",
             "widget": self.create_checkbox()},
            {"label": "Legend", "property": "legend",
             "widget": self.create_checkbox()},
            {"label": "Legend position", "property": "legend_position",
             "widget": self.default_plot_legend_position_widget()},
            {"label": "Legend layout", "property": "legend_layout",
             "widget": self.default_plot_legend_layout_widget()},
            {"label": "Font size", "property": "font_size",
             "widget": self.default_fontsize_widget()},
            {"label": "Font color", "property": "font_color", "widget": ColorPicker("font_color")},
            {"label": "Background color", "property": "background_color", "widget": ColorPicker("background_color")},
            {"label": "Line style", "property": "line_style",
             "widget": self.default_linestyle_widget()},
            {"label": "Line size", "property": "line_size",
             "widget": self.default_linesize_widget()},
            {"label": "Marker", "property": "marker",
             "widget": self.default_marker_widget()},
            {"label": "Marker size", "property": "marker_size",
             "widget": self.default_markersize_widget()},
            {"label": "Line Path", "property": "step",
             "widget": self.default_linepath_widget()}
        ]
        super().__init__(fields=prototype, label="A plot", parent=parent, f=f)

    @Slot()
    def reset_prefs(self):
        py_object = self.widgetModel.data(QModelIndex(), BeanItemModel.PyObjectRole)

        if isinstance(py_object, PlotXY):
            py_object.reset_preferences()
        else:
            return

        self.widgetMapper.revert()
        super().reset_prefs()


class PlotContourForm(IplotPreferencesForm):
    """
    Map the properties of a Plot object to the widgets in a GUI form.
    """

    def __init__(self, parent: typing.Optional[QWidget] = None, f: Qt.WindowFlags = Qt.Widget):
        prototype = [
            {"label": "Title", "property": "title", "widget": self.create_lineedit()},
            {"label": "Grid", "property": "grid", "widget": self.create_checkbox()},
            {"label": "Legend format", "property": "legend_format",
             "widget": self.default_plot_contour_legend_format_widget()},
            {"label": "Font size", "property": "font_size", "widget": self.default_fontsize_widget()},
            {"label": "Font color", "property": "font_color", "widget": ColorPicker("font_color")},
            {"label": "Background color", "property": "background_color", "widget": ColorPicker("background_color")},
            {"label": "Contour Levels", "property": "contour_levels", "widget": self.default_contour_levels_widget()},
            {"label": "Contour Filled", "property": "contour_filled", "widget": self.create_checkbox()},
            {"label": "Equivalent Units", "property": "equivalent_units", "widget": self.create_checkbox()}]
        super().__init__(fields=prototype, label="A plot", parent=parent, f=f)

    @Slot()
    def reset_prefs(self):
        py_object = self.widgetModel.data(QModelIndex(), BeanItemModel.PyObjectRole)

        if isinstance(py_object, PlotContour):
            py_object.reset_preferences()
        else:
            return

        self.widgetMapper.revert()
        super().reset_prefs()
