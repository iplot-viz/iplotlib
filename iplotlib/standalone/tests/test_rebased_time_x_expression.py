"""Plots whose X re-bases time under shared time, on both backends.

An X expression such as '${self}.time - T0' reads the time buffer but shows the
time elapsed since T0: an absolute time window means nothing on that axis, and
the window the plot requests is mapped back from its view through the samples
in memory, so undo, zoom out and Home must be able to widen it again. The
archive stub serves the samples inside the requested window, so every refetch
those gestures trigger is real.
"""

import types
import unittest

import numpy as np

from iplotlib.core.canvas import Canvas
from iplotlib.core.impl_base import BackendParserBase
from iplotlib.core.plot import PlotXY
from iplotlib.core.signal import SignalXY
from iplotlib.interface.iplotSignalAdapter import AccessHelper, ParserHelper
from iplotlib.qt.gui.iplotQtCanvasFactory import IplotQtCanvasFactory
from iplotlib.qt.testing import ensure_qapp

BACKENDS = ('matplotlib', 'pyqt')
SECOND = 1_000_000_000
STEP = SECOND // 1000
ABS_WINDOW = (1_790_181_946_767_360_892, 1_790_181_953_407_599_253)
REL_WINDOW = (1_790_181_951_942_473_159, 1_790_181_952_942_473_159)
REL_X_EXPR = '${self}.time-np.int64(%d)' % REL_WINDOW[0]


class _ArchiveStub:
    """Raw samples every STEP inside the requested window, like an archive read."""

    def __init__(self):
        self.requests = []

    def get_data_source(self, name):
        return None

    @staticmethod
    def _samples(request):
        grid = np.arange(ABS_WINDOW[0] - SECOND, REL_WINDOW[1] + SECOND, STEP, dtype=np.int64)
        return grid[(grid >= int(request['tsS'])) & (grid <= int(request['tsE']))]

    def get_data(self, **request):
        self.requests.append(request['varname'])
        x = self._samples(request)
        return types.SimpleNamespace(errcode=0, errdesc='OK', xdata=x, ydata=np.sin(x / 1e8),
                                     xunit='ns', yunit='V', resolved_pulse=None)

    def get_envelope(self, **request):
        self.requests.append(request['varname'])
        x = self._samples(request)
        avg = np.sin(x / 1e8)
        return types.SimpleNamespace(errcode=0, errdesc='OK', xdata=x, ydata_min=avg - 1,
                                     ydata_max=avg + 1, ydata_avg=avg,
                                     xunit='ns', yunit='V', resolved_pulse=None)


class RebasedTimeXExpressionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = ensure_qapp()

    def setUp(self) -> None:
        ParserHelper.env.clear()
        self._saved_da = AccessHelper.da
        self.archive = AccessHelper.da = _ArchiveStub()

    def tearDown(self) -> None:
        AccessHelper.da = self._saved_da

    def _build(self, backend, envelope=False):
        """A time plot and a plot drawing its own time window since its start."""
        canvas = Canvas(2, 1, title="rebased_time", shared_x_axis=True)
        time_plot, rebased_plot = PlotXY(), PlotXY()
        time_plot.add_signal(SignalXY(label="abs", name="ABS", data_source="stub",
                                      ts_start=ABS_WINDOW[0], ts_end=ABS_WINDOW[1]))
        rebased_plot.add_signal(SignalXY(label="rel", name="REL", data_source="stub", envelope=envelope,
                                         ts_start=REL_WINDOW[0], ts_end=REL_WINDOW[1], x_expr=REL_X_EXPR))
        canvas.add_plot(time_plot, 0)
        canvas.add_plot(rebased_plot, 0)
        qt_canvas = IplotQtCanvasFactory.new(backend, canvas=canvas)
        qt_canvas.set_canvas(canvas)
        qt_canvas.resize(800, 600)
        qt_canvas._mmode = 'MMZoom'
        self.app.processEvents()
        parser = qt_canvas._parser
        time_impl = parser._plot_impl_plot_lut[id(time_plot)][0]
        rebased_impl = parser._plot_impl_plot_lut[id(rebased_plot)][0]
        return qt_canvas, parser, time_impl, rebased_impl, rebased_plot.signals[1][0]

    def _zoom(self, qt_canvas, parser, impl_plot, window):
        """A zoom through the command pipeline, so it can be undone."""
        qt_canvas.stage_view_lim_cmd(impl_plot)
        parser.set_oaw_axis_limits(impl_plot, 0, window)
        BackendParserBase._x_axis_update_callback(parser, impl_plot)
        self.app.processEvents()
        qt_canvas.commit_view_lim_cmd(impl_plot)
        qt_canvas.push_view_lim_cmd()

    @staticmethod
    def _fraction(view, begin, end):
        low, high = view
        return low + begin * (high - low), low + end * (high - low)

    def test_time_plot_zoom_leaves_the_rebased_plot_alone(self):
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                qt_canvas, parser, time_impl, rebased_impl, signal = self._build(backend)
                view = parser.get_oaw_axis_limits(rebased_impl, 0)
                samples = len(signal.x_data)
                self.assertNotIn(rebased_impl, parser._get_all_shared_axes(time_impl))

                window = self._fraction(ABS_WINDOW, 0.2, 0.25)
                self._zoom(qt_canvas, parser, time_impl, (int(window[0]), int(window[1])))

                self.assertEqual(parser.get_oaw_axis_limits(rebased_impl, 0), view)
                self.assertEqual(len(signal.x_data), samples)

    def test_undo_brings_the_data_back_with_a_single_request(self):
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                qt_canvas, parser, _, rebased_impl, signal = self._build(backend)
                drawn = np.asarray(signal.x_data).copy()
                view = parser.get_oaw_axis_limits(rebased_impl, 0)
                self._zoom(qt_canvas, parser, rebased_impl, self._fraction(view, 0.2, 0.3))
                self.assertLess(len(signal.x_data), len(drawn) // 2)

                before = len(self.archive.requests)
                parser._hm.undo()
                self.app.processEvents()

                np.testing.assert_array_equal(np.asarray(signal.x_data), drawn)
                self.assertEqual(self.archive.requests[before:].count('REL'), 1)

    def test_zoom_out_brings_the_rest_of_the_data_back(self):
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                qt_canvas, parser, _, rebased_impl, signal = self._build(backend)
                drawn = np.asarray(signal.x_data).copy()
                view = parser.get_oaw_axis_limits(rebased_impl, 0)
                self._zoom(qt_canvas, parser, rebased_impl, self._fraction(view, 0.2, 0.3))

                self._zoom(qt_canvas, parser, rebased_impl, view)

                np.testing.assert_array_equal(np.asarray(signal.x_data), drawn)

    def test_zoom_after_home_requests_the_matching_time_window(self):
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                qt_canvas, parser, _, rebased_impl, signal = self._build(backend)
                view = parser.get_oaw_axis_limits(rebased_impl, 0)
                self._zoom(qt_canvas, parser, rebased_impl, self._fraction(view, 0.2, 0.3))
                qt_canvas.reset_all_views()
                self.app.processEvents()

                low, high = self._fraction(view, 0.5, 0.6)
                self._zoom(qt_canvas, parser, rebased_impl, (low, high))

                x = np.asarray(signal.x_data)
                self.assertGreater(len(x), 0)
                self.assertGreaterEqual(x.min(), low - 2 * STEP)
                self.assertLessEqual(x.max(), high + 2 * STEP)

    def test_envelope_with_rebased_time_is_drawn(self):
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                _, _, _, _, signal = self._build(backend, envelope=True)
                self.assertGreater(len(signal.x_data), 0)
                self.assertEqual(len(signal.x_data), len(signal.data_store[0]))
                self.assertLess(float(np.max(signal.x_data)), 2 * SECOND)


if __name__ == '__main__':
    unittest.main()
