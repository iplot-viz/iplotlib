import os
import typing
from collections import namedtuple
from typing import Collection, NamedTuple

from qtpy.QtCore import QAbstractItemModel, QEvent, QMargins, QModelIndex, Qt, Property, Signal
from qtpy.QtGui import QKeyEvent, QStandardItem, QStandardItemModel
from qtpy.QtWidgets import QApplication, QCheckBox, QColorDialog, QComboBox, QDataWidgetMapper, QDoubleSpinBox, QFormLayout, QLabel, QLineEdit, QMainWindow, QPushButton, QSizePolicy, QSpinBox, \
    QSplitter, QStackedWidget, QTreeView, QVBoxLayout, QWidget

from core.axis import Axis
from impl.matplotlib.matplotlibCanvas import ConversionHelper
from iplotlib.core.signal import ArraySignal
from iplotlib.core.canvas import Canvas
from iplotlib.core.axis import LinearAxis
from iplotlib.core.plot import PlotXY
from iplotlib.data_access.dataAccessSignal import DataAccessSignal


#FIXME: Colorpicker seems to stick its value (change one plot color to red, then second plot color to white then show colorpicker on first to see results)
class PreferencesWindow(QMainWindow):

    apply = Signal()

    def __init__(self, parent=None):
        super().__init__()
        self.setWindowTitle("MINT: {}".format(os.getpid()))
        self.resize(800, 400)
        self.tree_view = QTreeView()
        self.tree_view.setHeaderHidden(True)
        self.forms = {
            Canvas: CanvasForm(),
            PlotXY: PlotForm(),
            LinearAxis: AxisForm(),
            ArraySignal: SignalForm(),
            DataAccessSignal: SignalForm(),
            type(None): QPushButton("Select item")
        }

        self.right_column = QStackedWidget()

        for form in self.forms.values():
            self.right_column.addWidget(form)
            if isinstance(form, PreferencesForm):
                form.applySignal.connect(self.apply.emit)

        central_widget = QSplitter()
        central_widget.addWidget(self.tree_view)
        central_widget.addWidget(self.right_column)
        central_widget.setSizes([30, 70])

        self.setCentralWidget(central_widget)

    def item_selected(self, item):

        if len(item.indexes()) > 0:
            for i in item.indexes():
                data = i.data(Qt.UserRole)
                print(F"ITEM SELECTED {item} indexes: {item.indexes()} data: {data}")
                index = list(self.forms.keys()).index(type(data))
                self.right_column.setCurrentIndex(index)
                if isinstance(self.right_column.currentWidget(), PreferencesForm):
                    self.right_column.currentWidget().set_model(data)

    def bind_canvases(self, canvas):
        self.tree_view.setModel(CanvasItemModel(canvases=canvas))
        self.tree_view.selectionModel().selectionChanged.connect(self.item_selected)
        index = list(self.forms.keys()).index(Canvas)
        self.right_column.setCurrentIndex(index)

        if isinstance(self.right_column.currentWidget(), PreferencesForm):
            self.right_column.currentWidget().set_model(canvas[0])
        self.tree_view.expandAll()

    def closeEvent(self, event):
        if QApplication.focusWidget():
            QApplication.focusWidget().clearFocus()
        self.apply.emit()


class CanvasItemModel(QStandardItemModel):
    axis_names = ['x', 'y', 'z']

    def __init__(self, canvases=None, auto_names=False):
        super().__init__()
        self.autoNames = auto_names
        self.canvases = []

        if canvases is not None:
            if isinstance(canvases, Collection):
                for canvas in canvases:
                    self.add_canvas(canvas)
            else:
                self.add_canvas(canvases)

    def add_canvas(self, canvas):
        if not isinstance(canvas, Canvas):
            raise Exception(F"Not a canvas instance: {canvas}")

        self.canvases.append(canvas)
        self.process_canvas(canvas, len(self.canvases)-1)

    def process_canvas(self, canvas, canvas_idx):
        canvasItem = QStandardItem(F"Canvas {canvas_idx + 1}")
        canvasItem.setEditable(False)
        canvasItem.setData(canvas, Qt.UserRole)
        if self.autoNames and canvas.title:
            canvasItem.setText(canvas.title)

        self.setItem(canvas_idx, 0, canvasItem)

        if canvas is not None:
            for column_idx in range(len(canvas.plots)):
                columnItem = QStandardItem("Column " + str(column_idx))
                canvasItem.appendRow(columnItem)

                for plot_idx, plot in enumerate(canvas.plots[column_idx]):
                    self.process_plot(columnItem, plot, plot_idx)

    def process_plot(self, column_item, plot, plot_idx):
        plotItem = QStandardItem("Plot " + str(plot_idx))
        plotItem.setEditable(False)
        plotItem.setData(plot, Qt.UserRole)
        if self.autoNames and plot.title:
            plotItem.setText(plot.title)

        column_item.appendRow(plotItem)

        if plot:
            for stack_idx, stack in enumerate(plot.signals.values()):
                for signal_idx, signal in enumerate(stack):
                    signalItem = QStandardItem("Signal {} stack {}".format(signal_idx, stack_idx))
                    signalItem.setEditable(False)
                    signalItem.setData(signal, Qt.UserRole)
                    if self.autoNames and signal.title:
                        signalItem.setText(signal.title)
                    plotItem.appendRow(signalItem)

            for axis_idx, axis in enumerate(plot.axes):
                if isinstance(axis, Collection):
                    if len(axis) == 1:
                        self.process_axis(F"Axis {self.axis_names[axis_idx]}", axis[0], plotItem)
                    else:
                        for subaxis_idx, subaxis in enumerate(axis):
                            self.process_axis(F"Axis {self.axis_names[axis_idx]}{subaxis_idx}", subaxis, plotItem)
                else:
                    self.process_axis(F"Axis {self.axis_names[axis_idx]}", axis, plotItem)


    def process_axis(self, label, ipl_axis, plotItem):
        if not isinstance(ipl_axis, LinearAxis):
            raise Exception(F"Given instance is not an iplot axis: {ipl_axis} {isinstance(ipl_axis, LinearAxis)}")

        axisItem = QStandardItem(label)
        axisItem.setEditable(False)
        axisItem.setData(ipl_axis, Qt.UserRole)
        if self.autoNames and ipl_axis.label:
            axisItem.setText(ipl_axis.label)
        plotItem.appendRow(axisItem)


