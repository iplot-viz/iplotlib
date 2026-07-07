import os
import tempfile
import unittest

import numpy as np
from matplotlib.figure import Figure
from matplotlib.ticker import FuncFormatter, LogLocator, MaxNLocator, NullFormatter

from iplotDataAccess.dataAccess import DataAccess
from iplotlib.core import PlotXY
from iplotlib.core.axis import LinearAxis
from iplotlib.impl.matplotlib.dateFormatter import ExponentScalarFormatter
from iplotlib.impl.matplotlib.matplotlibCanvas import MatplotlibParser
from iplotlib.impl.matplotlib.tests.QAppOffscreenTestAdapter import QAppOffscreenTestAdapter
from iplotlib.interface import AccessHelper

ROOT = os.path.dirname(__file__)
data_dir = os.path.join(ROOT, 'csv', 'ITER')

dscfg_csv = """
{
    "csv": {
        "path": "%s",
        "type": "CSV"
    }
}
"""


class MatplotlibTesting(QAppOffscreenTestAdapter):
    def setUp(self) -> None:
        super().setUp()

        # Snapshot global state we are about to mutate, so tearDown can restore it.
        self._prev_sources_config = os.environ.get('IPLOT_SOURCES_CONFIG')
        self._prev_access_helper_da = AccessHelper.da

        self.da = DataAccess()
        self.ds = "csv"

        # Use forward slashes for JSON compatibility on all platforms
        data_dir_escaped = data_dir.replace('\\', '/')
        dscfg = dscfg_csv % data_dir_escaped

        fd, self.temp_config_path = tempfile.mkstemp(suffix='.cfg')
        with os.fdopen(fd, 'w') as f:
            f.write(dscfg)

        os.environ['IPLOT_SOURCES_CONFIG'] = os.path.abspath(self.temp_config_path)
        if self.da.load_config(self.temp_config_path):
            AccessHelper.da = self.da

    def tearDown(self) -> None:
        if hasattr(self, 'temp_config_path'):
            try:
                os.unlink(self.temp_config_path)
            except OSError:
                pass
        # Restore env var and AccessHelper to prevent leaking into other tests.
        if self._prev_sources_config is None:
            os.environ.pop('IPLOT_SOURCES_CONFIG', None)
        else:
            os.environ['IPLOT_SOURCES_CONFIG'] = self._prev_sources_config
        AccessHelper.da = self._prev_access_helper_da
        super().tearDown()

    # --------------------------
    #           TESTS
    # --------------------------

    def test_01_null_refresh(self):
        self.mpl_parser = MatplotlibParser()
        self.mpl_parser.process_ipl_canvas(None)

        self.assertIsNone(self.mpl_parser.canvas)

    def test_CSVAccessByPulse(self) -> None:
        test_cases = [
            {
                "varname": "MAG-MCTB-F1:VAR1",
                "pulse": "ITER:MCTB-TEST/111",
                "expected_x_shape": (11,),
                "expected_y_shape": (11,),
                "expected_x_values": [-5.0, -4.0, -3.0, 0.0, 1.0, 1.1, 1.5, 2.0, 2.5, 3.0, 3.5],
                "expected_y_values": [0, 1, 2, 10, 11, 12, 12, 12, 12, 14, 0]
            },
            {
                "varname": "MAG-MCTB-F1:VAR2",
                "pulse": "ITER:MCTB-TEST/111",
                "expected_x_shape": (11,),
                "expected_y_shape": (11,),
                "expected_x_values": [-5.0, -4.0, -3.0, 0.0, 1.0, 1.1, 1.5, 2.0, 2.5, 3.0, 3.5],
                "expected_y_values": [1, 2, 3, 11, 12, 13, 13, 13, 13, 15, 0],
            },
        ]

        for test_case in test_cases:
            varname = test_case["varname"]
            pulse = test_case["pulse"]
            expected_x_shape = test_case["expected_x_shape"]
            expected_y_shape = test_case["expected_y_shape"]
            expected_x_values = test_case["expected_x_values"]
            expected_y_values = test_case["expected_y_values"]

            dobj = self.da.get_data(self.ds, varname=varname, pulse=pulse)

            self.assertEqual(np.shape(dobj.xdata), expected_x_shape)
            self.assertEqual(np.shape(dobj.ydata), expected_y_shape)
            self.assertIsInstance(dobj.xdata, (np.ndarray, list))
            self.assertIsInstance(dobj.ydata, (np.ndarray, list))
            np.testing.assert_array_equal(dobj.xdata, expected_x_values)
            np.testing.assert_array_equal(dobj.ydata, expected_y_values)

    def test_CSVAccessByPulseWithTime(self) -> None:
        test_cases = [
            {
                "varname": "MAG-MCTB-F1:VAR1",
                "pulse": "ITER:MCTB-TEST/111",
                "tsS": -3.0,
                "tsE": 3.0,
                "expected_x_shape": (8,),
                "expected_y_shape": (8,),
            },
            {
                "varname": "MAG-MCTB-F1:VAR2",
                "pulse": "ITER:MCTB-TEST/111",
                "tsS": 0.0,
                "tsE": 2.0,
                "expected_x_shape": (5,),
                "expected_y_shape": (5,),
            }
        ]

        for test_case in test_cases:
            varname = test_case["varname"]
            pulse = test_case["pulse"]
            tsS = test_case["tsS"]
            tsE = test_case["tsE"]
            expected_x_shape = test_case["expected_x_shape"]
            expected_y_shape = test_case["expected_y_shape"]

            dobj = self.da.get_data(self.ds, varname=varname, pulse=pulse, tsS=tsS, tsE=tsE)

            self.assertEqual(np.shape(dobj.xdata), expected_x_shape)
            self.assertEqual(np.shape(dobj.ydata), expected_y_shape)
            self.assertIsInstance(dobj.xdata, (np.ndarray, list))
            self.assertIsInstance(dobj.ydata, (np.ndarray, list))


