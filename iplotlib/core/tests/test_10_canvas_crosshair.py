"""Tests for canvas crosshair and marker state (mouse mode and enable_crosshair)."""

import unittest

from iplotlib.core.canvas import Canvas


class TestCanvasCrosshair(unittest.TestCase):
    def test_defaults(self):
        c = Canvas()
        self.assertFalse(c.crosshair_enabled)
        self.assertTrue(c.crosshair_horizontal)  # default in Canvas dataclass
        self.assertTrue(c.crosshair_vertical)

    def test_enable_crosshair_sets_color_and_flags(self):
        c = Canvas()
        c.enable_crosshair(color="#00ff00", linewidth=3,
                           horizontal=True, vertical=False)
        self.assertTrue(c.crosshair_enabled)
        self.assertEqual(c.crosshair_color, "#00ff00")
        self.assertEqual(c.crosshair_line_width, 3)
        self.assertTrue(c.crosshair_horizontal)
        self.assertFalse(c.crosshair_vertical)

    def test_mouse_mode_crosshair(self):
        c = Canvas()
        c.set_mouse_mode(Canvas.MOUSE_MODE_CROSSHAIR)
        self.assertEqual(c.mouse_mode, Canvas.MOUSE_MODE_CROSSHAIR)

    def test_mouse_mode_marker(self):
        c = Canvas()
        c.set_mouse_mode(Canvas.MOUSE_MODE_MARKER)
        self.assertEqual(c.mouse_mode, Canvas.MOUSE_MODE_MARKER)

    def test_mouse_mode_constants_distinct(self):
        modes = {Canvas.MOUSE_MODE_SELECT, Canvas.MOUSE_MODE_CROSSHAIR,
                 Canvas.MOUSE_MODE_PAN, Canvas.MOUSE_MODE_ZOOM,
                 Canvas.MOUSE_MODE_DIST, Canvas.MOUSE_MODE_MARKER}
        # All six modes must be distinct string constants.
        self.assertEqual(len(modes), 6)


if __name__ == '__main__':
    unittest.main()
