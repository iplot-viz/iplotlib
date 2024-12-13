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

from iplotlib.core.signal import SignalXY, SignalContour
from iplotlib.qt.gui.forms.iplotPreferencesForm import IplotPreferencesForm
from iplotlib.qt.models.beanItemModel import BeanItemModel
from iplotlib.qt.utils.color_picker import ColorPicker


class SignalXYForm(IplotPreferencesForm):
    """
    Map the properties of a SignalXY object to the widgets in a GUI form.
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
    def reset_prefs(self):
        py_object = self.widgetModel.data(QModelIndex(), BeanItemModel.PyObjectRole)

        if isinstance(py_object, SignalXY):
            py_object.reset_preferences()
        else:
            return

        self.widgetMapper.revert()
        super().reset_prefs()


class SignalContourForm(IplotPreferencesForm):
    """
    Map the properties of a SignalContour object to the widgets in a GUI form.
    """

    def __init__(self, parent: typing.Optional[QWidget] = None, f: Qt.WindowFlags = Qt.Widget):
        prototype = [
            {"label": "Label", "property": "label", "widget": self.create_lineedit()},
            {"label": "Varname", "property": "varname", "widget": self.create_lineedit(readonly=True)},
            {"label": "Color map", "property": "color_map", "widget": self.default_plot_contour_color_map_widget()},
            {"label": "Contour Levels", "property": "contour_levels", "widget": self.default_contour_levels_widget()}]
        super().__init__(fields=prototype, label="A signal", parent=parent, f=f)

    @Slot()
    def reset_prefs(self):
        py_object = self.widgetModel.data(QModelIndex(), BeanItemModel.PyObjectRole)

        if isinstance(py_object, SignalContour):
            py_object.reset_preferences()
        else:
            return

        self.widgetMapper.revert()
        super().reset_prefs()
