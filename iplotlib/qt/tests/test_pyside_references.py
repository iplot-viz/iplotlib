"""Qt calls that return nothing must not free None."""

import sys
import unittest

from PySide6.QtCore import QPointF


class PySideReferencesTest(unittest.TestCase):

    def test_qt_calls_that_return_nothing_keep_none_alive(self):
        # PySide6 6.12.0 on Linux drops a reference to None on each call, and Python older than 3.12 then aborts
        point = QPointF()
        before = sys.getrefcount(None)
        for _ in range(1000):
            point.setX(1.0)
        self.assertGreater(sys.getrefcount(None), before - 500)


if __name__ == '__main__':
    unittest.main()
