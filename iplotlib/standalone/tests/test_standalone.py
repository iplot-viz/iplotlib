"""
End-to-end test that verifies iplotlib can be used as a standalone visualisation
library, independent of MINT. Renders a simple canvas via the Qt factory for both
matplotlib and pyqtgraph backends and checks the output is produced.
"""

import os
import sys
import unittest

from iplotlib.qt.gui.iplotQtCanvasFactory import IplotQtCanvasFactory
from iplotlib.qt.testing import compare_pixmap_to_baseline, ensure_qapp
from iplotlib.standalone.examples import customData

ROOT = os.path.dirname(__file__)
BASELINE_DIR = os.path.join(ROOT, 'baseline')
PYQT_CANONICAL_PLATFORM = 'linux'
BASELINE_TOLERANCE = 5.0
PYQT_BASELINE_TOLERANCE = 20.0


class StandaloneRenderTest(unittest.TestCase):
    """Verifies that the standalone Qt canvas renders a canvas for each backend."""

    def setUp(self) -> None:
        super().setUp()
        self.app = ensure_qapp()

    def _render_and_save(self, backend: str) -> bytes:
        canvas = customData.get_canvas()
        qt_canvas = IplotQtCanvasFactory.new(backend, canvas=canvas)
        qt_canvas.set_canvas(canvas)
        qt_canvas.resize(800, 600)
        self.app.processEvents()

        pixmap = qt_canvas.grab()
        self.assertFalse(pixmap.isNull(),
                         f"{backend} produced a null pixmap")
        self.assertGreater(pixmap.width(), 0)
        self.assertGreater(pixmap.height(), 0)

        baseline = os.path.join(BASELINE_DIR, f"customData_{backend}.png")
        tol = PYQT_BASELINE_TOLERANCE if backend == 'pyqt' else BASELINE_TOLERANCE
        compare_pixmap_to_baseline(pixmap, baseline, tol=tol)
        return baseline

    def test_matplotlib_renders_customData(self):
        self._render_and_save('matplotlib')

    @unittest.skipIf(not sys.platform.startswith(PYQT_CANONICAL_PLATFORM),
                     "pyqt visual baselines are canonical on Linux only")
    def test_pyqtgraph_renders_customData(self):
        self._render_and_save('pyqt')


if __name__ == '__main__':
    unittest.main()
