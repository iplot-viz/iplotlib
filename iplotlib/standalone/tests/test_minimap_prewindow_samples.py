"""The minimap must survive samples that precede the draw window.

Decimated replies and the extremities option both hand the plot a sample
earlier than the requested window start. The minimap plots X relative to an
integer offset taken from the baseline start, so such a sample used to wrap
around in the unsigned nanosecond dtype and land at ~1.8e19, flooding the
ViewBox with numpy overflow warnings.
"""

import unittest
import warnings

import numpy as np

from iplotlib.core.canvas import Canvas
from iplotlib.core.plot import PlotXY
from iplotlib.core.signal import SignalXY
from iplotlib.qt.gui.iplotQtCanvasFactory import IplotQtCanvasFactory
from iplotlib.qt.testing import ensure_qapp

TS_START = 1_787_839_810_000_000_000
SPAN = 300_000_000_000  # 5 min in ns


class MinimapPreWindowSampleTest(unittest.TestCase):
    def setUp(self) -> None:
        super().setUp()
        self.app = ensure_qapp()

    def test_sample_before_baseline_keeps_minimap_coordinates_small(self):
        core = Canvas(1, 1, title="minimap")
        core.show_minimap = True
        plot = PlotXY()
        signal = SignalXY(label="s")
        signal.ts_start = TS_START
        signal.ts_end = TS_START + SPAN
        # First sample 5 s before the window start, as an extremity would be.
        x = np.linspace(TS_START - 5_000_000_000, TS_START + SPAN, 200).astype(np.uint64)
        signal.set_data([x, np.sin(np.linspace(0, 6, 200))])
        plot.add_signal(signal)
        plot.axes[0].is_date = True
        core.add_plot(plot, 0)

        qt_canvas = IplotQtCanvasFactory.new('pyqt', canvas=core)
        qt_canvas.set_canvas(core)
        qt_canvas.resize(800, 600)
        self.app.processEvents()

        # The baseline is the requested window, as MINT draws it; the early
        # sample then lies before the offset instead of defining it.
        core.snapshot_minimap_baseline(TS_START, TS_START + SPAN)

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            qt_canvas._update_minimap()
            self.app.processEvents()

        overflow = [w for w in caught if "overflow" in str(w.message)]
        self.assertEqual(overflow, [])

        self.assertIsNotNone(qt_canvas._minimap_plot)
        for item in qt_canvas._minimap_plot.listDataItems():
            x_item, _ = item.getData()
            if x_item is None or len(x_item) == 0:
                continue
            # Relative to the offset: a pre-window sample is slightly negative,
            # never a wrapped huge positive.
            self.assertLess(float(np.max(x_item)), 2 * SPAN)
            self.assertGreater(float(np.min(x_item)), -2 * SPAN)


if __name__ == "__main__":
    unittest.main()