class BeanItemModel(QAbstractItemModel):
    """An implementation of QAbstractItemModel that binds indexes to object properties"""

    def __init__(self, form):
        super().__init__()
        self.form = form


    def data(self, index: QModelIndex, role: int = ...) -> typing.Any:
        print(F"** GET DATA {index.column()}")
        if self.form and self.form.model is not None and self.form.fields is not None:
            field = self.get_field(index.column())
            print(F"\tFIELD: {field}")
            if field.widget is not None and hasattr(field.widget, '_items'):

                key = getattr(self.form.model, field.property)
                keys = list(field.widget._items.keys())
                if key in keys:
                    return keys.index(key)
                else:
                    return 0
            else:
                try:
                    return self._to_view(field, self.form.model)
                except Exception as e:

                    print(F"ERROR for getattr {field.property} model: {self.form.model}: {e}")
        return ""

    def setData(self, index: QModelIndex, value: typing.Any, role: int = ...) -> bool:
        print(F"** SET DATA {index.column()} value={value}")
        if self.form and self.form.model is not None and self.form.fields is not None:
            field = self.get_field(index.column())
            print(F"\tFIELDx: {field} model: {self.form.model}")

            if field.widget is not None and hasattr(field.widget, '_items'):
                keys = list(field.widget._items.keys())
                setattr(self.form.model, field.property, keys[value])
            else:
                if hasattr(self.form.model, field.property):
                    cur_type = type(getattr(self.form.model, field.property))
                    print(F"CURTYPE: {cur_type.__name__}")
                    value = ConversionHelper.asType(value, cur_type)

                setattr(self.form.model, field.property, value)

            self.dataChanged.emit(self.createIndex(0, 0), self.createIndex(100, 100)) #FIXME: correct this
            self.layoutChanged.emit()

        return True

    def get_field(self, idx):
        return list(self.form.fields.values())[idx]

    def columnCount(self, parent: QModelIndex = ...) -> int:
        if self.form.fields is not None:
            return len(self.form.fields)
        return 1

    def rowCount(self, parent: QModelIndex = ...) -> int:
        return 1

    def index(self, row: int, column: int, parent: QModelIndex = ...) -> QModelIndex:
        return self.createIndex(row, column)

    def _to_view(self, field, model):
        print(F"* TO_VIEW {field} model={model}")
        value = getattr(model, field.property)
        return "" if value is None else str(value)

    def _to_model(self, field_def, model):
        pass

FormField = namedtuple('FormField', ['label', 'property', 'widget', 'converter'], defaults=[None])


