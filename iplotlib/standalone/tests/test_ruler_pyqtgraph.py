"""End-to-end tests for the Ruler feature on the pyqtgraph backend.

Exercises the canvas widget side: placing a ruler programmatically should
mirror what a left-click does, removing one should keep parser state in sync
with Plot.rulers, and reloading a canvas with rulers must repaint them back
on the impl plot and on the ruler window.
"""

import os
import unittest

import numpy as np

from iplotlib.core.canvas import Canvas
from iplotlib.core.plot import PlotXY
from iplotlib.core.ruler import Ruler
from iplotlib.core.signal import SignalXY
from iplotlib.impl.pyqtgraph.pyQtRuler import pyQtRuler
from iplotlib.impl.pyqtgraph.qt.qtPyQtGraphCanvas import QtPyQtGraphCanvas
from iplotlib.qt.testing import ensure_qapp

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')


def _build_canvas() -> Canvas:
    c = Canvas(1, 1, title="ruler_test")
    x = np.linspace(0, 10, 50)
    plot = PlotXY()
    sig = SignalXY(label="s")
    sig.set_data([x, np.sin(x)])
    plot.add_signal(sig)
    c.add_plot(plot, 0)
    return c


class RulerPyQtGraphEndToEndTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = ensure_qapp()

    def setUp(self):
        self.canvas = _build_canvas()
        self.widget = QtPyQtGraphCanvas(canvas=self.canvas)
        self.plot = self.canvas.plots[0][0]
        self.impl_plot = self.widget._get_impl_plot_for_plot(self.plot)
        self.assertIsNotNone(self.impl_plot, "Plot impl item must be available after set_canvas")

    def tearDown(self):
        self.widget._ruler_window.close()
        self.widget.deleteLater()

    def test_add_ruler_populates_data_model_and_backend_and_window(self):
        self.widget._add_ruler_at(self.impl_plot, self.plot, 2.5, 0.5)
        self.assertEqual([r.name for r in self.plot.rulers], ['A'])
        self.assertEqual(self.plot.rulers[0].xy, (2.5, 0.5))
        parser_rulers = self.widget._parser.get_rulers(self.impl_plot)
        self.assertEqual(len(parser_rulers), 1)
        self.assertIsInstance(parser_rulers[0], pyQtRuler)
        self.assertEqual(self.widget._ruler_window.table.rowCount(), 1)

    def test_add_two_rulers_assigns_distinct_names(self):
        self.widget._add_ruler_at(self.impl_plot, self.plot, 1.0, 0.1)
        self.widget._add_ruler_at(self.impl_plot, self.plot, 3.0, 0.3)
        self.assertEqual([r.name for r in self.plot.rulers], ['A', 'B'])

    def test_add_rulers_picks_different_default_colors(self):
        self.widget._add_ruler_at(self.impl_plot, self.plot, 1.0, 0.1)
        self.widget._add_ruler_at(self.impl_plot, self.plot, 3.0, 0.3)
        self.assertNotEqual(self.plot.rulers[0].color, self.plot.rulers[1].color)

    def test_delete_ruler_removes_from_plot_parser_and_window(self):
        self.widget._add_ruler_at(self.impl_plot, self.plot, 1.0, 0.1)
        self.widget._add_ruler_at(self.impl_plot, self.plot, 3.0, 0.3)

        self.widget.delete_ruler('A', (self.plot.col, self.plot.row), True)
        self.widget._ruler_window.remove_row_by_name('A', (self.plot.col, self.plot.row))

        self.assertEqual([r.name for r in self.plot.rulers], ['B'])
        self.assertEqual([r.name for r in self.widget._parser.get_rulers(self.impl_plot)], ['B'])
        self.assertEqual(self.widget._ruler_window.table.rowCount(), 1)
        self.assertEqual(self.widget._ruler_window.table.item(0, 0).text(), 'B')

    def test_toggle_ruler_visibility_updates_model_and_backend(self):
        self.widget._add_ruler_at(self.impl_plot, self.plot, 1.0, 0.1)
        self.widget.toggle_ruler_visibility('A', (self.plot.col, self.plot.row), False)
        self.assertFalse(self.plot.rulers[0].visible)
        backend_ruler = self.widget._parser.get_rulers(self.impl_plot)[0]
        self.assertFalse(backend_ruler.v_line.isVisible())

    def test_change_ruler_color_updates_model_and_backend(self):
        self.widget._add_ruler_at(self.impl_plot, self.plot, 1.0, 0.1)
        self.widget.change_ruler_color('A', (self.plot.col, self.plot.row), '#FF0000')
        self.assertEqual(self.plot.rulers[0].color, '#FF0000')
        self.assertEqual(self.widget._parser.get_rulers(self.impl_plot)[0].color, '#FF0000')

    def test_repaint_after_setting_canvas_with_rulers(self):
        """A canvas loaded from JSON already has Plot.rulers; reopening it must
        recreate the on-screen ruler items and repopulate the ruler window."""
        c2 = _build_canvas()
        plot2 = c2.plots[0][0]
        plot2.add_ruler(Ruler(name='X', xy=(2.0, 0.2), color='#00FF00', visible=True))
        plot2.add_ruler(Ruler(name='Y', xy=(5.0, -0.5), color='#0000FF', visible=False))

        self.widget.set_canvas(c2)

        impl_plot = self.widget._get_impl_plot_for_plot(plot2)
        self.assertIsNotNone(impl_plot)
        names = sorted(r.name for r in self.widget._parser.get_rulers(impl_plot))
        self.assertEqual(names, ['X', 'Y'])
        self.assertEqual(self.widget._ruler_window.table.rowCount(), 2)

        # Visibility preserved from the model.
        backend_y = next(r for r in self.widget._parser.get_rulers(impl_plot) if r.name == 'Y')
        self.assertFalse(backend_y.v_line.isVisible())

    def test_loading_a_canvas_without_rulers_clears_previous_rulers(self):
        """Place rulers on the current canvas, then load a different canvas
        that has none. The backend ruler list, the window table and the
        on-screen items must all be cleared — otherwise stale rulers visually
        survive across workspace reloads (issue reproduced manually in MINT)."""
        self.widget._add_ruler_at(self.impl_plot, self.plot, 2.5, 0.5)
        self.widget._add_ruler_at(self.impl_plot, self.plot, 7.5, -0.5)
        self.assertEqual(len(self.widget._parser._rulers), 2)
        self.assertEqual(self.widget._ruler_window.table.rowCount(), 2)

        clean_canvas = _build_canvas()
        self.widget.set_canvas(clean_canvas)

        self.assertEqual(self.widget._parser._rulers, [])
        self.assertEqual(self.widget._ruler_window.table.rowCount(), 0)

    def test_mint_import_flow_clears_stale_rulers(self):
        """Reproduce MINT's import_dict flow: external code calls
        ``parser.clear()`` first (it is what mtMainWindow does at line ~423),
        and only later does set_canvas() run. The ruler window must end up
        empty and parser._rulers must contain nothing stale."""
        self.widget._add_ruler_at(self.impl_plot, self.plot, 2.5, 0.5)
        self.widget._add_ruler_at(self.impl_plot, self.plot, 7.5, -0.5)

        # Simulate what MTMainWindow.import_dict does before swapping canvases.
        self.widget._parser.clear()
        self.assertEqual(self.widget._parser._rulers, [])

        clean_canvas = _build_canvas()
        self.widget.set_canvas(clean_canvas)

        self.assertEqual(self.widget._parser._rulers, [])
        self.assertEqual(self.widget._ruler_window.table.rowCount(), 0)

    def test_ruler_on_second_plot_uses_correct_plot_id(self):
        """Stacked plots must get distinct plot_ids so delete/visibility/color
        operations route to the correct plot."""
        c = Canvas(2, 1, title="multi_plot")
        x = np.linspace(0, 10, 50)
        for _ in range(2):
            p = PlotXY()
            s = SignalXY(label="s")
            s.set_data([x, np.sin(x)])
            p.add_signal(s)
            c.add_plot(p, 0)
        widget = QtPyQtGraphCanvas(canvas=c)
        try:
            plot_one, plot_two = c.plots[0]
            impl_one = widget._get_impl_plot_for_plot(plot_one)
            impl_two = widget._get_impl_plot_for_plot(plot_two)
            widget._add_ruler_at(impl_one, plot_one, 1.0, 0.1)
            widget._add_ruler_at(impl_two, plot_two, 2.0, 0.2)

            self.assertEqual(widget._ruler_window._rows[0]['plot_id'], (1, 1))
            self.assertEqual(widget._ruler_window._rows[1]['plot_id'], (2, 1))

            widget.delete_ruler('B', (2, 1), True)
            self.assertEqual([r.name for r in plot_two.rulers], [])
            self.assertEqual([r.name for r in plot_one.rulers], ['A'])
        finally:
            widget._ruler_window.close()
            widget.deleteLater()

    def test_ruler_artifacts_detach_from_scene_on_remove(self):
        """Even if Python references linger, the ruler's QGraphicsItems must
        not stay attached to their parent axes / viewbox after remove() —
        otherwise the dotted lines and X/Y label boxes survive a canvas
        reload visually (this was the regression seen in MINT)."""
        self.widget._add_ruler_at(self.impl_plot, self.plot, 2.5, 0.5)
        ruler = self.widget._parser._rulers[0]
        items = (ruler.v_line, ruler.h_line, ruler.name_label,
                 ruler.x_label, ruler.y_label)

        # Sanity: all items belong to some scene before remove().
        self.assertTrue(all(item.scene() is not None for item in items))

        ruler.remove()

        # After remove() the items must be fully detached: no scene, no parent.
        for item in items:
            self.assertIsNone(item.scene(),
                              f"{type(item).__name__} still attached to a scene after remove()")
            self.assertIsNone(item.parentItem(),
                              f"{type(item).__name__} still parented after remove()")


class RulerPyQtGraphRegressionTest(unittest.TestCase):
    """Sanity: existing crosshair / cursor wiring stays intact when the ruler
    plumbing is added. A regression here would mean Crosshair mode broke."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.app = ensure_qapp()

    def test_crosshair_still_activates(self):
        widget = QtPyQtGraphCanvas(canvas=_build_canvas())
        try:
            widget.set_mouse_mode(Canvas.MOUSE_MODE_CROSSHAIR)
            self.assertTrue(widget._parser._cursor_active)
        finally:
            widget.deleteLater()

    def test_marker_window_remains_independent_from_ruler_window(self):
        widget = QtPyQtGraphCanvas(canvas=_build_canvas())
        try:
            self.assertIsNotNone(widget._marker_window)
            self.assertIsNotNone(widget._ruler_window)
            self.assertIsNot(widget._marker_window, widget._ruler_window)
        finally:
            widget.deleteLater()


if __name__ == '__main__':
    unittest.main()
