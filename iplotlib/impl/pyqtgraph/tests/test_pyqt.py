import os
import tempfile
import unittest

import numpy as np
from iplotDataAccess.dataAccess import DataAccess
from iplotlib.core.canvas import Canvas
from iplotlib.impl.pyqtgraph.pyQtGraphCanvas import PyQtGraphParser
from iplotlib.impl.pyqtgraph.tests.QAppOffscreenTestAdapter import QAppOffscreenTestAdapter
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

class PyQtGraphTesting(QAppOffscreenTestAdapter):
    def setUp(self) -> None:
        super().setUp()

        self.da = DataAccess()
        self.ds = "csv"

        # Use forward slashes for JSON compatibility on all platforms
        data_dir_escaped = data_dir.replace('\\', '/')
        dscfg = dscfg_csv % data_dir_escaped

        # Create temp file - on Windows we need to close it before reading
        self.temp_config_path = tempfile.mktemp(suffix='.cfg')
        with open(self.temp_config_path, 'w') as f:
            f.write(dscfg)

        os.environ.update({'IPLOT_SOURCES_CONFIG': os.path.abspath(self.temp_config_path)})
        if self.da.load_config(self.temp_config_path):
            AccessHelper.da = self.da

    def tearDown(self) -> None:
        # Clean up temp file
        if hasattr(self, 'temp_config_path'):
            try:
                os.unlink(self.temp_config_path)
            except OSError:
                pass
        super().tearDown()

    # --------------------------
    #           TESTS
    # --------------------------

    def test_01_null_refresh(self):
        canvas = Canvas(0, 0)
        self.pyqt_parser = PyQtGraphParser()
        self.pyqt_parser.process_ipl_canvas(canvas)

        size = self.pyqt_parser.figure.size()

        self.assertEqual(0, 0)
        self.assertEqual(0, 0)

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

    def test_CSVAccessByPulseWithTime(self) -> None:
        test_cases = [
            {
                "varname": "MAG-MCTB-F1:VAR1",
                "pulse": "ITER:MCTB-TEST/111",
                "tsS": -3.0,
                "tsE": 3.0,
                "expected_x_shape": (8,),
                "expected_y_shape": (8,),
                "expected_x_values": [-3.0, 0.0, 1.0, 1.1, 1.5, 2.0, 2.5, 3.0, 3.5],
                "expected_y_values": [2, 10, 11, 12, 12, 12, 12, 14]
            },
            {
                "varname": "MAG-MCTB-F1:VAR2",
                "pulse": "ITER:MCTB-TEST/111",
                "tsS": 0.0,
                "tsE": 2.0,
                "expected_x_shape": (5,),
                "expected_y_shape": (5,),
                "expected_x_values": [0.0, 1.0, 1.1, 1.5, 2.0],
                "expected_y_values": [10, 11, 12, 12, 12]
            }
        ]

        for test_case in test_cases:
            varname = test_case["varname"]
            pulse = test_case["pulse"]
            tsS = test_case["tsS"]
            tsE = test_case["tsE"]
            expected_x_shape = test_case["expected_x_shape"]
            expected_y_shape = test_case["expected_y_shape"]
            expected_x_values = test_case["expected_x_values"]
            expected_y_values = test_case["expected_y_values"]

            dobj = self.da.get_data(self.ds, varname=varname, pulse=pulse, tsS=tsS, tsE=tsE)

            self.assertEqual(np.shape(dobj.xdata), expected_x_shape)
            self.assertEqual(np.shape(dobj.ydata), expected_y_shape)
            self.assertIsInstance(dobj.xdata, (np.ndarray, list))
            self.assertIsInstance(dobj.ydata, (np.ndarray, list))


