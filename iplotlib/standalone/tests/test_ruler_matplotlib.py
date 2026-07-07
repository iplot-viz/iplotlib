"""End-to-end tests for the Ruler feature on the matplotlib backend.

Mirrors test_ruler_pyqtgraph.py to guarantee both backends behave the same
from the perspective of Plot.rulers / parser._rulers / window contents and
support the same operations (add, delete, toggle visibility, change color,
repaint on canvas reload).
"""

import os
import unittest

import numpy as np

from iplotlib.core.canvas import Canvas
from iplotlib.core.plot import PlotXY
from iplotlib.core.ruler import Ruler
from iplotlib.core.signal import SignalXY
from iplotlib.impl.matplotlib.iplotMplRuler import iplotMplRuler
from iplotlib.impl.matplotlib.qt.qtMatplotlibCanvas import QtMatplotlibCanvas
from iplotlib.qt.testing import ensure_qapp

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')


def _build_canvas() -> Canvas:
    c = Canvas(1, 1, title="ruler_test_mpl")
    x = np.linspace(0, 10, 50)
    plot = PlotXY()
    sig = SignalXY(label="s")
    sig.set_data([x, np.sin(x)])
    plot.add_signal(sig)
    c.add_plot(plot, 0)
    return c


class RulerMatplotlibEndToEndTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = ensure_qapp()

    def setUp(self):
        self.canvas = _build_canvas()
        self.widget = QtMatplotlibCanvas(canvas=self.canvas)
        self.plot = self.canvas.plots[0][0]
        self.impl_plot = self.widget._get_impl_plot_for_plot(self.plot)
        self.assertIsNotNone(self.impl_plot, "Axes for plot must be available after set_canvas")

    def tearDown(self):
        self.widget._ruler_window.close()
        self.widget.deleteLater()

    def test_add_ruler_populates_data_model_and_backend_and_window(self):
        self.widget._add_ruler_at(self.impl_plot, self.plot, 2.5, 0.5)
        self.assertEqual([r.name for r in self.plot.rulers], ['A'])
        self.assertEqual(self.plot.rulers[0].xy, (2.5, 0.5))
        parser_rulers = self.widget._parser.get_rulers(self.impl_plot)
        self.assertEqual(len(parser_rulers), 1)
        self.assertIsInstance(parser_rulers[0], iplotMplRuler)
        self.assertEqual(self.widget._ruler_window.table.rowCount(), 1)

    def test_add_ruler_populates_signal_values_in_window(self):
        self.widget._add_ruler_at(self.impl_plot, self.plot, 2.5, 0.5)
        text = self.widget._ruler_window._rows[0]['signal_values']
        self.assertTrue(text.startswith('s: '), text)
        self.assertAlmostEqual(float(text.split(': ')[1]), np.sin(2.5), delta=0.15)

    def test_ruler_off_the_signal_has_empty_signal_values(self):
        # X well beyond the data extent (0..10) -> no signal under the ruler.
        self.widget._add_ruler_at(self.impl_plot, self.plot, 100.0, 0.0)
        self.assertEqual(self.widget._ruler_window._rows[0]['signal_values'], '')

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

    def test_toggle_ruler_visibility_updates_model_and_backend(self):
        self.widget._add_ruler_at(self.impl_plot, self.plot, 1.0, 0.1)
        self.widget.toggle_ruler_visibility('A', (self.plot.col, self.plot.row), False)
        self.assertFalse(self.plot.rulers[0].visible)
        self.assertFalse(self.widget._parser.get_rulers(self.impl_plot)[0].v_line.get_visible())

    def test_change_ruler_color_updates_model_and_backend(self):
        self.widget._add_ruler_at(self.impl_plot, self.plot, 1.0, 0.1)
        self.widget.change_ruler_color('A', (self.plot.col, self.plot.row), '#FF0000')
        self.assertEqual(self.plot.rulers[0].color, '#FF0000')
        # matplotlib reports colors as RGBA tuples after set_color; compare back to hex.
        from matplotlib.colors import to_hex
        impl_color = self.widget._parser.get_rulers(self.impl_plot)[0].v_line.get_color()
        self.assertEqual(to_hex(impl_color).upper(), '#FF0000')

    def test_change_ruler_font_color_updates_model_and_backend(self):
        self.widget._add_ruler_at(self.impl_plot, self.plot, 1.0, 0.1)
        self.widget.change_ruler_font_color('A', (self.plot.col, self.plot.row), '#000000')
        self.assertEqual(self.plot.rulers[0].font_color, '#000000')
        from matplotlib.colors import to_hex
        backend = self.widget._parser.get_rulers(self.impl_plot)[0]
        self.assertEqual(to_hex(backend.name_label.get_color()).upper(), '#000000')

    def test_default_font_autocontrasts_with_ruler_color(self):
        self.widget._add_ruler_at(self.impl_plot, self.plot, 1.0, 0.1, color='#ffff00')
        backend = self.widget._parser.get_rulers(self.impl_plot)[0]
        self.assertEqual(backend.name_label.get_color(), 'black')  # light ruler
        self.widget.change_ruler_color('A', (self.plot.col, self.plot.row), '#000080')
        self.assertEqual(backend.name_label.get_color(), 'white')  # dark ruler

    def test_explicit_font_color_overrides_autocontrast(self):
        self.widget._add_ruler_at(self.impl_plot, self.plot, 1.0, 0.1, color='#ffff00')
        self.widget.change_ruler_font_color('A', (self.plot.col, self.plot.row), '#123456')
        from matplotlib.colors import to_hex
        backend = self.widget._parser.get_rulers(self.impl_plot)[0]
        self.assertEqual(to_hex(backend.name_label.get_color()).upper(), '#123456')

    def test_toggle_ruler_label_hides_only_the_name_label(self):
        self.widget._add_ruler_at(self.impl_plot, self.plot, 1.0, 0.1)
        self.widget.toggle_ruler_label('A', (self.plot.col, self.plot.row), False, True)
        self.assertFalse(self.plot.rulers[0].show_label)
        backend = self.widget._parser.get_rulers(self.impl_plot)[0]
        self.assertFalse(backend.name_label.get_visible())
        self.assertTrue(backend.v_line.get_visible())

    def test_ruler_shows_one_value_label_per_signal(self):
        self.widget._add_ruler_at(self.impl_plot, self.plot, 2.5, 0.5)
        backend = self.widget._parser.get_rulers(self.impl_plot)[0]
        self.assertEqual(len(backend.value_labels), 1)
        annotation = backend.value_labels[0]
        self.assertTrue(annotation.get_visible())
        x = np.linspace(0, 10, 50)
        nearest = int(np.argmin(np.abs(x - 2.5)))
        self.assertEqual(annotation.get_text(), self.impl_plot.format_ydata(np.sin(x)[nearest]))

    def test_toggle_val_label_hides_signal_value_labels(self):
        self.widget._add_ruler_at(self.impl_plot, self.plot, 2.5, 0.5)
        self.widget.toggle_ruler_label('A', (self.plot.col, self.plot.row), True, False)
        backend = self.widget._parser.get_rulers(self.impl_plot)[0]
        self.assertFalse(backend.value_labels[0].get_visible())
        self.assertTrue(backend.name_label.get_visible())

    def test_preview_ruler_shows_next_identity_without_touching_the_model(self):
        self.widget._show_preview_ruler(self.impl_plot, 2.0, 0.2)
        ghost = next(r for r in self.widget._parser.get_rulers(self.impl_plot)
                     if r.name == self.widget._PREVIEW_RULER_NAME)
        self.assertEqual(ghost.name_label.get_text(), 'A')
        self.assertEqual(self.plot.rulers, [])
        self.assertEqual(self.widget._ruler_window.table.rowCount(), 0)

    def test_add_ruler_clears_preview_and_takes_its_identity(self):
        self.widget._show_preview_ruler(self.impl_plot, 2.0, 0.2)
        self.widget._add_ruler_at(self.impl_plot, self.plot, 2.0, 0.2)
        names = [r.name for r in self.widget._parser.get_rulers(self.impl_plot)]
        self.assertEqual(names, ['A'])

    def test_preview_identity_reuses_freed_name(self):
        self.widget._add_ruler_at(self.impl_plot, self.plot, 1.0, 0.1)
        self.widget._add_ruler_at(self.impl_plot, self.plot, 3.0, 0.3)
        self.widget.delete_ruler('A', (self.plot.col, self.plot.row), True)
        self.widget._ruler_window.remove_row_by_name('A', (self.plot.col, self.plot.row))
        self.assertEqual(self.widget._preview_identity_for_next()['name'], 'A')

    def test_remove_from_menu_on_shared_x_echo_deletes_the_owner_ruler(self):
        """Deleting via the context menu of another shared-x plot hits the echo:
        the deletion must reach the owner plot's model and the window row, and
        the ruler must not come back on the next canvas reload."""
        c = Canvas(2, 1, title="shared_x_mpl", shared_x_axis=True)
        x = np.linspace(0, 10, 50)
        for _ in range(2):
            p = PlotXY()
            s = SignalXY(label="s")
            s.set_data([x, np.sin(x)])
            p.add_signal(s)
            c.add_plot(p, 0)
        widget = QtMatplotlibCanvas(canvas=c)
        try:
            plot_one, plot_two = c.plots[0]
            impl_one = widget._get_impl_plot_for_plot(plot_one)
            impl_two = widget._get_impl_plot_for_plot(plot_two)
            widget._add_ruler_at(impl_one, plot_one, 5.0, 0.0)
            self.assertTrue(any(r.is_echo for r in widget._parser.get_rulers(impl_two)))

            widget._remove_ruler_from_menu('A', (2, 1))

            self.assertEqual(plot_one.rulers, [])
            self.assertEqual(widget._parser.get_rulers(), [])
            self.assertEqual(widget._ruler_window.table.rowCount(), 0)

            widget.set_canvas(c)
            self.assertEqual(widget._parser.get_rulers(), [])
            self.assertEqual(widget._ruler_window.table.rowCount(), 0)
        finally:
            widget._ruler_window.close()
            widget.deleteLater()

    def test_repaint_applies_font_color_and_label_state(self):
        c2 = _build_canvas()
        plot2 = c2.plots[0][0]
        plot2.add_ruler(Ruler(name='X', xy=(2.0, 0.2), color='#00FF00',
                              font_color='#000000', show_label=False, show_val_label=False))
        self.widget.set_canvas(c2)
        impl_plot = self.widget._get_impl_plot_for_plot(plot2)
        backend = self.widget._parser.get_rulers(impl_plot)[0]
        self.assertEqual(backend.font_color, '#000000')
        self.assertFalse(backend.show_label)
        self.assertFalse(backend.name_label.get_visible())
        self.assertFalse(backend.show_val_label)
        self.assertFalse(backend.value_labels[0].get_visible())

    def test_ruler_on_second_plot_uses_correct_plot_id(self):
        """Stacked plots must get distinct plot_ids so delete/visibility/color
        operations route to the correct plot."""
        c = Canvas(2, 1, title="multi_plot_mpl")
        x = np.linspace(0, 10, 50)
        for _ in range(2):
            p = PlotXY()
            s = SignalXY(label="s")
            s.set_data([x, np.sin(x)])
            p.add_signal(s)
            c.add_plot(p, 0)
        widget = QtMatplotlibCanvas(canvas=c)
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

    def test_repaint_after_setting_canvas_with_rulers(self):
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
        backend_y = next(r for r in self.widget._parser.get_rulers(impl_plot) if r.name == 'Y')
        self.assertFalse(backend_y.v_line.get_visible())


class RulerMatplotlibRegressionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = ensure_qapp()

    def test_crosshair_still_activates(self):
        widget = QtMatplotlibCanvas(canvas=_build_canvas())
        try:
            widget.set_mouse_mode(Canvas.MOUSE_MODE_CROSSHAIR)
            self.assertTrue(len(widget._parser._cursors) >= 1)
        finally:
            widget.deleteLater()

    def test_marker_and_ruler_windows_are_independent(self):
        widget = QtMatplotlibCanvas(canvas=_build_canvas())
        try:
            self.assertIsNot(widget._marker_window, widget._ruler_window)
        finally:
            widget.deleteLater()

    def test_zoom_with_legend_and_ruler_keeps_axis_callback_alive(self):
        """Ruler '_RulerLine' helpers must not be counted as signal lines: if they
        are, zooming a legend plot raises inside the axis-update callback and
        leaves the ``_update`` guard stuck True, freezing later zoom/pan/undo."""
        import copy
        from iplotlib.core.commands.axes_range import IplotAxesRangeCmd

        canvas = Canvas(2, 1, title="legend_ruler", shared_x_axis=True)
        x = np.linspace(0, 10, 400)
        for _ in range(2):
            p = PlotXY(legend=True)
            s = SignalXY(label="s")
            s.set_data([x, np.sin(x)])
            p.add_signal(s)
            canvas.add_plot(p, 0)
        widget = QtMatplotlibCanvas(canvas=canvas)
        try:
            plot0 = canvas.plots[0][0]
            ip0 = widget._get_impl_plot_for_plot(plot0)
            widget._add_ruler_at(ip0, plot0, 5.0, 0.0)

            parser = widget._parser
            current = parser.get_all_plot_limits()
            narrowed = copy.deepcopy(current)
            for src, dst in zip(current, narrowed):
                dst.plot_ref = src.plot_ref
                for a, b in zip(src.signals_ranges, dst.signals_ranges):
                    b.signal_ref = a.signal_ref
            span = current[0].axes_ranges[0].end - current[0].axes_ranges[0].begin
            narrowed[0].axes_ranges[0].set_limits(
                current[0].axes_ranges[0].begin + span * 0.25,
                current[0].axes_ranges[0].end - span * 0.25)
            cmd = IplotAxesRangeCmd('Zoom', old_limits=current,
                                    new_limits=narrowed, parser=parser)
            parser._hm.done(cmd)
            cmd()
            parser._hm.undo()

            self.assertFalse(parser._update,
                             "axis-update guard left stuck True after zoom+undo")
        finally:
            widget._ruler_window.close()
            widget.deleteLater()


if __name__ == '__main__':
    unittest.main()
