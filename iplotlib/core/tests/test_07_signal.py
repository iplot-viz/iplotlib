"""Unit tests for SignalXY and SignalContour."""

import unittest

import numpy as np
from iplotlib.core.signal import SignalXY, SignalContour


class TestSignalXY(unittest.TestCase):
    def test_set_data_populates_buffers(self):
        s = SignalXY(label="s")
        s.set_data([np.array([0.0, 1.0, 2.0]),
                    np.array([10.0, 11.0, 12.0])])
        self.assertEqual(len(s.data_store[0]), 3)
        self.assertEqual(len(s.data_store[1]), 3)

    def test_label_is_stored(self):
        s = SignalXY(label="my_label")
        self.assertEqual(s.label, "my_label")

    def test_color_is_stored(self):
        s = SignalXY(label="s", color="#ff0000")
        self.assertEqual(s.color, "#ff0000")


class TestSignalContour(unittest.TestCase):
    def test_set_data_populates_buffers(self):
        x = np.array([0.0, 1.0, 2.0])
        y = np.array([0.0, 1.0])
        z = np.outer(y, x)
        s = SignalContour(label="contour")
        s.set_data([x, y, z])
        self.assertEqual(len(s.data_store[0]), 3)
        self.assertEqual(len(s.data_store[1]), 2)


if __name__ == '__main__':
    unittest.main()