class SetYAxisLimitsLogModeTests(QAppOffscreenTestAdapter):
    """In log mode the viewport bounds must be log10-transformed so the
    log-projected curve stays visible without the user invoking Autoscale."""

    def _new_plot_item(self):
        import pyqtgraph as pg
        return pg.PlotItem()

    def test_linear_mode_passes_limits_through(self):
        parser = PyQtGraphParser()
        plot = self._new_plot_item()
        parser.set_impl_y_axis_limits(plot, (1.0, 10.0))
        lo, hi = plot.getViewBox().viewRange()[1]
        self.assertAlmostEqual(lo, 1.0, places=5)
        self.assertAlmostEqual(hi, 10.0, places=5)

    def test_log_mode_log10_transforms_limits(self):
        parser = PyQtGraphParser()
        plot = self._new_plot_item()
        plot.setLogMode(x=False, y=True)
        parser.set_impl_y_axis_limits(plot, (1e-4, 2e-4))
        lo, hi = plot.getViewBox().viewRange()[1]
        self.assertAlmostEqual(lo, np.log10(1e-4), places=5)
        self.assertAlmostEqual(hi, np.log10(2e-4), places=5)

    def test_log_mode_falls_back_to_autorange_on_non_positive(self):
        parser = PyQtGraphParser()
        plot = self._new_plot_item()
        plot.setLogMode(x=False, y=True)
        parser.set_impl_y_axis_limits(plot, (-1.0, 5.0))
        state = plot.getViewBox().state['autoRange']
        self.assertTrue(state[1])

    def test_set_then_get_log_mode_roundtrip_is_data_space(self):
        parser = PyQtGraphParser()
        plot = self._new_plot_item()
        plot.setLogMode(x=False, y=True)
        parser.set_impl_y_axis_limits(plot, (1e-4, 2e-4))
        lo, hi = parser.get_impl_y_axis_limits(plot)
        self.assertAlmostEqual(lo, 1e-4, places=10)
        self.assertAlmostEqual(hi, 2e-4, places=10)

    def test_set_then_get_linear_mode_passes_through(self):
        parser = PyQtGraphParser()
        plot = self._new_plot_item()
        parser.set_impl_y_axis_limits(plot, (1.0, 10.0))
        lo, hi = parser.get_impl_y_axis_limits(plot)
        self.assertAlmostEqual(lo, 1.0, places=5)
        self.assertAlmostEqual(hi, 10.0, places=5)

    def test_log_mode_round_trip_stable_across_two_iterations(self):
        # Simulates the undo/redo flow: get -> set -> get must keep values stable.
        parser = PyQtGraphParser()
        plot = self._new_plot_item()
        plot.setLogMode(x=False, y=True)
        parser.set_impl_y_axis_limits(plot, (1e-4, 2e-4))
        lo1, hi1 = parser.get_impl_y_axis_limits(plot)
        parser.set_impl_y_axis_limits(plot, (lo1, hi1))
        lo2, hi2 = parser.get_impl_y_axis_limits(plot)
        self.assertAlmostEqual(lo1, lo2, places=10)
        self.assertAlmostEqual(hi1, hi2, places=10)
        self.assertFalse(np.isnan(lo2))
        self.assertFalse(np.isnan(hi2))


class StreamUnitLabelRealignTests(QAppOffscreenTestAdapter):
    """A Y label arriving after the build (stream units) must retrigger the
    column width alignment."""

    def _parser_with_plot(self):
        import pyqtgraph as pg
        parser = PyQtGraphParser()
        plot = pg.PlotItem()
        parser._layout_stacks[(0, 0)] = {1: plot}
        calls = []
        parser.align_y_axis = lambda col: calls.append(col)
        return parser, plot, calls

    def test_changed_y_label_realigns_its_column(self):
        parser, plot, calls = self._parser_with_plot()
        parser.set_impl_y_axis_label_text(plot, '[kV]')
        self.assertEqual(calls, [0])

    def test_unchanged_y_label_does_not_realign(self):
        parser, plot, calls = self._parser_with_plot()
        parser.set_impl_y_axis_label_text(plot, '[kV]')
        parser.set_impl_y_axis_label_text(plot, '[kV]')
        self.assertEqual(calls, [0])


class LogModeConsistencyTests(QAppOffscreenTestAdapter):
    """Log-mode readouts must stay in data units and match the matplotlib
    backend: statistics read source values, autoscale must not re-log the
    already log-mapped display data, ticks read as powers of ten and the
    crosshair reads the plain value."""

    def _plot_with_curve(self, y_values, log=True):
        import pyqtgraph as pg
        plot = pg.PlotItem()
        x = np.arange(len(y_values), dtype=float)
        plot.plot(x, np.asarray(y_values, dtype=float))
        if log:
            plot.setLogMode(x=False, y=True)
        return plot

    def test_stats_source_data_is_data_space_in_log_mode(self):
        from iplotlib.qt.gui.IplotQtStatistics import _line_source_data
        plot = self._plot_with_curve([10.0, 100.0, 1000.0])
        line = plot.listDataItems()[0]
        # display data is log10-mapped ...
        np.testing.assert_allclose(np.asarray(line.getData()[1]), [1.0, 2.0, 3.0])
        # ... but statistics must read data units
        np.testing.assert_allclose(np.asarray(_line_source_data(line)[1]),
                                   [10.0, 100.0, 1000.0])

    def test_autoscale_log_mode_does_not_double_log(self):
        parser = PyQtGraphParser()
        plot = self._plot_with_curve([10.0, 100.0, 10000.0])
        plot.getViewBox().setXRange(-1.0, 3.0, padding=0)
        parser.autoscale_y_axis(plot, padding=0.0)
        lo, hi = parser.get_impl_y_axis_limits(plot)  # data space
        self.assertAlmostEqual(lo, 10.0, places=4)
        self.assertAlmostEqual(hi, 10000.0, places=4)

    def test_autoscale_log_mode_skips_non_positive_samples(self):
        parser = PyQtGraphParser()
        plot = self._plot_with_curve([-5.0, 10.0, 1000.0])
        plot.getViewBox().setXRange(-1.0, 3.0, padding=0)
        parser.autoscale_y_axis(plot, padding=0.0)
        lo, hi = parser.get_impl_y_axis_limits(plot)
        self.assertAlmostEqual(lo, 10.0, places=4)
        self.assertAlmostEqual(hi, 1000.0, places=4)

    def _log_axis(self):
        from iplotlib.impl.pyqtgraph.dateFormatter import NanosecondDateFormatter
        axis = NanosecondDateFormatter(orientation='left', is_date=False)
        axis.setLogMode(True)
        return axis

    def test_multidecade_ticks_are_powers_of_ten(self):
        axis = self._log_axis()
        levels = axis.tickValues(np.log10(1e-2), np.log10(1e4), 400)
        labelled = [axis.tickStrings(v, 1.0, sp) for sp, v in levels[:2]]
        self.assertEqual(labelled[0], ['10⁻²', '10⁰', '10²', '10⁴'])
        self.assertEqual(labelled[1], ['10⁻¹', '10¹', '10³'])
        # Minor ticks are what make the log spacing visible.
        self.assertGreater(len(levels[-1][1]), 10)

    def test_subdecade_view_labels_intermediate_ticks(self):
        # A view narrower than a decade contains no power of ten; pyqtgraph
        # alone yields a single tick there.
        axis = self._log_axis()
        levels = axis.tickValues(np.log10(1.12e-4), np.log10(2.08e-4), 400)
        spacing, positions = levels[0]
        self.assertGreater(len(positions), 1)
        self.assertEqual(axis.tickStrings(positions, 1.0, spacing),
                         ['1.2×10⁻⁴', '1.4×10⁻⁴', '1.6×10⁻⁴', '1.8×10⁻⁴', '2×10⁻⁴'])

    def test_crosshair_reads_plain_value_between_decades(self):
        from iplotlib.impl.pyqtgraph.pyQtCrosshair import pyQtCrosshair
        axis = self._log_axis()
        readout = pyQtCrosshair._format_left_axis_value(
            axis, np.log10(4.39), np.log10(5e-2), np.log10(2e4))
        self.assertEqual(readout, '4.39')


