"""End-to-end tests for the frozen-Crosshair feature on the pyqtgraph backend.

Mirrors test_ruler_pyqtgraph.py but pins the crosshair-specific contract: a
frozen crosshair is a time cursor, so the window row carries per-signal values
as a dict (not a text blob), the artist draws solid lines (vs the ruler's
dashed), and freezing/deleting/repainting keeps Plot.crosshairs, the parser and
the crosshair window in sync -- all without disturbing rulers.
"""

import os
import unittest

import numpy as np

from iplotlib.core.canvas import Canvas
from iplotlib.core.plot import PlotXY
from iplotlib.core.signal import SignalXY
from iplotlib.impl.pyqtgraph.pyQtCrosshairFrozen import pyQtCrosshairFrozen
from iplotlib.impl.pyqtgraph.qt.qtPyQtGraphCanvas import QtPyQtGraphCanvas
from iplotlib.qt.testing import ensure_qapp

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')


def _build_canvas() -> Canvas:
    c = Canvas(1, 1, title="crosshair_test")
    x = np.linspace(0, 10, 50)
    plot = PlotXY()
    for label, fn in (("s1", np.sin), ("s2", np.cos)):
        sig = SignalXY(label=label)
        sig.set_data([x, fn(x)])
        plot.add_signal(sig)
    c.add_plot(plot, 0)
    return c


class CrosshairPyQtGraphEndToEndTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = ensure_qapp()

    def setUp(self):
        self.canvas = _build_canvas()
        self.widget = QtPyQtGraphCanvas(canvas=self.canvas)
        self.plot = self.canvas.plots[0][0]
        self.impl_plot = self.widget._get_impl_plot_for_plot(self.plot)
        self.assertIsNotNone(self.impl_plot)

    def tearDown(self):
        self.widget._crosshair_window.close()
        self.widget._ruler_window.close()
        self.widget.deleteLater()

    def _plot_id(self):
        return (self.plot.col, self.plot.row)

    def test_freeze_populates_model_parser_and_window(self):
        self.widget._add_crosshair_at(self.impl_plot, self.plot, 2.5, 0.5)
        self.assertEqual([c.name for c in self.plot.crosshairs], ['A'])
        parser_crosshairs = self.widget._parser.get_crosshairs(self.impl_plot)
        self.assertEqual(len(parser_crosshairs), 1)
        self.assertIsInstance(parser_crosshairs[0], pyQtCrosshairFrozen)
        self.assertEqual(self.widget._crosshair_window.table.rowCount(), 1)

    def test_freeze_does_not_create_a_ruler(self):
        self.widget._add_crosshair_at(self.impl_plot, self.plot, 2.5, 0.5)
        self.assertEqual(self.plot.rulers, [])
        self.assertEqual(self.widget._ruler_window.table.rowCount(), 0)

    def test_signal_values_is_a_per_signal_dict(self):
        self.widget._add_crosshair_at(self.impl_plot, self.plot, 2.5, 0.5)
        sv = self.widget._crosshair_window._rows[0]['signal_values']
        self.assertIsInstance(sv, dict)
        self.assertEqual(set(sv.keys()), {'s1', 's2'})
        self.assertAlmostEqual(float(sv['s1']['value']), np.sin(2.5), delta=0.2)
        self.assertAlmostEqual(float(sv['s2']['value']), np.cos(2.5), delta=0.2)

    def test_signal_values_carry_the_curve_color(self):
        self.widget._add_crosshair_at(self.impl_plot, self.plot, 2.5, 0.5)
        sv = self.widget._crosshair_window._rows[0]['signal_values']
        # Each signal entry exposes its plot colour so the column can be tinted.
        self.assertTrue(all(sv[label].get('color') for label in ('s1', 's2')), sv)

    def test_frozen_crosshair_uses_solid_lines(self):
        from PySide6.QtCore import Qt
        self.widget._add_crosshair_at(self.impl_plot, self.plot, 2.5, 0.5)
        artist = self.widget._parser.get_crosshairs(self.impl_plot)[0]
        self.assertEqual(artist.v_line.pen.style(), Qt.PenStyle.SolidLine)

    def test_two_crosshairs_get_distinct_names(self):
        self.widget._add_crosshair_at(self.impl_plot, self.plot, 1.0, 0.1)
        self.widget._add_crosshair_at(self.impl_plot, self.plot, 3.0, 0.3)
        self.assertEqual([c.name for c in self.plot.crosshairs], ['A', 'B'])

    def test_delete_crosshair_syncs_model_parser_and_window(self):
        self.widget._add_crosshair_at(self.impl_plot, self.plot, 1.0, 0.1)
        self.widget._add_crosshair_at(self.impl_plot, self.plot, 3.0, 0.3)
        self.widget.delete_crosshair('A', self._plot_id(), True)
        self.widget._crosshair_window.remove_row_by_name('A', self._plot_id())
        self.assertEqual([c.name for c in self.plot.crosshairs], ['B'])
        self.assertEqual([c.name for c in self.widget._parser.get_crosshairs(self.impl_plot)], ['B'])
        self.assertEqual(self.widget._crosshair_window.table.rowCount(), 1)

    def test_toggle_visibility_updates_model_and_backend(self):
        self.widget._add_crosshair_at(self.impl_plot, self.plot, 1.0, 0.1)
        self.widget.toggle_crosshair_visibility('A', self._plot_id(), False)
        self.assertFalse(self.plot.crosshairs[0].visible)
        self.assertFalse(self.widget._parser.get_crosshairs(self.impl_plot)[0].v_line.isVisible())

    def test_change_color_updates_model_and_backend(self):
        self.widget._add_crosshair_at(self.impl_plot, self.plot, 1.0, 0.1)
        self.widget.change_crosshair_color('A', self._plot_id(), '#FF0000')
        self.assertEqual(self.plot.crosshairs[0].color, '#FF0000')
        self.assertEqual(self.widget._parser.get_crosshairs(self.impl_plot)[0].color, '#FF0000')

    def test_repaint_after_setting_canvas_with_crosshairs(self):
        """A canvas loaded from a workspace already carries Plot.crosshairs;
        reopening it must recreate the on-screen crosshair items and repopulate
        the crosshair window."""
        from iplotlib.core.crosshair import Crosshair
        c2 = _build_canvas()
        plot2 = c2.plots[0][0]
        plot2.add_crosshair(Crosshair(name='X', xy=(2.0, 0.2), color='#00FF00', visible=True))
        plot2.add_crosshair(Crosshair(name='Y', xy=(5.0, -0.5), color='#0000FF', visible=False))

        self.widget.set_canvas(c2)

        impl_plot = self.widget._get_impl_plot_for_plot(plot2)
        self.assertIsNotNone(impl_plot)
        names = sorted(c.name for c in self.widget._parser.get_crosshairs(impl_plot))
        self.assertEqual(names, ['X', 'Y'])
        self.assertEqual(self.widget._crosshair_window.table.rowCount(), 2)


if __name__ == '__main__':
    unittest.main()
