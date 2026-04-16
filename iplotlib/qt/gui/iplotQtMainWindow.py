"""
A main window with a collection of iplotlib canvases and a helpful toolbar.
"""

# Author: Jaswant Sai Panchumarti

from functools import partial
import typing

from PySide6.QtCore import QItemSelectionModel, QMargins, Qt, Signal
from PySide6.QtWidgets import QApplication, QMainWindow, QWidget

from PySide6.QtCore import QMargins, Qt, Signal
from PySide6.QtWidgets import QApplication, QFileDialog, QMainWindow, QWidget

from PySide6.QtGui import QCloseEvent, QShowEvent
from iplotlib.core.command import IplotCommand
from iplotlib.core.signal import Signal as IplotSignal

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
        self.prefWindow.onDiscard.connect(self.discard_prefs)

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
        self.toolBar.statistics.triggered.connect(self.show_stats)
        self.toolBar.toolActivated.connect(
            lambda tool_name:
            [self.canvasStack.widget(i).set_mouse_mode(tool_name) for i in range(self.canvasStack.count())])
        self.canvasStack.canvasAdded.connect(self.on_canvas_add)
        self.canvasStack.currentChanged.connect(lambda idx: self.check_history(self.canvasStack.widget(idx)))
        self.toolBar.saveImageAction.triggered.connect(self.save_canvas_image)
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
        # Computation of the statistics after undo operation
        w.stats(w.get_canvas())
        QApplication.restoreOverrideCursor()
        self.check_history(w)

    def redo(self):
        w = self.canvasStack.currentWidget()
        if not w:
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        w.redo()
        # Computation of the statistics after redo operation
        w.stats(w.get_canvas())
        QApplication.restoreOverrideCursor()
        self.check_history(w)

    def show_stats(self):
        w = self.canvasStack.currentWidget()
        if not w:
            return
        w.show_stats()

    def save_canvas_image(self):
        w = self.canvasStack.currentWidget()
        if not w:
            return
        file_filter = "PNG Image (*.png);;SVG Image (*.svg);;JPEG Image (*.jpg *.jpeg)"
        filename, selected_filter = QFileDialog.getSaveFileName(
            self, "Save Canvas as Image", "", file_filter)
        if filename:
            if not any(filename.lower().endswith(ext) for ext in ('.png', '.svg', '.jpg', '.jpeg')):
                if 'SVG' in selected_filter:
                    filename += '.svg'
                elif 'JPEG' in selected_filter:
                    filename += '.jpg'
                else:
                    filename += '.png'
            w.save_canvas_image(filename)

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
        w.openPlotPreferences.connect(self._open_plot_preferences)

    def on_cmd_done(self, w: IplotQtCanvas, cmd: IplotCommand):
        """
        Whenever a command is done by a canvas widget, it emits that signal.
        We handle it by checking the history and setting the appropriate style, text of
        the undo/redo buttons.
        """
        self.check_history(w)
        self.toolBar.undoAction.setText(f"Undo {cmd.name}")

    def _open_plot_preferences(self, target):
        """Open preferences window and navigate to the given Plot or Signal in the tree.
        Collapses all other items and expands only the relevant path."""
        tree = self.prefWindow.treeView
        model = tree.model()
        if not model:
            return
        is_signal = isinstance(target, IplotSignal)
        for canvas_row in range(model.rowCount()):
            canvas_idx = model.index(canvas_row, 0)
            for col_row in range(model.rowCount(canvas_idx)):
                col_idx = model.index(col_row, 0, canvas_idx)
                for plot_row in range(model.rowCount(col_idx)):
                    plot_idx = model.index(plot_row, 0, col_idx)
                    if not is_signal and plot_idx.data(Qt.ItemDataRole.UserRole) is target:
                        self._show_pref_at(tree, canvas_idx, col_idx, plot_idx, plot_idx)
                        return
                    if is_signal:
                        for child_row in range(model.rowCount(plot_idx)):
                            child_idx = model.index(child_row, 0, plot_idx)
                            if child_idx.data(Qt.ItemDataRole.UserRole) is target:
                                self._show_pref_at(tree, canvas_idx, col_idx, plot_idx, child_idx)
                                return

    def _show_pref_at(self, tree, canvas_idx, col_idx, plot_idx, target_idx):
        """Show preferences window with tree collapsed except the path to target_idx."""
        self.prefWindow.show()
        self.prefWindow.raise_()
        self.prefWindow.activateWindow()
        self.prefWindow._refresh_signal_icons()
        tree.collapseAll()
        tree.expand(canvas_idx)
        tree.expand(col_idx)
        tree.expand(plot_idx)
        tree.selectionModel().clearSelection()
        tree.selectionModel().select(target_idx, QItemSelectionModel.SelectionFlag.Select)
        tree.scrollTo(target_idx)
        self.prefWindow.set_canvas_from_preferences()

    def update_canvas_preferences(self):
        w = self.canvasStack.currentWidget()
        with w.view_retainer():
            w.refresh()
        self.prefWindow.set_canvas_from_preferences()
        self.prefWindow.post_applied()

    def reset_prefs(self):
        w = self.canvasStack.currentWidget()
        with w.view_retainer():
            w.refresh()
        self.prefWindow.set_canvas_from_preferences()
        self.prefWindow.update()

    def discard_prefs(self):
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