class LogScaleAxisTests(QAppOffscreenTestAdapter):
    """Log-scale Y axis behaviour mirroring the pyqtgraph backend: plain decade
    tick labels, no labelled minors and non-positive bounds falling back to
    autoscale."""

    @staticmethod
    def _new_axes():
        return Figure().add_subplot()

    def test_log_axis_uses_plain_decade_labels(self):
        parser = MatplotlibParser()
        ax = self._new_axes()
        parser.process_ipl_log_axis(ax.get_yaxis(), PlotXY(log_scale=True))
        y_axis = ax.get_yaxis()
        self.assertEqual(ax.get_yscale(), 'log')
        self.assertIsInstance(y_axis.get_major_formatter(), FuncFormatter)
        self.assertEqual(y_axis.get_major_formatter()(1000, 0), '1000')
        self.assertIsInstance(y_axis.get_minor_formatter(), NullFormatter)

    def test_axis_params_keep_log_locator_and_formatter(self):
        parser = MatplotlibParser()
        ax = self._new_axes()
        y_axis = ax.get_yaxis()
        parser.process_ipl_log_axis(y_axis, PlotXY(log_scale=True))
        parser.process_ipl_axis_params('black', 10, 5, LinearAxis(), y_axis)
        self.assertIsInstance(y_axis.get_major_locator(), LogLocator)
        self.assertIsInstance(y_axis.get_major_formatter(), FuncFormatter)

    def test_axis_params_linear_get_exponent_formatter(self):
        parser = MatplotlibParser()
        y_axis = self._new_axes().get_yaxis()
        parser.process_ipl_axis_params('black', 10, 5, LinearAxis(), y_axis)
        self.assertIsInstance(y_axis.get_major_locator(), MaxNLocator)
        self.assertIsInstance(y_axis.get_major_formatter(), ExponentScalarFormatter)

    def test_linear_mode_passes_limits_through(self):
        parser = MatplotlibParser()
        ax = self._new_axes()
        parser.set_impl_y_axis_limits(ax, (1.0, 10.0))
        lo, hi = ax.get_ylim()
        self.assertAlmostEqual(lo, 1.0, places=5)
        self.assertAlmostEqual(hi, 10.0, places=5)

    def test_log_mode_applies_positive_limits(self):
        parser = MatplotlibParser()
        ax = self._new_axes()
        ax.set_yscale('log')
        parser.set_impl_y_axis_limits(ax, (1e-4, 2e-4))
        lo, hi = ax.get_ylim()
        self.assertAlmostEqual(lo, 1e-4, places=10)
        self.assertAlmostEqual(hi, 2e-4, places=10)

    def test_log_mode_falls_back_to_autoscale_on_non_positive(self):
        import warnings
        parser = MatplotlibParser()
        ax = self._new_axes()
        ax.plot([0, 1, 2], [1, 10, 100])
        ax.set_yscale('log')
        with warnings.catch_warnings():
            warnings.simplefilter('error')  # the old code warned and ignored the limits
            parser.set_impl_y_axis_limits(ax, (-1.0, 5.0))
        self.assertTrue(ax.get_autoscaley_on())


if __name__ == '__main__':
    unittest.main()
