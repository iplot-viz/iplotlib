# iplotlib/impl/tests/test_tp_tt_001_time_based_plots.py

import os
import numpy as np
import unittest

from iplotlib.core.canvas import Canvas
from iplotlib.core.plot import PlotXY
from iplotlib.core.signal import SignalXY

from iplotlib.impl.tests.tools.utils import regression_test
from iplotlib.impl.tests.base_canvas_test import BaseCanvasTest
from iplotlib.impl.matplotlib.qt.qtMatplotlibCanvas import QtMatplotlibCanvas


class CanvasTesting(BaseCanvasTest, unittest.TestCase):
    """
    TP-TT-001: Basic time-range plots in a 2×2 grid.
    """

    canvas_class = QtMatplotlibCanvas

    def setUp(self):
        super().setUp()
        # 2 rows × 2 columns core canvas
        self.core_canvas = Canvas(2, 2, title=os.path.basename(__file__))
        ts = np.linspace(0.0, 1.0, 50)

        for idx, label in enumerate(["Signal1.1", "Signal1.2", "Signal2.1", "Signal2.2"]):
            sig = SignalXY(label=label)
            sig.set_data([ts, ts * (idx + 1)])
            plot = PlotXY()
            plot.add_signal(sig)
            # ensure column index wraps within [0, cols)
            col = idx % self.core_canvas.cols
            self.core_canvas.add_plot(plot, col)

    def tearDown(self):
        super().tearDown()

    def test_tp_tt_001_time_based_plots_refresh(self):
        """
        After setting the core canvas, verify that the layout grid is
        exactly 2 columns × 2 rows.
        """
        self.canvas.set_canvas(self.core_canvas)
        # MatplotlibParser exposes its layout in _layout
        layout = self.canvas._parser._layout
        self.assertEqual(layout.ncols, 2)
        self.assertEqual(layout.nrows, 2)

    def test_tp_tt_001_time_based_plots_visuals(self):
        """
        Perform visual regression. If the baseline doesn't exist, create it
        and pass; otherwise compare and fail on mismatch.
        """
        self.canvas.set_canvas(self.core_canvas)
        figure = self.canvas._parser.figure

        valid_name = (
            os.path.basename(__file__)
            .replace("test", "valid")
            .replace(".py", ".png")
        )
        valid_path = os.path.join(
            os.path.dirname(__file__),
            "baseline",
            valid_name
        )

        # Record whether baseline existed prior to this run
        baseline_existed = os.path.exists(valid_path)
        passed = regression_test(valid_path, figure)
        if baseline_existed:
            # only assert once we have a reference to compare against
            self.assertTrue(
                passed,
                "Visual regression failed for time-based plots (TP-TT-001)."
            )
        # on first run (no baseline) we created it and do not fail


if __name__ == "__main__":
    unittest.main()