"""Smoke tests for IplotQtMainWindow, its toolbar and the preferences window.

These exercise the widget-level integration that sits on top of the core:
- the main window boots with a canvas assembly and a toolbar;
- the toolbar exposes the mouse-mode actions, undo/redo, save image, etc.;
- the preferences window builds forms for Canvas / Plot / Signal types and
  reflects the canvas hierarchy in its tree.

A broken toolbar or preferences window is invisible in rendering tests
(nothing on the canvas changes), so these invariants need their own pin.
"""

import os
import unittest

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QStandardItemModel

from iplotlib.core.canvas import Canvas
from iplotlib.core.plot import PlotXY
from iplotlib.core.signal import SignalXY
from iplotlib.qt.gui.iplotQtCanvasFactory import IplotQtCanvasFactory
from iplotlib.qt.gui.iplotQtMainWindow import IplotQtMainWindow
from iplotlib.qt.gui.iplotQtPreferencesWindow import IplotQtPreferencesWindow
from iplotlib.qt.testing import ensure_qapp

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')


def _canvas_with_signal() -> Canvas:
    core = Canvas(1, 1, title="main_window_test")
    x = np.linspace(0, 10, 50)
    plot = PlotXY()
    sig = SignalXY(label="s")
    sig.set_data([x, np.sin(x)])
    plot.add_signal(sig)
    core.add_plot(plot, 0)
    return core


class MainWindowSmokeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = ensure_qapp()

    def test_main_window_builds_toolbar_and_preferences(self):
        win = IplotQtMainWindow()
        try:
            self.assertIsNotNone(win.toolBar)
            self.assertIsNotNone(win.canvasStack)
            self.assertIsNotNone(win.prefWindow)

            # Toolbar exposes the actions wired in wire_connections().
            for action_name in (
                    'undoAction', 'redoAction', 'saveImageAction',
                    'importAction', 'exportAction', 'exportDataAction',
                    'redrawAction', 'detachAction', 'configureAction',
                    'statistics'):
                self.assertTrue(hasattr(win.toolBar, action_name),
                                f"toolbar is missing {action_name}")

            # Pref window is wired to the canvas assembly's model.
            self.assertIs(win.prefWindow.treeView.model(), win.canvasStack.model())
        finally:
            win.close()

    def test_add_canvas_populates_preferences_tree(self):
        win = IplotQtMainWindow()
        try:
            qt_canvas = IplotQtCanvasFactory.new('matplotlib',
                                                 canvas=_canvas_with_signal())
            qt_canvas.set_canvas(qt_canvas.get_canvas())
            win.canvasStack.addWidget(qt_canvas)
            self.app.processEvents()

            model = win.canvasStack.model()
            self.assertEqual(model.rowCount(), 1)
            canvas_item = model.item(0, 0)
            self.assertIsNotNone(canvas_item)
            # The canvas item must carry the core Canvas via UserRole so the
            # preferences forms can bind to it.
            self.assertIsInstance(canvas_item.data(Qt.ItemDataRole.UserRole), Canvas)
        finally:
            win.close()

    def test_toolbar_exposes_mouse_mode_actions(self):
        """Each canvas mouse mode has a checkable action in the toolbar."""
        win = IplotQtMainWindow()
        try:
            action_texts = {a.text() for a in win.toolBar._actions.actions()}
            # Actions are added stripping the "MM_" prefix.
            for mode in (Canvas.MOUSE_MODE_SELECT, Canvas.MOUSE_MODE_CROSSHAIR,
                         Canvas.MOUSE_MODE_PAN, Canvas.MOUSE_MODE_ZOOM,
                         Canvas.MOUSE_MODE_DIST, Canvas.MOUSE_MODE_MARKER):
                self.assertIn(mode[3:], action_texts,
                              f"{mode} action missing from toolbar")
            for a in win.toolBar._actions.actions():
                self.assertTrue(a.isCheckable())
        finally:
            win.close()


