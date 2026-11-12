"""
This module is deprecated and unused.
"""

# Description: Support for canvas tools (zoom, pan, select, crosshair) and import/export, history management
#               and other important tools/actions.
# Author: Piotr Mazur
# Changelog:
#   Sept 2021: -Refactor qt classes [Jaswant Sai Panchumarti]
#              -Port to PySide2 [Jaswant Sai Panchumarti]


import typing

from PySide6.QtCore import QEvent, QMargins, Signal
from PySide6.QtWidgets import QSizePolicy, QToolBar, QWidget
from PySide6.QtGui import QAction, QActionGroup

from iplotlib.core.canvas import Canvas
from iplotlib.qt.utils.icon_loader import create_icon
from iplotlib.qt.utils.icon_sizing import FontScaledIcons
from iplotlib.qt.utils.palette import theme_colors

from iplotLogging import setupLogger as Sl

logger = Sl.get_logger(__name__)


class IplotQtCanvasToolbar(FontScaledIcons, QToolBar):
    toolActivated = Signal(str)

    def __init__(self, parent: typing.Optional[QWidget] = None):
        super().__init__(parent=parent)

        # The actions with a packaged icon and the colours they are drawn in, drawn again in those of a new palette
        # (see changeEvent).
        self._packaged_icons = {}
        self._icons_theme = theme_colors()
        self._margins = QMargins()
        self._szPolicy = QSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Maximum)

        self.layout().setContentsMargins(self._margins)
        self.setSizePolicy(self._szPolicy)
        # The style sizes the icons from the screen DPI, not from the font.
        self.apply_icon_size()

        # Interactive plot actions.
        self._actions = QActionGroup(self)
        self._actions.setExclusive(True)
        self._tool_actions = {}
        for tool_name in [Canvas.MOUSE_MODE_SELECT,
                          Canvas.MOUSE_MODE_CROSSHAIR,
                          Canvas.MOUSE_MODE_PAN,
                          Canvas.MOUSE_MODE_ZOOM,
                          Canvas.MOUSE_MODE_DIST,
                          Canvas.MOUSE_MODE_MARKER,
                          Canvas.MOUSE_MODE_RULER]:
            tool_action = QAction(tool_name[3:], parent=self)
            tool_action.setCheckable(True)
            tool_action.setActionGroup(self._actions)
            # `triggered` passes `checked` on PySide6 6.10 but not 6.6; *_ absorbs either.
            tool_action.triggered.connect(lambda *_, n=tool_name: self.toolActivated.emit(n))
            self.addAction(tool_action)
            self._tool_actions[tool_name] = tool_action

        self.addSeparator()

        # Statistics
        self.statistics = self._packaged_action('stats', 'svg', 'Statistics')
        self.addAction(self.statistics)

        self.minimapAction = self._packaged_action('minimap', 'svg', 'Mini-map')
        self.minimapAction.setCheckable(True)
        self.minimapAction.setEnabled(False)
        self.minimapAction.setToolTip('Show mini-map (available when a single plot is visible, '
                                      'except while streaming)')
        self.addAction(self.minimapAction)
        self.addSeparator()

        # Command-history management
        self.undoAction = self._packaged_action('undo', 'svg', '&Undo')
        self.redoAction = self._packaged_action('redo', 'svg', '&Redo')
        self.addAction(self.undoAction)
        self.addAction(self.redoAction)

        # Restore every plot to the range captured at draw time.
        self.homeAction = self._packaged_action('home', 'svg', '&Home')
        self.homeAction.setToolTip('Resets all plots to the original view')
        self.addAction(self.homeAction)

        # Saving, etc..
        self.importAction = self._packaged_action('open_file', 'svg', '&Import Workspace')
        self.exportAction = self._packaged_action('save_as', 'svg', '&Export Workspace')
        self.exportDataAction = self._packaged_action('export', 'svg', '&Export Data')
        self.addAction(self.importAction)
        self.addAction(self.exportAction)
        self.addAction(self.exportDataAction)

        # Save canvas as image
        self.saveImageAction = self._packaged_action('screenshot', 'svg', '&Save Canvas as Image')
        self.addAction(self.saveImageAction)

        # Pulse creation. Hidden by default — the host application decides
        # whether to show it based on data-source capabilities (see
        # MTMainWindow feature-gating against UdaAccess.is_write_capable()).
        self.createPulseAction = self._packaged_action('create_pulse', 'svg', '&Create Pulse')
        self.createPulseAction.setToolTip('Create Pulse')
        self.createPulseAction.setStatusTip(
            'Create a UDA pulse from the currently visible time range')
        self.createPulseAction.setVisible(False)
        self.addAction(self.createPulseAction)

        # Pulse update. Hidden by default; same gating as createPulseAction.
        self.updatePulseAction = self._packaged_action('update_pulse', 'svg', '&Update Pulse')
        self.updatePulseAction.setToolTip('Update Pulse')
        self.updatePulseAction.setStatusTip(
            'Search for an existing UDA pulse and update its time range, status or description')
        self.updatePulseAction.setVisible(False)
        self.addAction(self.updatePulseAction)

        # Draw..
        self.redrawAction = self._packaged_action('rotate180', 'svg', '&Redraw')
        # self.addAction(self.redrawAction)

        # Configuration..
        self.configureAction = self._packaged_action('options', 'svg', '&Preferences')
        self.addAction(self.configureAction)

        # Detach..
        self.detachAction = QAction('Detach', self)
        self.addAction(self.detachAction)

    def _packaged_action(self, icon: str, ext: str, text: str) -> QAction:
        action = QAction(create_icon(icon, ext), text, self)
        self._packaged_icons[action] = (icon, ext)
        return action

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.PaletteChange and theme_colors() != self._icons_theme:
            self._icons_theme = theme_colors()
            for action, (icon, ext) in self._packaged_icons.items():
                action.setIcon(create_icon(icon, ext))
