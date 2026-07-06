"""Unit tests for the Ruler dataclass and its integration with Plot.

Rulers are placed by the user on a plot to read X/Y values and compute deltas
between pairs. The data model is a plain dataclass — but it is serialized to
the workspace JSON, so defaults, the ``_type`` fingerprint and the Plot-level
add/remove/get helpers must stay stable across versions.
"""

import unittest

from iplotlib.core.canvas import Canvas
from iplotlib.core.plot import PlotXY
from iplotlib.core.ruler import Ruler


class RulerDefaultsTest(unittest.TestCase):
    def test_defaults(self):
        r = Ruler()
        self.assertIsNone(r.name)
        self.assertIsNone(r.xy)
        self.assertEqual(r.color, '#FFFFFF')
        self.assertEqual(r.font_color, '#FFFFFF')
        self.assertTrue(r.visible)
        self.assertTrue(r.show_label)

    def test_attributes_store_values(self):
        r = Ruler(name='A', xy=(1.5, 3.2), color='#ff0000', visible=False)
        self.assertEqual(r.name, 'A')
        self.assertEqual(r.xy, (1.5, 3.2))
        self.assertEqual(r.color, '#ff0000')
        self.assertFalse(r.visible)

    def test_type_fingerprint_is_set_after_init(self):
        r = Ruler(name='A')
        self.assertIsNotNone(r._type)
        self.assertIn('Ruler', r._type)
        self.assertIn('iplotlib.core.ruler', r._type)

    def test_two_rulers_share_the_same_type_fingerprint(self):
        self.assertEqual(Ruler(name='a')._type, Ruler(name='b')._type)


class PlotRulersTest(unittest.TestCase):
    def test_plot_initializes_rulers_to_empty_list(self):
        p = PlotXY()
        self.assertEqual(p.rulers, [])

    def test_add_ruler_appends_in_order(self):
        p = PlotXY()
        a = Ruler(name='A', xy=(1, 2))
        b = Ruler(name='B', xy=(3, 4))
        p.add_ruler(a)
        p.add_ruler(b)
        self.assertEqual(p.rulers, [a, b])

    def test_get_ruler_returns_match_by_name(self):
        p = PlotXY()
        a = Ruler(name='A', xy=(1, 2))
        p.add_ruler(a)
        self.assertIs(p.get_ruler('A'), a)

    def test_get_ruler_returns_none_when_missing(self):
        p = PlotXY()
        self.assertIsNone(p.get_ruler('Z'))

    def test_remove_ruler_removes_matching_name(self):
        p = PlotXY()
        a = Ruler(name='A', xy=(1, 2))
        b = Ruler(name='B', xy=(3, 4))
        p.add_ruler(a)
        p.add_ruler(b)
        p.remove_ruler('A')
        self.assertEqual([r.name for r in p.rulers], ['B'])

    def test_remove_ruler_is_noop_when_name_missing(self):
        p = PlotXY()
        a = Ruler(name='A', xy=(1, 2))
        p.add_ruler(a)
        p.remove_ruler('Z')
        self.assertEqual(p.rulers, [a])