class MainWindowActionsTest(unittest.TestCase):
    """Toolbar actions must reach the active canvas widget."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.app = ensure_qapp()

    def _add_canvas(self, win):
        qt_canvas = IplotQtCanvasFactory.new('matplotlib',
                                             canvas=_canvas_with_signal())
        qt_canvas.set_canvas(qt_canvas.get_canvas())
        win.canvasStack.addWidget(qt_canvas)
        self.app.processEvents()
        return qt_canvas

    def test_save_canvas_image_writes_png(self):
        """IplotQtCanvas.save_canvas_image writes a PNG file."""
        import tempfile

        win = IplotQtMainWindow()
        try:
            qt_canvas = self._add_canvas(win)
            with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
                path = tmp.name
            try:
                qt_canvas.save_canvas_image(path)
                self.app.processEvents()
                self.assertTrue(os.path.exists(path))
                self.assertGreater(os.path.getsize(path), 0)
            finally:
                if os.path.exists(path):
                    os.remove(path)
        finally:
            win.close()

    def test_show_stats_reaches_current_widget(self):
        """show_stats on the main window forwards to the current canvas."""
        win = IplotQtMainWindow()
        try:
            self._add_canvas(win)
            # Should not raise — the canvas has signals with data, so stats
            # can be computed even without real data access.
            win.show_stats()
            self.app.processEvents()
        finally:
            win.close()

    def test_drop_history_clears_history(self):
        """drop_history on the main window wipes the current canvas's history."""
        win = IplotQtMainWindow()
        try:
            qt_canvas = self._add_canvas(win)
            win.drop_history()
            self.app.processEvents()
            self.assertFalse(qt_canvas.can_undo())
            self.assertFalse(qt_canvas.can_redo())
        finally:
            win.close()

    def test_check_history_disables_undo_redo_on_empty_stack(self):
        """With an empty history, the undo/redo actions are disabled."""
        win = IplotQtMainWindow()
        try:
            qt_canvas = self._add_canvas(win)
            win.check_history(qt_canvas)
            self.assertFalse(win.toolBar.undoAction.isEnabled())
            self.assertFalse(win.toolBar.redoAction.isEnabled())
        finally:
            win.close()


class PreferencesWindowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = ensure_qapp()

    def test_preferences_window_registers_forms_for_all_known_types(self):
        from iplotlib.core.axis import LinearAxis
        from iplotlib.core.plot import (PlotContour, PlotContourWithSlider,
                                        PlotXY, PlotXYWithSlider)
        from iplotlib.core.signal import SignalContour, SignalXY

        win = IplotQtPreferencesWindow(QStandardItemModel())
        try:
            expected = {Canvas, PlotXY, PlotXYWithSlider, PlotContour,
                        PlotContourWithSlider, LinearAxis, SignalXY,
                        SignalContour, type(None)}
            self.assertEqual(expected, set(win._forms.keys()))
        finally:
            win.close()

    def test_preferences_window_tree_reflects_canvas_assembly(self):
        """Showing the preferences window expands the tree of the canvas."""
        win = IplotQtMainWindow()
        try:
            qt_canvas = IplotQtCanvasFactory.new('matplotlib',
                                                 canvas=_canvas_with_signal())
            qt_canvas.set_canvas(qt_canvas.get_canvas())
            win.canvasStack.addWidget(qt_canvas)
            self.app.processEvents()

            win.prefWindow.show()
            self.app.processEvents()
            self.assertTrue(win.prefWindow.treeView.isExpanded(
                win.prefWindow.treeView.model().index(0, 0)))
            # Disconnect the onDiscard → discard_prefs path before closing:
            # canvases built directly from the core API (without the MINT
            # pipeline) have signals whose uid is None, and discard_prefs'
            # merge path tries to build "uid + ';' + name" on them. That's a
            # pre-existing edge case in compute_signal_uniqkey (see
            # follow-up issue) — we sidestep it here so the test logs
            # stay clean.
            try:
                win.prefWindow.onDiscard.disconnect(win.discard_prefs)
            except (RuntimeError, TypeError):
                pass
            win.prefWindow.close()
        finally:
            win.close()


class MinimapStateTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = ensure_qapp()

    def test_default_state_is_off(self):
        c = Canvas(1, 1)
        self.assertFalse(c.show_minimap)
        self.assertIsNone(c.get_minimap_baseline())

    def test_eligibility_single_plot(self):
        c = _canvas_with_signal()
        self.assertTrue(c.is_minimap_eligible())
        self.assertIsNotNone(c.get_minimap_target_plot())

    def test_eligibility_multiple_plots(self):
        c = Canvas(2, 1)
        for _ in range(2):
            p = PlotXY()
            sig = SignalXY(label='s')
            sig.set_data([np.linspace(0, 1, 10), np.zeros(10)])
            p.add_signal(sig)
            c.add_plot(p, 0)
        self.assertFalse(c.is_minimap_eligible())

    def test_eligibility_with_focus_plot(self):
        c = Canvas(2, 1)
        for _ in range(2):
            p = PlotXY()
            sig = SignalXY(label='s')
            sig.set_data([np.linspace(0, 1, 10), np.zeros(10)])
            p.add_signal(sig)
            c.add_plot(p, 0)
        c.focus_plot = c.plots[0][0]
        self.assertTrue(c.is_minimap_eligible())

    def test_eligibility_rejects_non_xy_plots(self):
        from iplotlib.core.plot import PlotContour, PlotXYWithSlider
        c = Canvas(1, 1)
        c.add_plot(PlotContour(), 0)
        self.assertFalse(c.is_minimap_eligible())

        c2 = Canvas(1, 1)
        c2.add_plot(PlotXYWithSlider(), 0)
        self.assertFalse(c2.is_minimap_eligible())

    def test_baseline_snapshot_roundtrip(self):
        c = Canvas(1, 1)
        c.snapshot_minimap_baseline(10, 20)
        self.assertEqual(c.get_minimap_baseline(), (10, 20))
        c.snapshot_minimap_baseline(None, None)
        self.assertIsNone(c.get_minimap_baseline())

    def test_show_minimap_serialization_roundtrip(self):
        c = _canvas_with_signal()
        c.show_minimap = True
        d = c.to_dict()
        self.assertTrue(d['show_minimap'])
        restored = Canvas.from_dict(d)
        self.assertTrue(restored.show_minimap)

    def test_old_workspace_without_show_minimap_defaults_off(self):
        c = _canvas_with_signal()
        d = c.to_dict()
        d.pop('show_minimap', None)
        restored = Canvas.from_dict(d)
        self.assertFalse(restored.show_minimap)


class MinimapToolbarTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = ensure_qapp()

    def _add_canvas(self, win, core=None):
        qt_canvas = IplotQtCanvasFactory.new('matplotlib',
                                             canvas=core or _canvas_with_signal())
        qt_canvas.set_canvas(qt_canvas.get_canvas())
        win.canvasStack.addWidget(qt_canvas)
        self.app.processEvents()
        return qt_canvas

    def test_minimap_action_exists_and_disabled_by_default(self):
        win = IplotQtMainWindow()
        try:
            self.assertIsNotNone(win.toolBar.minimapAction)
            self.assertTrue(win.toolBar.minimapAction.isCheckable())
            self.assertFalse(win.toolBar.minimapAction.isEnabled())
        finally:
            win.close()

    def test_minimap_action_enabled_for_single_plot_canvas(self):
        win = IplotQtMainWindow()
        try:
            self._add_canvas(win)
            win.refresh_minimap_availability()
            self.assertTrue(win.toolBar.minimapAction.isEnabled())
        finally:
            win.close()

    def test_minimap_action_disabled_for_multi_plot_canvas(self):
        win = IplotQtMainWindow()
        try:
            multi = Canvas(2, 1)
            for _ in range(2):
                p = PlotXY()
                sig = SignalXY(label='s')
                sig.set_data([np.linspace(0, 1, 10), np.zeros(10)])
                p.add_signal(sig)
                multi.add_plot(p, 0)
            self._add_canvas(win, multi)
            win.refresh_minimap_availability()
            self.assertFalse(win.toolBar.minimapAction.isEnabled())
        finally:
            win.close()

    def test_toggle_minimap_updates_canvas_flag(self):
        win = IplotQtMainWindow()
        try:
            qt_canvas = self._add_canvas(win)
            win.refresh_minimap_availability()
            win.toolBar.minimapAction.setChecked(True)
            self.app.processEvents()
            self.assertTrue(qt_canvas.get_canvas().show_minimap)
            win.toolBar.minimapAction.setChecked(False)
            self.app.processEvents()
            self.assertFalse(qt_canvas.get_canvas().show_minimap)
        finally:
            win.close()


class MinimapFontSizeTest(unittest.TestCase):
    """The minimap must reuse the main plot's font size (issue #141), for both
    backends, so its ticks stay legible on high-DPI screens and follow the
    single font-size setting instead of a hard-coded value."""

    BACKENDS = ('matplotlib', 'pyqt')

    @classmethod
    def setUpClass(cls) -> None:
        cls.app = ensure_qapp()

    def _qt_canvas(self, backend, core):
        qt_canvas = IplotQtCanvasFactory.new(backend, canvas=core)
        qt_canvas.set_canvas(qt_canvas.get_canvas())
        self.app.processEvents()
        return qt_canvas

    def test_minimap_inherits_canvas_font_size(self):
        for backend in self.BACKENDS:
            with self.subTest(backend=backend):
                core = _canvas_with_signal()
                core.font_size = 14
                qt_canvas = self._qt_canvas(backend, core)
                try:
                    target = core.get_minimap_target_plot()
                    self.assertEqual(qt_canvas._minimap_font_size(target), 14)
                finally:
                    qt_canvas.deleteLater()

    def test_minimap_plot_font_size_overrides_canvas(self):
        for backend in self.BACKENDS:
            with self.subTest(backend=backend):
                core = _canvas_with_signal()
                core.font_size = 10
                target = core.get_minimap_target_plot()
                target.font_size = 22
                qt_canvas = self._qt_canvas(backend, core)
                try:
                    self.assertEqual(qt_canvas._minimap_font_size(target), 22)
                finally:
                    qt_canvas.deleteLater()

    def test_minimap_font_size_falls_back_to_default(self):
        for backend in self.BACKENDS:
            with self.subTest(backend=backend):
                core = _canvas_with_signal()  # no font_size set anywhere
                qt_canvas = self._qt_canvas(backend, core)
                try:
                    target = core.get_minimap_target_plot()
                    self.assertEqual(qt_canvas._minimap_font_size(target), 8)
                finally:
                    qt_canvas.deleteLater()


if __name__ == '__main__':
    unittest.main()
