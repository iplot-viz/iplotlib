"""Unit tests for Axis, RangeAxis and LinearAxis."""

import unittest

from iplotlib.core.axis import Axis, RangeAxis, LinearAxis


class TestAxis(unittest.TestCase):
    def test_axis_defaults(self):
        a = Axis()
        self.assertIsNone(a.label)
        self.assertIsNone(a.font_size)
        self.assertIsNone(a.font_color)

    def test_axis_accepts_label(self):
        a = Axis(label="Time")
        self.assertEqual(a.label, "Time")


class TestRangeAxis(unittest.TestCase):
    def test_defaults(self):
        a = RangeAxis()
        self.assertIsNone(a.begin)
        self.assertIsNone(a.end)
        self.assertIsNone(a.original_begin)
        self.assertIsNone(a.original_end)
        self.assertFalse(a.limits_changed)

    def test_set_and_get_current_limits(self):
        a = RangeAxis()
        a.set_limits(0, 10, 'current')
        self.assertEqual(a.get_limits('current'), (0, 10))

    def test_set_and_get_original_limits(self):
        a = RangeAxis()
        a.set_limits(-5, 5, 'original')
        self.assertEqual(a.get_limits('original'), (-5, 5))
        # 'current' should remain unset.
        self.assertEqual(a.get_limits('current'), (None, None))

    def test_get_limits_unknown_kind(self):
        a = RangeAxis()
        self.assertEqual(a.get_limits('nonsense'), (None, None))


class TestLinearAxis(unittest.TestCase):
    def test_inherits_range_axis(self):
        a = LinearAxis()
        self.assertIsInstance(a, RangeAxis)

    def test_is_date_default_false(self):
        a = LinearAxis()
        self.assertFalse(a.is_date)

    def test_is_date_flag(self):
        a = LinearAxis(is_date=True)
        self.assertTrue(a.is_date)


if __name__ == '__main__':
    unittest.main()
