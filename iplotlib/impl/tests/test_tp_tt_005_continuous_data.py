# iplotlib/impl/tests/test_tp_tt_005_continuous_data.py

import os
import numpy as np
import unittest
from datetime import datetime

from iplotlib.core.canvas import Canvas
from iplotlib.core.plot import PlotXY
from iplotlib.core.signal import SignalXY

from iplotlib.impl.tests.tools.utils import regression_test
from iplotlib.impl.tests.base_canvas_test import BaseCanvasTest
from iplotlib.impl.matplotlib.qt.qtMatplotlibCanvas import QtMatplotlibCanvas


class CanvasTesting(BaseCanvasTest, unittest.TestCase):
    """
    TP-TT-005: Verify coexisting absolute time ranges in a 2×1 canvas.
    """

    canvas_class = QtMatplotlibCanvas

    def setUp(self):
        super().setUp()
        # 2 rows × 1 column core canvas
        self.core_canvas = Canvas(2, 1, title=os.path.basename(__file__))
        ts = np.linspace(0.0, 1.0, 100)

        # full-range signal
        sig1 = SignalXY(label="CWS-SCSU-HR00:MTE0097-TT-XI")
        sig1.set_data([ts, ts * 1])
        plot1 = PlotXY()
        plot1.add_signal(sig1)
        self.core_canvas.add_plot(plot1, 0)

        # restricted-range signal
        sig2 = SignalXY(label="CWS-SCSU-HR00:MTE0097-TT-XI")
        sig2.set_data([ts, ts * 2])
        sig2.start_time = datetime.fromisoformat("2021-11-19T11:01:49")
        sig2.end_time   = datetime.fromisoformat("2021-11-26T11:01:49")
        plot2 = PlotXY()
        plot2.add_signal(sig2)
        self.core_canvas.add_plot(plot2, 0)

    def tearDown(self):
        super().tearDown()

    def test_tp_tt_005_continuous_data_refresh(self):
        """
        After set_canvas, verify that the layout grid is 1 column × 2 rows.
        """
        self.canvas.set_canvas(self.core_canvas)
        layout = self.canvas._parser._layout
        self.assertEqual(layout.ncols, 1)
        self.assertEqual(layout.nrows, 2)

    def test_tp_tt_005_continuous_data_visuals(self):
        """
        Perform visual regression for continuous-data plots. Create baseline if missing.
        """
        self.canvas.set_canvas(self.core_canvas)
        fig = self.canvas._parser.figure

        valid_name = os.path.basename(__file__).replace("test", "valid").replace(".py", ".png")
        valid_path = os.path.join(os.path.dirname(__file__), "baseline", valid_name)

        baseline_existed = os.path.exists(valid_path)
        passed = regression_test(valid_path, fig)
        if baseline_existed:
            self.assertTrue(
                passed,
                "Visual regression failed for continuous-data plots (TP-TT-005)."
            )


if __name__ == "__main__":
    unittest.main()