class RulerWorkspaceRoundtripTest(unittest.TestCase):
    """Rulers ride along Plot serialization. Lock the round-trip in place."""

    def _build_canvas_with_rulers(self) -> Canvas:
        c = Canvas(rows=1, cols=1)
        p = PlotXY(plot_title="p0")
        p.add_ruler(Ruler(name='A', xy=(1.0, 2.0), color='#FF0000', visible=True))
        p.add_ruler(Ruler(name='B', xy=(3.0, 4.0), color='#00FF00', visible=False))
        c.add_plot(p, 0)
        return c

    def test_rulers_serialize_into_plot_dict(self):
        c = self._build_canvas_with_rulers()
        d = c.to_dict()
        self.assertIn('rulers', d['plots'][0][0])
        self.assertEqual(len(d['plots'][0][0]['rulers']), 2)

    def test_rulers_survive_dict_roundtrip(self):
        c = self._build_canvas_with_rulers()
        c2 = Canvas.from_dict(c.to_dict())
        rulers = c2.plots[0][0].rulers
        self.assertEqual(len(rulers), 2)
        self.assertEqual([r.name for r in rulers], ['A', 'B'])
        self.assertEqual(rulers[0].color, '#FF0000')
        self.assertFalse(rulers[1].visible)

    def test_canvas_without_rulers_still_roundtrips(self):
        c = Canvas(rows=1, cols=1)
        p = PlotXY()
        c.add_plot(p, 0)
        c2 = Canvas.from_dict(c.to_dict())
        self.assertEqual(c2.plots[0][0].rulers, [])

    def test_legacy_workspace_without_rulers_key_is_loadable(self):
        """Workspaces serialized before #99 lack the 'rulers' key on Plot dicts.
        Loading one must default to an empty rulers list and not raise."""
        c = Canvas(rows=1, cols=1)
        p = PlotXY()
        c.add_plot(p, 0)
        d = c.to_dict()
        # Simulate a pre-rulers workspace by stripping the key.
        for col in d['plots']:
            for plot_dict in col:
                if isinstance(plot_dict, dict):
                    plot_dict.pop('rulers', None)
        c2 = Canvas.from_dict(d)
        self.assertEqual(c2.plots[0][0].rulers, [])

    def test_plot_merge_restores_rulers_from_dict(self):
        """Plot.merge() must restore rulers from the old_plot dict so that
        rebuilding the canvas on Draw does not drop user-placed rulers."""
        old = self._build_canvas_with_rulers().to_dict()['plots'][0][0]
        fresh = PlotXY()
        fresh.merge(old)
        self.assertEqual([r.name for r in fresh.rulers], ['A', 'B'])
        self.assertEqual(fresh.rulers[0].xy, (1.0, 2.0))
        self.assertEqual(fresh.rulers[0].color, '#FF0000')
        self.assertFalse(fresh.rulers[1].visible)

    def test_plot_merge_with_no_rulers_in_dict_yields_empty_list(self):
        """Merging a dict that lacks the 'rulers' key must leave rulers as []."""
        c = Canvas(rows=1, cols=1)
        c.add_plot(PlotXY(), 0)
        old = c.to_dict()['plots'][0][0]
        old.pop('rulers', None)
        fresh = PlotXY()
        fresh.merge(old)
        self.assertEqual(fresh.rulers, [])

    def test_font_color_and_show_label_survive_dict_roundtrip(self):
        c = Canvas(rows=1, cols=1)
        p = PlotXY()
        p.add_ruler(Ruler(name='A', xy=(1.0, 2.0), color='#FF0000',
                          font_color='#000000', show_label=False))
        c.add_plot(p, 0)
        restored = Canvas.from_dict(c.to_dict()).plots[0][0].rulers[0]
        self.assertEqual(restored.font_color, '#000000')
        self.assertFalse(restored.show_label)

    def test_plot_merge_defaults_new_fields_for_pre_existing_workspaces(self):
        """Ruler dicts serialized before font_color / show_label existed must
        load with the dataclass defaults."""
        c = Canvas(rows=1, cols=1)
        p = PlotXY()
        p.add_ruler(Ruler(name='A', xy=(1.0, 2.0), color='#FF0000'))
        c.add_plot(p, 0)
        old = c.to_dict()['plots'][0][0]
        for ruler_dict in old['rulers']:
            ruler_dict.pop('font_color', None)
            ruler_dict.pop('show_label', None)
        fresh = PlotXY()
        fresh.merge(old)
        self.assertEqual(fresh.rulers[0].font_color, Ruler.font_color)
        self.assertTrue(fresh.rulers[0].show_label)


class CanvasMouseModeRulerTest(unittest.TestCase):
    def test_mouse_mode_ruler_constant_exists(self):
        self.assertEqual(Canvas.MOUSE_MODE_RULER, 'MM_RULER')

    def test_mouse_mode_ruler_is_distinct(self):
        modes = {Canvas.MOUSE_MODE_SELECT, Canvas.MOUSE_MODE_CROSSHAIR,
                 Canvas.MOUSE_MODE_PAN, Canvas.MOUSE_MODE_ZOOM,
                 Canvas.MOUSE_MODE_DIST, Canvas.MOUSE_MODE_MARKER,
                 Canvas.MOUSE_MODE_RULER}
        self.assertEqual(len(modes), 7)


class PlotItemRulerTreeTest(unittest.TestCase):
    """The PlotItem in the preferences tree must list each ruler as a child
    next to the signals, so the user can pick a ruler from the tree and edit
    its preferences. Live tests for the QStandardItem so the wiring cannot
    drift silently."""

    @classmethod
    def setUpClass(cls) -> None:
        from iplotlib.qt.testing import ensure_qapp
        cls.app = ensure_qapp()

    def test_plotitem_appends_one_child_per_ruler(self):
        from PySide6.QtCore import Qt
        from iplotlib.qt.models.plotting.plotItem import PlotItem
        from iplotlib.qt.models.plotting.rulerItem import RulerItem
        from iplotlib.core.signal import SignalXY

        p = PlotXY()
        p.add_signal(SignalXY(label='s1'))
        p.add_ruler(Ruler(name='A', xy=(1, 2), color='#FF0000'))
        p.add_ruler(Ruler(name='B', xy=(3, 4), color='#00FF00'))

        item = PlotItem('Plot 1')
        item.setData(p, Qt.ItemDataRole.UserRole)

        ruler_children = [item.child(i) for i in range(item.rowCount())
                          if isinstance(item.child(i), RulerItem)]
        self.assertEqual(len(ruler_children), 2)
        self.assertEqual({c.text() for c in ruler_children}, {'Ruler A', 'Ruler B'})

    def test_plotitem_without_rulers_has_no_ruler_children(self):
        from PySide6.QtCore import Qt
        from iplotlib.qt.models.plotting.plotItem import PlotItem
        from iplotlib.qt.models.plotting.rulerItem import RulerItem

        p = PlotXY()
        item = PlotItem('Plot 1')
        item.setData(p, Qt.ItemDataRole.UserRole)

        rulers = [item.child(i) for i in range(item.rowCount())
                  if isinstance(item.child(i), RulerItem)]
        self.assertEqual(rulers, [])


if __name__ == '__main__':
    unittest.main()
