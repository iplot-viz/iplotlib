"""Unit tests for the Marker dataclass.

Marker is a plain dataclass used to annotate points on a SignalXY and to
anchor the distance/ruler tool's persistent marks. Trivial surface, but
the defaults and ``_type`` fingerprint are relied on by workspace
persistence (import/export dict). Pin them so they cannot drift silently.
"""

import unittest

from iplotlib.core.marker import Marker


class MarkerTest(unittest.TestCase):
    def test_defaults(self):
        m = Marker()
        self.assertIsNone(m.name)
        self.assertIsNone(m.xy)
        self.assertEqual(m.color, '#FFFFFF')
        self.assertFalse(m.visible)

    def test_attributes_store_values(self):
        m = Marker(name='peak', xy=(1.5, 3.2), color='#ff0000', visible=True)
        self.assertEqual(m.name, 'peak')
        self.assertEqual(m.xy, (1.5, 3.2))
        self.assertEqual(m.color, '#ff0000')
        self.assertTrue(m.visible)

    def test_type_fingerprint_is_set_after_init(self):
        """_type is populated in __post_init__ and must match the class FQN."""
        m = Marker(name='p')
        self.assertIsNotNone(m._type)
        self.assertIn('Marker', m._type)
        self.assertIn('iplotlib.core.marker', m._type)

    def test_two_markers_share_the_same_type_fingerprint(self):
        self.assertEqual(Marker(name='a')._type, Marker(name='b')._type)


if __name__ == '__main__':
    unittest.main()