class MirroredAxisTests(QAppOffscreenTestAdapter):
    """pyqtgraph draws the grid from all four axes, so top/right must place
    their ticks where bottom/left placed theirs -- otherwise 'Show all ticks'
    lays a second grid, on an unrelated 1/2/5 ladder, over the first one."""

    def test_date_axis_top_ticks_match_the_bottom_ones(self):
        from iplotlib.impl.pyqtgraph.dateFormatter import MirroredAxisItem, NanosecondDateFormatter
        bottom = NanosecondDateFormatter(orientation='bottom')
        top = MirroredAxisItem(bottom, orientation='top')
        # 12 h window on 2025-08-06, the range of the reported workspace.
        lo, hi = 1754460000_000000000, 1754503200_000000000
        self.assertEqual(top.tickValues(lo, hi, 600), bottom.tickValues(lo, hi, 600))

    def test_numeric_axis_right_ticks_match_the_left_ones(self):
        from iplotlib.impl.pyqtgraph.dateFormatter import MirroredAxisItem, NanosecondDateFormatter
        left = NanosecondDateFormatter(orientation='left', is_date=False)
        left.set_ticks_number(3)
        right = MirroredAxisItem(left, orientation='right')
        self.assertEqual(right.tickValues(-1.2, 1.2, 300), left.tickValues(-1.2, 1.2, 300))

    def test_mirrored_axis_is_not_labelled(self):
        from iplotlib.impl.pyqtgraph.dateFormatter import MirroredAxisItem, NanosecondDateFormatter
        top = MirroredAxisItem(NanosecondDateFormatter(orientation='bottom'), orientation='top')
        self.assertEqual(top.tickStrings([1.0, 2.0], 1.0, 1.0), ['', ''])

    def test_built_plot_wires_the_mirrored_axes(self):
        from iplotlib.core.plot import PlotXY
        from iplotlib.core.signal import SignalXY
        from iplotlib.impl.pyqtgraph.dateFormatter import MirroredAxisItem

        canvas = Canvas(1, 1)
        plot = PlotXY()
        plot.axes[0].is_date = True
        signal = SignalXY(label='sig')
        signal.set_data([np.linspace(1754460000_000000000, 1754503200_000000000, 100).astype(np.int64),
                         np.sin(np.linspace(0, 6, 100))])
        plot.add_signal(signal)
        canvas.add_plot(plot, 0)

        parser = PyQtGraphParser()
        parser.process_ipl_canvas(canvas)
        impl_plot = parser._layout_stacks[(0, 0)][0]
        top, bottom = impl_plot.getAxis('top'), impl_plot.getAxis('bottom')
        self.assertIsInstance(top, MirroredAxisItem)
        self.assertIsInstance(impl_plot.getAxis('right'), MirroredAxisItem)
        lo, hi = impl_plot.getViewBox().viewRange()[0]
        self.assertEqual(top.tickValues(lo, hi, 600), bottom.tickValues(lo, hi, 600))


if __name__ == '__main__':
    unittest.main()
