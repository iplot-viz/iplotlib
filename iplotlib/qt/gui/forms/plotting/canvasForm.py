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
Map properties of a Canvas object to a form.
"""

# Author: Piotr Mazur
# Changelog:
#   Sept 2021:  -Refactor qt classes [Jaswant Sai Panchumarti]
#               -Port to PySide2 [Jaswant Sai Panchumarti]
#   Jan 2023:   -Added legend position and layout options [Alberto Luengo]

import typing

from PySide6.QtCore import QModelIndex, Qt, Slot
from PySide6.QtWidgets import QWidget
import json
from iplotlib.core.canvas import Canvas

from iplotlib.qt.models.beanItemModel import BeanItemModel
from iplotlib.qt.gui.forms.iplotPreferencesForm import IplotPreferencesForm
from iplotlib.qt.utils.color_picker import ColorPicker
from iplotlib.core.property_manager import PropertyManager

from pathlib import Path

from iplotLogging import setupLogger as Sl

logger = Sl.get_logger(__name__)


class CanvasForm(IplotPreferencesForm):
    """
    Map the properties of a Canvas object to the widgets in a GUI form.
    """

    def __init__(self, parent: typing.Optional[QWidget] = None, f: Qt.WindowFlags = Qt.Widget):
        prototype = [
            {"label": "Title", "property": "title",
             "widget": self.create_lineedit()},
            {"label": "Font size", "property": "font_size",
             "widget": self.default_fontsize_widget()},
            {"label": "Shared time", "property": "shared_x_axis",
             "widget": self.create_checkbox()},
            {"label": "Time range difference (s)", "property": "max_diff",
             "widget": self.default_canvas_max_diff()},
            {"label": "Round hours", "property": "round_hour",
             "widget": self.create_checkbox()},
            {"label": "Auto scale", "property": "autoscale",
             "widget": self.create_checkbox()},
            {"label": "Log scale", "property": "log_scale",
             "widget": self.create_checkbox()},
            {"label": "Grid", "property": "grid",
             "widget": self.create_checkbox()},
            {"label": "Show all ticks", "property": "ticks_position",
             "widget": self.create_checkbox()},
            {"label": "Number of ticks and labels", "property": "tick_number",
             "widget": self.default_ticknumber_widget()},
            {"label": "Background color", "property": "background_color", "widget": ColorPicker("background_color")},
            {"label": "Legend", "property": "legend",
             "widget": self.create_checkbox()},
            {"label": "Legend position", "property": "legend_position",
             "widget": self.default_canvas_legend_position_widget()},
            {"label": "Legend layout", "property": "legend_layout",
             "widget": self.default_canvas_legend_layout_widget()},
            {"label": "Enable Crosshair X-label", "property": "enable_x_label_crosshair",
             "widget": self.create_checkbox()},
            {"label": "Enable Crosshair Y-label", "property": "enable_y_label_crosshair",
             "widget": self.create_checkbox()},
            {"label": "Enable Crosshair Val-label", "property": "enable_val_label_crosshair",
             "widget": self.create_checkbox()},
            {"label": "Crosshair color", "property": "crosshair_color", "widget": ColorPicker("crosshair_color")},
            {"label": "Font color", "property": "font_color", "widget": ColorPicker("font_color")},
            {"label": "Line style", "property": "line_style",
             "widget": self.default_linestyle_widget()},
            {"label": "Line size", "property": "line_size",
             "widget": self.default_linesize_widget()},
            {"label": "Marker", "property": "marker",
             "widget": self.default_marker_widget()},
            {"label": "Marker size", "property": "marker_size",
             "widget": self.default_markersize_widget()},
            {"label": "Line Path", "property": "step",
             "widget": self.default_linepath_widget()},
            {"label": "Focus all plots in stack", "property": "full_mode_all_stack", "widget": self.create_checkbox()},
            {"label": "Contour Levels", "property": "contour_levels",
             "widget": self.default_contour_levels_widget()},
            {"label": "Contour Filled", "property": "contour_filled",
             "widget": self.create_checkbox()}]
        self._pm = PropertyManager()
        super().__init__(fields=prototype, label="Canvas", parent=parent, f=f)

    @Slot()
    def reset_prefs(self):
        py_object = self.widgetModel.data(QModelIndex(), BeanItemModel.PyObjectRole)

        if isinstance(py_object, Canvas):
            py_object.reset_preferences()
        else:
            return

        self.widgetMapper.revert()
        super().reset_prefs()

    def get_canvas_properties(self):
        # Get the current canvas properties and returns them as a dictionary
        canvas_properties = {
            field["property"]: self._pm.get_value(self.widgetModel.data(QModelIndex(), BeanItemModel.PyObjectRole),
                                                  field["property"]) for field in self.fields}

        extra_properties = {
            "autoscale": True,
            "legend_format": "color_bar",
            "equivalent_units": False,
            "color_map": "viridis",
            "color": None}

        return {**canvas_properties, **extra_properties}

    @Slot()
    def export_canvas_preferences(self):
        # Define folder path
        path = Path.home() / ".local" / "1DPreferences"
        path.mkdir(parents=True, exist_ok=True)

        # Define file path
        file_name = path / "default_properties.json"

        try:
            with file_name.open(mode="w", encoding="utf-8") as f:
                json.dump(self.get_canvas_properties(), f, ensure_ascii=False, indent=4)
                logger.info(f"Default Canvas preferences updated")
        except Exception as e:
            logger.error(f"Error exporting Canvas preferences: {e}")

        super().export_canvas_preferences()
