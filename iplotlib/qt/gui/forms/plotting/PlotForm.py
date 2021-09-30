# Description: Map properties of a Plot object to a form.
# Author: Piotr Mazur
# Changelog:
#   Sept 2021: -Refactor qt classes [Jaswant Sai Panchumarti]
#              -Port to PySide2 [Jaswant Sai Panchumarti]

import typing

from PySide2.QtCore import Qt
from PySide2.QtWidgets import QWidget

from iplotlib.qt.gui.forms.iplotPreferencesForm import IplotPreferencesForm
from iplotlib.qt.utils.color_picker import ColorPicker


class PlotForm(IplotPreferencesForm):

    def __init__(self, parent: typing.Optional[QWidget] = None, f: Qt.WindowFlags = Qt.Widget):
        prototype = [
            {"label": "Title", "property": "title",
                "widget": self.create_lineedit()},
            {"label": "Grid", "property": "grid",
                "widget": self.create_checkbox()},
            {"label": "Legend", "property": "legend",
                "widget": self.create_checkbox()},
            {"label": "Font size", "property": "font_size",
                "widget": self.default_fontsize_widget()},
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
                "widget": self.default_linepath_widget()}
        ]
        super().__init__(fields=prototype, label="A plot", parent=parent, f=f)