# TODO: Range changes should be included as canvas property: for entire canvas or for plots
class PreferencesForm(QWidget):

    applySignal = Signal()

    def __init__(self, label: str = None):
        super().__init__()
        self.setLayout(QVBoxLayout())
        if label is not None:
            top_label = QLabel(label)
            top_label.setSizePolicy(QSizePolicy(QSizePolicy.MinimumExpanding, QSizePolicy.Maximum))
            self.layout().addWidget(top_label)

        self.form = QWidget()
        self.form.setLayout(QFormLayout())
        self.layout().addWidget(self.form)

        apply_button = QPushButton("Apply")
        apply_button.pressed.connect(self.applySignal.emit)
        self.layout().addWidget(apply_button)

        self.mapper = QDataWidgetMapper()
        self.model = None
        self.mapper.setModel(BeanItemModel(self))

        self.fields = dict()

    def add_fields(self, fields_to_add):
        if fields_to_add is not None and len(fields_to_add) > 0:
            for index, a_tuple in enumerate(fields_to_add):
                if isinstance(a_tuple, tuple):
                    field = FormField(*list(a_tuple))
                    self.fields[field.property] = field
                    self.form.layout().addRow(field.label, field.widget)
                    if isinstance(field.widget, QComboBox):
                        self.mapper.addMapping(field.widget, index, b"currentIndex")
                    else:
                        self.mapper.addMapping(field.widget, index)

    def set_model(self, obj):
        print("*** SET_MODEL:",obj)
        self.model = obj
        self.mapper.toFirst()

    def create_spinbox(self, **params):
        widget = QSpinBox()
        if params.get("min"):
            widget.setMinimum(params.get("min"))
        if params.get("max"):
            widget.setMaximum(params.get("max"))
        return widget

    def create_comboBox(self, items):
        widget = QComboBox()
        widget._items = items
        if isinstance(items, dict):
            for k, v in items.items():
                widget.addItem(v, k)
        elif isinstance(items, list):
            for i in items:
                widget.addItem(i)
            pass
        return widget

    def create_lineedit(self, **params):
        widget = QLineEdit()
        if params.get("readonly"):
            widget.setReadOnly(params.get("readonly"))
        return widget

    def default_fontsize_widget(self):
        return self.create_spinbox(min=0, max=20)

    def default_linesize_widget(self):
        return self.create_spinbox(min=0, max=20)

    def default_markersize_widget(self):
        return self.create_spinbox(min=0, max=20)

    def default_linestyle_widget(self):
        return self.create_comboBox({"Solid": "Solid", "Dotted": "Dotted", "Dashed": "Dashed", "None": "None"})

    def default_marker_widget(self):
        return self.create_comboBox({"None": "None", "o": "o", "x": "x"})

    def default_linepath_widget(self):
        return self.create_comboBox({"None": "Linear", "post": "Last Value"})


class CanvasForm(PreferencesForm):

    def __init__(self):
        super().__init__("Canvas")
        canvas_fields = [
            ("Title", "title", QLineEdit()),
            ("Font size", "font_size", self.default_fontsize_widget()),
            ("Shared x axis", "shared_x_axis", QCheckBox()),
            ("Grid", "grid", QCheckBox()),
            ("Legend", "legend", QCheckBox()),
            ("Font color", "font_color", ColorPicker()),
            ("Line style", "line_style", self.default_linestyle_widget()),
            ("Line size", "line_size", self.default_linesize_widget()),
            ("Marker", "marker", self.default_marker_widget()),
            ("Marker size", "marker_size", self.default_markersize_widget()),
            ("Line Path", "step", self.default_linepath_widget())
        ]
        self.add_fields(canvas_fields)


class PlotForm(PreferencesForm):
    def __init__(self):
        super().__init__("A plot")
        plot_fields = [
            ("Title", "title", QLineEdit()),
            ("Grid", "grid", QCheckBox()),
            ("Legend", "legend", QCheckBox()),
            ("Font size", "font_size", self.default_fontsize_widget()),
            ("Font color", "font_color", ColorPicker()),
            ("Line style", "line_style", self.default_linestyle_widget()),
            ("Line size", "line_size", self.default_linesize_widget()),
            ("Marker", "marker", self.default_marker_widget()),
            ("Marker size", "marker_size", self.default_markersize_widget()),
            ("Line Path", "step", self.default_linepath_widget())

        ]
        self.add_fields(plot_fields)


class AxisForm(PreferencesForm):
    def __init__(self):
        super().__init__("An axis")

        axis_fields = [
            ("Label", "label", QLineEdit()),
            ("Font size", "font_size", self.default_fontsize_widget()),
            ("Font color", "font_color", ColorPicker()),
            ("Min value", "begin", QLineEdit()),
            ("Max value", "end", QLineEdit())
        ]

        self.add_fields(axis_fields)


class SignalForm(PreferencesForm):
    def __init__(self):
        super().__init__("A signal")
        signal_fields = [
            ("Label", "title", QLineEdit()),
            ("Varname", "varname", self.create_lineedit(readonly=True)),
            ("Color", "color", ColorPicker()),
            ("Line style", "line_style", self.default_linestyle_widget()),
            ("Line size", "line_size", self.default_linesize_widget()),
            ("Marker", "marker", self.default_marker_widget()),
            ("Marker size", "marker_size", self.default_markersize_widget()),
            ("Line Path", "step", self.default_linepath_widget())]
        self.add_fields(signal_fields)


class ColorPicker(QWidget):

    def __init__(self):
        super().__init__()
        self.setLayout(QVBoxLayout())
        self.layout().setContentsMargins(QMargins())
        button = QPushButton("Select color")
        button.clicked.connect(self.open_picker)
        self.layout().addWidget(button)
        self.dialog = QColorDialog(self)
        self.dialog.colorSelected.connect(self.select_color)
        self.selectedColor = None

    def open_picker(self):
        self.dialog.show()

    def select_color(self, color):
        self.setProperty("rgbValue", '#{:02X}{:02X}{:02X}'.format(color.red(), color.green(), color.blue()))
        QApplication.postEvent(self, QKeyEvent(QEvent.KeyPress, Qt.Key_Enter, Qt.NoModifier))

    @Property(str, user=True)
    def rgbValue(self):
        return self.selectedColor

    @rgbValue.setter
    def rgbValue(self, color):
        self.setStyleSheet("background-color: {}".format(color))
        self.selectedColor = color
