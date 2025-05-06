"""
This module is deprecated and unused.
"""

# Description: Support for canvas tools (zoom, pan, select, crosshair) and import/export, history management
#               and other important tools/actions.
# Author: Piotr Mazur
# Changelog:
#   Sept 2021: -Refactor qt classes [Jaswant Sai Panchumarti]
#              -Port to PySide2 [Jaswant Sai Panchumarti]


from functools import partial
import typing

from PySide6.QtCore import QMargins, Signal
from PySide6.QtWidgets import QSizePolicy, QToolBar, QWidget
from PySide6.QtGui import QAction, QActionGroup

from iplotlib.core.canvas import Canvas
from iplotlib.qt.utils.icon_loader import create_icon

from iplotLogging import setupLogger as Sl

logger = Sl.get_logger(__name__)


class IplotQtCanvasToolbar(QToolBar):
    toolActivated = Signal(str)

    def __init__(self, parent: typing.Optional[QWidget] = None):
        super().__init__(parent=parent)

        self._margins = QMargins()
        self._szPolicy = QSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Maximum)

        self.layout().setContentsMargins(self._margins)
        self.setSizePolicy(self._szPolicy)

        # Interactive plot actions.
        self._actions = QActionGroup(self)
        self._actions.setExclusive(True)
        for tool_name in [Canvas.MOUSE_MODE_SELECT,
                          Canvas.MOUSE_MODE_CROSSHAIR,
                          Canvas.MOUSE_MODE_PAN,
                          Canvas.MOUSE_MODE_ZOOM,
                          Canvas.MOUSE_MODE_DIST,
                          Canvas.MOUSE_MODE_MARKER]:
            tool_action = QAction(tool_name[3:], parent=self)
            tool_action.setCheckable(True)
            tool_action.setActionGroup(self._actions)
            tool_action.triggered.connect(partial(self.toolActivated.emit, tool_name))
            self.addAction(tool_action)

        self.addSeparator()

        # Statistics
        self.statistics = QAction(create_icon('stats_icon'), 'Statistics', self)
        self.addAction(self.statistics)
        self.addSeparator()

        # Command-history management
        self.undoAction = QAction(create_icon('undo'), '&Undo', self)
        self.redoAction = QAction(create_icon('redo'), '&Redo', self)
        self.addAction(self.undoAction)
        self.addAction(self.redoAction)

        # Saving, etc..
        self.importAction = QAction(create_icon('open_file'), '&Import Workspace', self)
        self.exportAction = QAction(create_icon('save_as'), '&Export Workspace', self)
        self.exportDataAction = QAction(create_icon('export'), '&Export Data', self)
        self.addAction(self.importAction)
        self.addAction(self.exportAction)
        self.addAction(self.exportDataAction)

        # Draw..
        self.redrawAction = QAction(create_icon('rotate180'), '&Redraw', self)
        # self.addAction(self.redrawAction)

        # Configuration..
        self.configureAction = QAction(create_icon('options', 'svg'), '&Preferences')
        self.addAction(self.configureAction)

        # Detach..
        self.detachAction = QAction('Detach', self)
        self.addAction(self.detachAction)
