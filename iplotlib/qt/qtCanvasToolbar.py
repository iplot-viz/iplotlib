import os
from functools import partial
from typing import Collection

from qtpy.QtCore import QMargins, Qt, Signal
from qtpy.QtGui import QIcon
from qtpy.QtWidgets import QAction, QActionGroup, QFileDialog, QMainWindow, QMessageBox, QSizePolicy, QToolBar

from iplotlib.core.canvas import Canvas
from iplotlib.qt.preferencesWindow import PreferencesWindow
from iplotlib.qt.qtPlotCanvas import QtPlotCanvas

import iplotLogging.setupLogger as ls

logger = ls.get_logger(__name__)


class CanvasToolbar(QToolBar):

    toolSelected = Signal(str)
    undo = Signal()
    redo = Signal()
    detach = Signal()
    export_json = Signal()
    import_json = Signal()
    redraw = Signal()
    preferences = Signal()

    def __init__(self, parent=None, attach_parent=None, qt_canvas=None):
        super().__init__(parent)

        self.qt_canvases = []

        self.layout().setContentsMargins(QMargins())
        self.setSizePolicy(QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum))

        self.attach_parent = attach_parent
        self.detached = False
        self.detached_window = QMainWindow()
        self.detached_window.setWindowTitle(F"MINT: {os.getpid()}")
        self.detached_window.layout().setContentsMargins(QMargins())
        self.detached_window.setWindowFlags(Qt.CustomizeWindowHint | Qt.WindowTitleHint | Qt.WindowMaximizeButtonHint | Qt.WindowMinimizeButtonHint)

        self.preferences_window = PreferencesWindow()

        tool_group = QActionGroup(self)
        tool_group.setExclusive(True)

        for e in [Canvas.MOUSE_MODE_SELECT, Canvas.MOUSE_MODE_CROSSHAIR, Canvas.MOUSE_MODE_PAN, Canvas.MOUSE_MODE_ZOOM]:
            tool_action = QAction(e[3:], self)
            tool_action.setCheckable(True)
            tool_action.setActionGroup(tool_group)
            tool_action.triggered.connect(partial(self.toolSelected.emit, e))
            self.addAction(tool_action)

        self.addSeparator()

        def create_icon(name):
            return QIcon(os.path.join(os.path.dirname(__file__), F"icons/{name}.png"))

        undo_action = QAction("Undo", self)
        undo_action.setIcon(create_icon("undo"))
        undo_action.triggered.connect(self.undo.emit)
        self.addAction(undo_action)

        redo_action = QAction("Redo", self)
        redo_action.setIcon(create_icon("redo"))
        redo_action.triggered.connect(self.redo.emit)
        self.addAction(redo_action)

        self.detach_action = QAction("Detach", self)
        # detach_action.setIcon(create_icon("fullscreen"))
        self.detach_action.triggered.connect(self.detach.emit)
        self.addAction(self.detach_action)

        preferences_action = QAction("Preferences", self)
        preferences_action.setIcon(create_icon("options"))
        preferences_action.triggered.connect(self.show_preferences)
        self.addAction(preferences_action)

        self.addAction(create_icon("save_as"), "Export to JSON", self.export_json.emit)
        self.addAction(create_icon("open_file"), "Import JSON", self.import_json.emit)
        self.addAction(create_icon("rotate180"), "Redraw", self.redraw.emit)

        if qt_canvas is not None:
            if isinstance(qt_canvas, Collection):
                for _ in qt_canvas:
                    self._connect(_)
            else:
                self._connect(qt_canvas)

    def show_preferences(self):
        all_canvases = [qt_canvas.get_canvas() for qt_canvas in self.qt_canvases]
        print("BINDING CANVASES: ", all_canvases)
        self.preferences_window.bind_canvases(all_canvases)
        self.preferences_window.show()

    def _connect(self, qt_canvas: QtPlotCanvas):

        def detach():
            detachable_widget = self.parent()
            if self.detached:
                detachable_widget.setParent(self.attach_parent)
                self.detached_window.hide()
                self.detached = False
                self.detach_action.setText("Detach")
            else:
                self.attach_parent = self.parent().parent()
                self.detached_window.setCentralWidget(detachable_widget)
                self.detached_window.show()
                self.detached = True
                self.detach_action.setText("Reattach")

        def redraw(qt_canvas_instance):
            qt_canvas_instance.set_canvas(qt_canvas_instance.get_canvas())

        def do_export(qt_canvas_instance):
            try:
                file = QFileDialog.getSaveFileName(self, "Save JSON")
                if file and file[0] and qt_canvas_instance is not None:
                    with open(file[0], "w") as out_file:
                        out_file.write(qt_canvas_instance.export_json())
            except Exception as e:
                box = QMessageBox()
                box.setIcon(QMessageBox.Critical)
                box.setText("Error exporting file")
                box.exec_()

        def do_import(qt_canvas_instance):
            try:
                file = QFileDialog.getOpenFileName(self, "Open CSV")
                if file and file[0]:
                    with open(file[0], "r") as in_file:
                        qt_canvas_instance.import_json(in_file.read())
            except Exception as e:
                print(e)
                box = QMessageBox()
                box.setIcon(QMessageBox.Critical)
                box.setText("Error parsing file")
                box.exec_()

        if qt_canvas is not None:
            self.qt_canvases.append(qt_canvas)
            self.export_json.connect(partial(do_export, qt_canvas))
            self.import_json.connect(partial(do_import, qt_canvas))
            self.toolSelected.connect(qt_canvas.set_mouse_mode)
            self.undo.connect(qt_canvas.back)
            self.redo.connect(qt_canvas.forward)
            self.detach.connect(detach)
            self.redraw.connect(partial(redraw, qt_canvas))
            self.preferences_window.apply.connect(partial(redraw, qt_canvas))

