# iplotlib/impl/tests/test_tp_tt_004_row_col_span.py

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
    TP-TT-004: Verify row-span and col-span functionality.
    """

    canvas_class = QtMatplotlibCanvas

    def setUp(self):
        super().setUp()
        # 4 rows × 2 columns core canvas
        self.core_canvas = Canvas(4, 2, title=os.path.basename(__file__))
        ts = np.linspace(0.0, 1.0, 50)

        entries = [
            ("CWS-SCSU-HR00:MFT0005-FT-XI", 2, 1),
            ("CWS-SCSU-HR00:MFT0009-FT-XI", 1, 1),
            ("CWS-SCSU-HR00:ML0103-LT-XI",  1, 1),
            ("CWS-SCSU-HR00:ML0204-LT-XI",  1, 1),
            ("CWS-SCSU-HR00:MP0003-PT-XI",  1, 1),
            ("CWS-SCSU-HR00:MP0006-PT-XI",  2, 1),
            ("CWS-SCSU-HR00:MTE0101-TT-XI", 1, 1),
            ("CWS-SCSU-HR00:MTE0102-TT-XI", 1, 1),
        ]
        for idx, (label, rspan, cspan) in enumerate(entries):
            sig = SignalXY(label=label)
            sig.set_data([ts, ts * (idx + 1)])
            plot = PlotXY(row_span=rspan, col_span=cspan)
            plot.add_signal(sig)
            col = idx % self.core_canvas.cols
            self.core_canvas.add_plot(plot, col)

    def tearDown(self):
        super().tearDown()

    def test_tp_tt_004_row_col_span_refresh(self):
        """
        After set_canvas, verify that the layout grid is 2 columns × 4 rows.
        """
        self.canvas.set_canvas(self.core_canvas)
        layout = self.canvas._parser._layout
        self.assertEqual(layout.ncols, 2)
        self.assertEqual(layout.nrows, 4)

    def test_tp_tt_004_row_col_span_visuals(self):
        """
        Perform visual regression for row/col span. Create baseline if needed.
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
                "Visual regression failed for row/col span (TP-TT-004)."
            )


if __name__ == "__main__":
    unittest.main()