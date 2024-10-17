"""
A main window with a collection of iplotlib canvases and a helpful toolbar.
"""

# Author: Jaswant Sai Panchumarti

from functools import partial
import typing

from PySide6.QtCore import QMargins, Qt, Signal
from PySide6.QtWidgets import QApplication, QMainWindow, QWidget
from PySide6.QtGui import QCloseEvent, QShowEvent
from iplotlib.core.command import IplotCommand

from iplotlib.qt.gui.iplotCanvasToolbar import IplotQtCanvasToolbar
from iplotlib.qt.gui.iplotQtCanvas import IplotQtCanvas
from iplotlib.qt.gui.iplotQtCanvasAssembly import IplotQtCanvasAssembly
from iplotlib.qt.gui.iplotQtPreferencesWindow import IplotQtPreferencesWindow

from iplotLogging import setupLogger as Sl

logger = Sl.get_logger(__name__)


class IplotQtMainWindow(QMainWindow):
    """
    A main window containing a toolbar and an assembly of iplotlib canvasses.
    This class helps developers write custom applications with PySide2
    """

    toolActivated = Signal(str)
    detachClicked = Signal(str)

    def __init__(self, show_toolbar: bool = True, parent: typing.Optional[QWidget] = None,
                 flags: Qt.WindowFlags = Qt.WindowFlags()):
        super().__init__(parent=parent, flags=flags)

        self.canvasStack = IplotQtCanvasAssembly(parent=self)
        self.toolBar = IplotQtCanvasToolbar(parent=self)
        self.toolBar.setVisible(show_toolbar)
        self.prefWindow = IplotQtPreferencesWindow(
            self.canvasStack.model(), parent=self, flags=flags)
        self.prefWindow.canvasSelected.connect(self.canvasStack.setCurrentIndex)
        self.prefWindow.onApply.connect(self.update_canvas_preferences)
        self.prefWindow.onReset.connect(self.reset_prefs)

        self.addToolBar(self.toolBar)
        self.setCentralWidget(self.canvasStack)
        self.wire_connections()

        self._floatingWindow = QMainWindow(parent=self,
                                           flags=(Qt.WindowType.CustomizeWindowHint
                                                  | Qt.WindowType.WindowTitleHint
                                                  | Qt.WindowType.WindowMaximizeButtonHint
                                                  | Qt.WindowType.WindowMinimizeButtonHint))
        self._floatingWinMargins = QMargins()
        self._floatingWindow.layout().setContentsMargins(self._floatingWinMargins)
        self._floatingWindow.hide()

    def wire_connections(self):
        self.toolBar.undoAction.triggered.connect(self.undo)
        self.toolBar.redoAction.triggered.connect(self.redo)
        self.toolBar.toolActivated.connect(
            lambda tool_name:
            [self.canvasStack.widget(i).set_mouse_mode(tool_name) for i in range(self.canvasStack.count())])
        self.canvasStack.canvasAdded.connect(self.on_canvas_add)
        self.canvasStack.currentChanged.connect(lambda idx: self.check_history(self.canvasStack.widget(idx)))
        self.toolBar.redrawAction.triggered.connect(self.re_draw)
        self.toolBar.detachAction.triggered.connect(self.detach)
        self.toolBar.configureAction.triggered.connect(
            lambda:
            [self.prefWindow.show(),
             self.prefWindow.raise_(),
             self.prefWindow.activateWindow()])

    def undo(self):
        w = self.canvasStack.currentWidget()
        if not w:
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        w.undo()
        QApplication.restoreOverrideCursor()
        self.check_history(w)

    def redo(self):
        w = self.canvasStack.currentWidget()
        if not w:
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        w.redo()
        QApplication.restoreOverrideCursor()
        self.check_history(w)

    def drop_history(self):
        w = self.canvasStack.currentWidget()
        if not w:
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        w.drop_history()
        QApplication.restoreOverrideCursor()
        self.check_history(w)

    def check_history(self, w: IplotQtCanvas):
        """
        Check the current state of history and set the style and text of undo, redo buttons.
        """
        if w.can_undo():
            self.toolBar.undoAction.setEnabled(True)
            self.toolBar.undoAction.setText(f"Undo {w.get_next_undo_cmd_name()}")
        else:
            self.toolBar.undoAction.setDisabled(True)
        if w.can_redo():
            self.toolBar.redoAction.setEnabled(True)
            self.toolBar.redoAction.setText(f"Redo {w.get_next_redo_cmd_name()}")
        else:
            self.toolBar.redoAction.setDisabled(True)

    def on_canvas_add(self, idx: int, w: IplotQtCanvas):
        """
        Connect the `on_cmd_done` signal of the canvas widget to our `on_cmd_done` signal.
        """
        w.cmdDone.connect(partial(self.on_cmd_done, w))

    def on_cmd_done(self, w: IplotQtCanvas, cmd: IplotCommand):
        """
        Whenever a command is done by a canvas widget, it emits that signal.
        We handle it by checking the history and setting the appropriate style, text of
        the undo/redo buttons.
        """
        self.check_history(w)
        self.toolBar.undoAction.setText(f"Undo {cmd.name}")

    def update_canvas_preferences(self):
        w = self.canvasStack.currentWidget()
        with w.view_retainer():
            w.refresh()
        self.prefWindow.set_canvas_from_preferences()
        self.prefWindow.post_applied()

    def reset_prefs(self):
        idx = self.canvasStack.currentIndex()
        self.prefWindow.reset_prefs(idx)
        self.prefWindow.formsStack.currentWidget().widgetMapper.revert()
        self.prefWindow.update()

    def re_draw(self):
        """
        Manually reset the preferences and draw the canvas object.
        The preferences forms shall reflect the current state of the canvas object.
        """
        w = self.canvasStack.currentWidget()
        idx = self.canvasStack.currentIndex()
        canvas = w.get_canvas()
        self.prefWindow.manual_reset(idx)
        w.reset()
        w.set_canvas(canvas)
        self.prefWindow.formsStack.currentWidget().widgetMapper.revert()
        self.prefWindow.update()

    def detach(self):
        """
        Detach/Re-attach the canvas widget from the main window.
        """
        if self.toolBar.detachAction.text() == 'Detach':
            # we detach now.
            tb_area = self.toolBarArea(self.toolBar)
            self._floatingWindow.setCentralWidget(self.canvasStack)
            self._floatingWindow.addToolBar(tb_area, self.toolBar)
            self._floatingWindow.setWindowTitle(self.windowTitle())
            self._floatingWindow.show()
            self.toolBar.detachAction.setText('Reattach')
        elif self.toolBar.detachAction.text() == 'Reattach':
            # we attach now.
            self.toolBar.detachAction.setText('Detach')
            tb_area = self._floatingWindow.toolBarArea(self.toolBar)
            self.setCentralWidget(self.canvasStack)
            self.addToolBar(tb_area, self.toolBar)
            self._floatingWindow.hide()

    def showEvent(self, event: QShowEvent):
        """
        Updates the style, text on the undo/redo buttons
        """
        super().showEvent(event)
        for i in range(self.canvasStack.count()):
            self.check_history(self.canvasStack.widget(i))
        super().showEvent(event)

    def closeEvent(self, event: QCloseEvent):
        """
        Special handling of the close event is done to close the preferences window if it is visible.
        This seems necessary, else qt might close the main window prior to closing this window and that would
        cause some inconsistency when exiting the app.
        """
        if self.prefWindow.isVisible():
            self.prefWindow.close()
        super().closeEvent(event)
