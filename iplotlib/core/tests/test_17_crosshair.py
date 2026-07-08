"""Unit tests for the frozen-Crosshair dataclass and its integration with Plot.

A frozen crosshair shares the data model with :class:`Ruler` but is a distinct,
separately-persisted feature (its own ``_type`` fingerprint and its own
``Plot.crosshairs`` collection). These tests pin the model, the Plot-level
add/remove/get helpers and the workspace round-trip so the crosshair extension
cannot silently drift — and, crucially, so it never disturbs the ruler side.
"""

import unittest

from iplotlib.core.canvas import Canvas
from iplotlib.core.crosshair import Crosshair
from iplotlib.core.plot import PlotXY
from iplotlib.core.ruler import Ruler


class CrosshairDefaultsTest(unittest.TestCase):
    def test_defaults_match_ruler(self):
        c = Crosshair()
        self.assertIsNone(c.name)
        self.assertIsNone(c.xy)
        self.assertEqual(c.color, '#FFFFFF')
        self.assertEqual(c.font_color, '#FFFFFF')
        self.assertTrue(c.visible)
        self.assertTrue(c.show_label)
        self.assertTrue(c.show_val_label)

    def test_type_fingerprint_is_crosshair_not_ruler(self):
        c = Crosshair(name='A')
        self.assertIsNotNone(c._type)
        self.assertIn('Crosshair', c._type)
        self.assertIn('iplotlib.core.crosshair', c._type)
        self.assertNotEqual(c._type, Ruler(name='A')._type)

    def test_is_a_ruler_subclass(self):
        self.assertIsInstance(Crosshair(), Ruler)


class PlotCrosshairsTest(unittest.TestCase):
    def test_plot_initializes_crosshairs_to_empty_list(self):
        self.assertEqual(PlotXY().crosshairs, [])

    def test_add_crosshair_appends_in_order(self):
        p = PlotXY()
        a = Crosshair(name='A', xy=(1, 2))
        b = Crosshair(name='B', xy=(3, 4))
        p.add_crosshair(a)
        p.add_crosshair(b)
        self.assertEqual(p.crosshairs, [a, b])

    def test_get_crosshair_returns_match_by_name(self):
        p = PlotXY()
        a = Crosshair(name='A', xy=(1, 2))
        p.add_crosshair(a)
        self.assertIs(p.get_crosshair('A'), a)

    def test_get_crosshair_returns_none_when_missing(self):
        self.assertIsNone(PlotXY().get_crosshair('Z'))

    def test_remove_crosshair_removes_matching_name(self):
        p = PlotXY()
        p.add_crosshair(Crosshair(name='A', xy=(1, 2)))
        p.add_crosshair(Crosshair(name='B', xy=(3, 4)))
        p.remove_crosshair('A')
        self.assertEqual([c.name for c in p.crosshairs], ['B'])

    def test_crosshairs_and_rulers_are_independent_collections(self):
        """Adding a crosshair must not touch rulers and vice-versa."""
        p = PlotXY()
        p.add_ruler(Ruler(name='R', xy=(1, 2)))
        p.add_crosshair(Crosshair(name='C', xy=(3, 4)))
        self.assertEqual([r.name for r in p.rulers], ['R'])
        self.assertEqual([c.name for c in p.crosshairs], ['C'])
        p.remove_crosshair('C')
        self.assertEqual([r.name for r in p.rulers], ['R'])
        self.assertEqual(p.crosshairs, [])


class CrosshairWorkspaceRoundtripTest(unittest.TestCase):
    def _build_canvas(self) -> Canvas:
        c = Canvas(rows=1, cols=1)
        p = PlotXY(plot_title="p0")
        p.add_ruler(Ruler(name='R', xy=(9.0, 9.0), color='#123456'))
        p.add_crosshair(Crosshair(name='A', xy=(1.0, 2.0), color='#FF0000', visible=True))
        p.add_crosshair(Crosshair(name='B', xy=(3.0, 4.0), color='#00FF00', visible=False))
        c.add_plot(p, 0)
        return c

    def test_crosshairs_serialize_into_plot_dict(self):
        d = self._build_canvas().to_dict()
        self.assertIn('crosshairs', d['plots'][0][0])
        self.assertEqual(len(d['plots'][0][0]['crosshairs']), 2)

    def test_crosshairs_survive_dict_roundtrip_alongside_rulers(self):
        c2 = Canvas.from_dict(self._build_canvas().to_dict())
        plot = c2.plots[0][0]
        self.assertEqual([r.name for r in plot.rulers], ['R'])
        crosshairs = plot.crosshairs
        self.assertEqual([c.name for c in crosshairs], ['A', 'B'])
        self.assertIsInstance(crosshairs[0], Crosshair)
        self.assertEqual(crosshairs[0].color, '#FF0000')
        self.assertFalse(crosshairs[1].visible)

    def test_canvas_without_crosshairs_still_roundtrips(self):
        c = Canvas(rows=1, cols=1)
        c.add_plot(PlotXY(), 0)
        c2 = Canvas.from_dict(c.to_dict())
        self.assertEqual(c2.plots[0][0].crosshairs, [])

    def test_legacy_workspace_without_crosshairs_key_is_loadable(self):
        """Workspaces serialized before #130 lack the 'crosshairs' key; loading
        one must default to an empty list and not raise, and must not affect
        rulers on the same plot."""
        c = Canvas(rows=1, cols=1)
        p = PlotXY()
        p.add_ruler(Ruler(name='R', xy=(1.0, 2.0)))
        c.add_plot(p, 0)
        d = c.to_dict()
        for col in d['plots']:
            for plot_dict in col:
                if isinstance(plot_dict, dict):
                    plot_dict.pop('crosshairs', None)
        c2 = Canvas.from_dict(d)
        self.assertEqual(c2.plots[0][0].crosshairs, [])
        self.assertEqual([r.name for r in c2.plots[0][0].rulers], ['R'])

    def test_plot_merge_restores_crosshairs_from_dict(self):
        old = self._build_canvas().to_dict()['plots'][0][0]
        fresh = PlotXY()
        fresh.merge(old)
        self.assertEqual([c.name for c in fresh.crosshairs], ['A', 'B'])
        self.assertEqual(fresh.crosshairs[0].xy, (1.0, 2.0))
        self.assertFalse(fresh.crosshairs[1].visible)
        # rulers on the same dict must still round-trip untouched
        self.assertEqual([r.name for r in fresh.rulers], ['R'])

    def test_plot_merge_with_no_crosshairs_in_dict_yields_empty_list(self):
        c = Canvas(rows=1, cols=1)
        c.add_plot(PlotXY(), 0)
        old = c.to_dict()['plots'][0][0]
        old.pop('crosshairs', None)
        fresh = PlotXY()
        fresh.merge(old)
        self.assertEqual(fresh.crosshairs, [])


if __name__ == '__main__':
    unittest.main()
