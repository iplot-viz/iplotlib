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
from iplotlib.core.canvas import Canvas

from iplotlib.qt.models.beanItemModel import BeanItemModel
from iplotlib.qt.gui.forms.iplotPreferencesForm import IplotPreferencesForm
from iplotlib.qt.utils.color_picker import ColorPicker


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
            {"label": "Shared x axis", "property": "shared_x_axis",
                "widget": self.create_checkbox()},
            {"label": "Grid", "property": "grid",
                "widget":  self.create_checkbox()},
            {"label": "Legend", "property": "legend",
                "widget": self.create_checkbox()},
            {"label": "Legend position", "property": "legend_position",
                "widget": self.default_canvas_legend_position_widget()},
            {"label": "Legend layout", "property": "legend_layout",
                "widget": self.default_canvas_legend_layout_widget()},
            {"label": "Font color", "property": "font_color", "widget": ColorPicker()},
            {"label": "Line style", "property": "line_style",
                "widget": self.default_linestyle_widget()},
            {"label": "Line size", "property": "line_size",
                "widget": self.default_linesize_widget()},
            {"label": "Marker", "property": "marker",
                "widget": self.default_marker_widget()},
            {"label": "Marker size", "property": "marker_size",
                "widget": self.default_markersize_widget()},
            {"label": "Line Path", "property": "step",
                "widget":  self.default_linepath_widget()},
            {"label": "Focus all plots in stack", "property": "full_mode_all_stack", "widget":  self.create_checkbox()}]
        super().__init__(fields=prototype, label="Canvas", parent=parent, f=f)

    @Slot()
    def resetPrefs(self):
        pyObject = self.widgetModel.data(QModelIndex(), BeanItemModel.PyObjectRole)

        if isinstance(pyObject, Canvas):
            pyObject.reset_preferences()
        else:
            return

        self.widgetMapper.revert()
        super().resetPrefs()
