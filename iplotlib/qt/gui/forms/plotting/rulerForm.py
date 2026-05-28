"""Map the properties of a Ruler object to the widgets in a GUI form."""

import typing

from PySide6.QtCore import QModelIndex, Qt, Slot
from PySide6.QtWidgets import QWidget

from iplotlib.core.ruler import Ruler
from iplotlib.qt.gui.forms.iplotPreferencesForm import IplotPreferencesForm
from iplotlib.qt.models.beanItemModel import BeanItemModel
from iplotlib.qt.utils.color_picker import ColorPicker


class RulerForm(IplotPreferencesForm):
    """Mapping for the Ruler dataclass: read-only name plus editable color and visibility."""

    def __init__(self, parent: typing.Optional[QWidget] = None, f: Qt.WindowFlags = Qt.Widget):
        prototype = [
            {"label": "Name", "property": "name",
             "widget": self.create_lineedit(readonly=True)},
            {"label": "Color", "property": "color", "widget": ColorPicker("color")},
            {"label": "Visible", "property": "visible", "widget": self.create_checkbox()},
        ]
        super().__init__(fields=prototype, label="A ruler", parent=parent, f=f)

    @Slot()
    def reset_prefs(self):
        py_object = self.widgetModel.data(QModelIndex(), BeanItemModel.PyObjectRole)
        if not isinstance(py_object, Ruler):
            return
        py_object.color = Ruler.color
        py_object.visible = Ruler.visible
        self.widgetMapper.revert()
        super().reset_prefs()
