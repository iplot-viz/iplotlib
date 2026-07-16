import os
import tempfile
import unittest

import numpy as np
from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.ticker import MaxNLocator, LogLocator, LogFormatterSciNotation

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
    """Log-scale Y axis behaviour: the scale keeps its own locators, so ticks
    read as powers of ten with the minor ticks that give the log spacing, and
    non-positive bounds fall back to autoscale."""

    @staticmethod
    def _new_axes():
        fig = Figure()
        FigureCanvasAgg(fig)  # real renderer so draws update tick labels/offset
        return fig.add_subplot()

    @staticmethod
    def _log_axis(parser, ax):
        y_axis = ax.get_yaxis()
        parser.process_ipl_log_axis(y_axis, PlotXY(log_scale=True))
        parser.process_ipl_axis_params('black', 10, 5, LinearAxis(), y_axis)
        return y_axis

    def test_log_axis_keeps_scale_locators(self):
        parser = MatplotlibParser()
        ax = self._new_axes()
        y_axis = self._log_axis(parser, ax)
        self.assertEqual(ax.get_yscale(), 'log')
        # The linear axis locator/formatter must not overwrite the log ones.
        self.assertIsInstance(y_axis.get_major_locator(), LogLocator)
        self.assertIsInstance(y_axis.get_major_formatter(), LogFormatterSciNotation)

    def test_log_axis_multidecade_ticks_are_powers_of_ten(self):
        parser = MatplotlibParser()
        ax = self._new_axes()
        y_axis = self._log_axis(parser, ax)
        ax.set_ylim(1e-2, 1e4)
        ax.figure.canvas.draw()
        self.assertEqual([t.get_text() for t in y_axis.get_majorticklabels()
                          if t.get_text()][:3],
                         ['$\\mathdefault{10^{-3}}$', '$\\mathdefault{10^{-2}}$',
                          '$\\mathdefault{10^{-1}}$'])
        # Minor ticks are what make the log spacing visible.
        self.assertGreater(len(y_axis.get_minorticklocs()), 10)

    def test_log_axis_subdecade_labels_intermediate_ticks(self):
        # A view narrower than a decade contains no power of ten, so the
        # intermediate ticks carry the labels.
        parser = MatplotlibParser()
        ax = self._new_axes()
        y_axis = self._log_axis(parser, ax)
        ax.set_ylim(1.12e-4, 2.08e-4)
        ax.figure.canvas.draw()
        labels = [t.get_text() for t in y_axis.get_minorticklabels() if t.get_text()]
        self.assertIn('$\\mathdefault{1.2\\times10^{-4}}$', labels)
        self.assertIn('$\\mathdefault{2\\times10^{-4}}$', labels)

    def test_log_formatter_readout_is_full_data_value(self):
        # Crosshair value labels go through Axes.format_ydata.
        parser = MatplotlibParser()
        ax = self._new_axes()
        self._log_axis(parser, ax)
        ax.set_ylim(1.12e-4, 2.08e-4)
        ax.figure.canvas.draw()
        self.assertEqual(ax.format_ydata(1.5e-4), '0.00015')

    def test_autoscale_log_pads_multiplicatively_and_skips_non_positive(self):
        from iplotlib.core.impl_base import ImplementationPlotCacheItem
        parser = MatplotlibParser()
        ax = self._new_axes()
        ax._ipl_cache_item = ImplementationPlotCacheItem()
        ax.plot([0.0, 1.0, 2.0, 3.0], [-5.0, 10.0, 100.0, 10000.0])
        ax.set_yscale('log')
        ax.set_xlim(-0.5, 3.5)
        parser.autoscale_y_axis(ax)
        lo, hi = ax.get_ylim()
        # padded below the smallest positive sample (negatives are not on a
        # log axis) and above the maximum, never triggering global autoscale
        self.assertGreater(lo, 0.0)
        self.assertLess(lo, 10.0)
        self.assertGreater(hi, 10000.0)
        self.assertFalse(ax.get_autoscaley_on())

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
