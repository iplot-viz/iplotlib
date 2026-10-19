"""With worker processes, a change of the view draws at once the data the signals have and reads
the data of the new range in the background; the signals are drawn again when they arrive."""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from iplotlib.core.canvas import Canvas
from iplotlib.core.plot import PlotXY
from iplotlib.core.signal import SignalXY
from iplotlib.interface.iplotSignalAdapter import AccessHelper, ParserHelper
from iplotlib.qt.gui.iplotQtCanvasFactory import IplotQtCanvasFactory
from iplotlib.qt.testing import ensure_qapp

T0 = 1_788_873_880_000_000_000
HOUR = 3600 * 10**9
ZOOM = (T0 + 600 * 10**9, T0 + 660 * 10**9)
_SAMPLE_LIMIT = ('Number of samples in reply exceeds available limit. Reduce request interval, use decimation '
                 'or read data by chunks.')
_read_in_this_process = AccessHelper._request_data


class _DataAccess:
    """Asks for decimation, as a large archive would, and answers with the width of the
    requested range in seconds: what is drawn tells which range was read. Records the reads
    made in this thread apart from those made for the worker processes."""

    def __init__(self):
        self.reads, self.worker_reads = [], []
        self.for_workers = False

    def get_data(self, data_s_name, **kwargs):
        if kwargs['nbp'] == -1:
            return SimpleNamespace(errcode=-1, errdesc=_SAMPLE_LIMIT)
        (self.worker_reads if self.for_workers else self.reads).append((kwargs['varname'], kwargs['tsS'], kwargs['tsE']))
        x = np.linspace(kwargs['tsS'], kwargs['tsE'], 50).astype(np.int64)
        return SimpleNamespace(errcode=0, errdesc='', xdata=x, ydata=np.full(50, (kwargs['tsE'] - kwargs['tsS']) / 1e9),
                               xunit='ns', yunit='A', resolved_pulse=None)

    def get_data_source(self, name):
        return None


class _PendingFetch:
    def __init__(self, requests, on_done):
        self.requests = list(requests)
        self.on_done = on_done
        self.cancelled = self.arrived = False

    def cancel(self):
        self.cancelled = True

    def arrive(self):
        self.arrived = True
        self.on_done(_read_for_workers(self.requests))


def _read_for_workers(requests):
    AccessHelper.da.for_workers = True
    try:
        return {AccessHelper.request_key(params): _read_in_this_process(**dict(params)) for params in requests}
    finally:
        AccessHelper.da.for_workers = False


class _Pool:
    """Reads when the test says the data arrive."""

    def __init__(self):
        self.fetches = []

    def fetch(self, requests, progress=None):
        return _read_for_workers(list(requests))

    def fetch_later(self, requests, on_done):
        self.fetches.append(_PendingFetch(requests, on_done))
        return self.fetches[-1]

    def pending(self):
        return [fetch for fetch in self.fetches if not fetch.cancelled and not fetch.arrived]

    def arrive(self):
        for fetch in self.pending():
            fetch.arrive()


class ViewReadsInBackgroundTest(unittest.TestCase):
    def setUp(self):
        self.app = ensure_qapp()
        ParserHelper.env.clear()
        self.addCleanup(ParserHelper.env.clear)
        for name in ('da', 'pool'):
            self.addCleanup(setattr, AccessHelper, name, getattr(AccessHelper, name))
        AccessHelper.da = self.da = _DataAccess()
        AccessHelper.pool = None

    def _draw(self, backend):
        core = Canvas(2, 1, title="background reads", shared_x_axis=True)
        signals = []
        for name in ('VAR-A', 'VAR-B'):
            plot = PlotXY()
            signals.append(SignalXY(name=name, label=name, data_source='uda', ts_start=T0, ts_end=T0 + HOUR))
            plot.add_signal(signals[-1])
            plot.axes[0].is_date = True
            core.add_plot(plot, 0)
        qt_canvas = IplotQtCanvasFactory.new(backend, canvas=core)
        self.addCleanup(qt_canvas.deleteLater)
        qt_canvas.set_canvas(core)
        qt_canvas.resize(1200, 800)
        self.app.processEvents()
        self.da.reads.clear()
        self.da.worker_reads.clear()
        parser = qt_canvas._parser
        impls = [parser._plot_impl_plot_lut.get(id(core.plots[0][row]))[0] for row in range(2)]
        return qt_canvas, parser, impls, signals

    @staticmethod
    def _drawn(parser, impl):
        lines, _, _ = parser.get_impl_lines(impl)
        return [np.unique(np.asarray(parser.get_impl_data(line)[1])).tolist() for line in lines]

    def test_a_zoom_draws_at_once_and_again_when_the_data_arrive(self):
        for backend in ('pyqt', 'matplotlib'):
            with self.subTest(backend=backend):
                qt_canvas, parser, impls, signals = self._draw(backend)
                AccessHelper.pool = pool = _Pool()
                self.da.reads.clear()

                with patch.object(qt_canvas, 'stats') as stats:
                    parser.set_oaw_axis_limits(impls[0], 0, ZOOM)
                    self.app.processEvents()

                    self.assertEqual(self.da.reads, [])
                    requested = sorted((params['varname'], params['tsS'], params['tsE'])
                                       for fetch in pool.pending() for params in fetch.requests)
                    self.assertEqual(requested, [('VAR-A', *ZOOM), ('VAR-B', *ZOOM)])
                    self.assertEqual([self._drawn(parser, impl) for impl in impls], [[[3600.0]], [[3600.0]]])

                    pool.arrive()
                    self.app.processEvents()

                self.assertEqual([self._drawn(parser, impl) for impl in impls], [[[60.0]], [[60.0]]])
                self.assertEqual(self.da.reads, [])
                self.assertEqual(sorted(self.da.worker_reads), [('VAR-A', *ZOOM), ('VAR-B', *ZOOM)])
                self.assertTrue(stats.called)
                self.assertEqual(parser._view_reads, {})

    def test_a_new_zoom_replaces_one_still_reading(self):
        for backend in ('pyqt', 'matplotlib'):
            with self.subTest(backend=backend):
                qt_canvas, parser, impls, signals = self._draw(backend)
                AccessHelper.pool = pool = _Pool()

                parser.set_oaw_axis_limits(impls[0], 0, (T0, T0 + 1800 * 10**9))
                self.app.processEvents()
                first = pool.pending()
                parser.set_oaw_axis_limits(impls[0], 0, ZOOM)
                self.app.processEvents()

                self.assertTrue(first and all(fetch.cancelled for fetch in first))
                pool.arrive()
                self.app.processEvents()
                self.assertEqual([self._drawn(parser, impl) for impl in impls], [[[60.0]], [[60.0]]])

    def test_a_new_canvas_forgets_the_reads_of_the_previous_one(self):
        for backend in ('pyqt', 'matplotlib'):
            with self.subTest(backend=backend):
                qt_canvas, parser, impls, signals = self._draw(backend)
                AccessHelper.pool = pool = _Pool()
                parser.set_oaw_axis_limits(impls[0], 0, ZOOM)
                self.app.processEvents()

                qt_canvas.drop_view_reads()

                self.assertTrue(pool.fetches and all(fetch.cancelled for fetch in pool.fetches))
                self.assertEqual(parser._view_reads, {})

    def test_data_that_arrive_while_the_view_is_dragged_wait_for_its_end(self):
        for backend in ('pyqt', 'matplotlib'):
            with self.subTest(backend=backend):
                qt_canvas, parser, impls, signals = self._draw(backend)
                AccessHelper.pool = pool = _Pool()
                parser.set_oaw_axis_limits(impls[0], 0, ZOOM)
                self.app.processEvents()

                parser.begin_interactive_pan()
                pool.arrive()
                self.app.processEvents()

                self.assertEqual([self._drawn(parser, impl) for impl in impls], [[[3600.0]], [[3600.0]]])
                # A drag that ends where it began leaves the data that arrived meanwhile valid.
                parser.end_interactive_pan()
                self.app.processEvents()
                self.assertEqual([self._drawn(parser, impl) for impl in impls], [[[60.0]], [[60.0]]])
                self.assertEqual(pool.pending(), [])

    def test_undo_reads_the_restored_range_in_the_background(self):
        for backend in ('pyqt', 'matplotlib'):
            with self.subTest(backend=backend):
                qt_canvas, parser, impls, signals = self._draw(backend)
                AccessHelper.pool = pool = _Pool()
                qt_canvas.stage_view_lim_cmd(impls[0], name='Zoom')
                parser.set_oaw_axis_limits(impls[0], 0, ZOOM)
                self.app.processEvents()
                while len(qt_canvas._staging_cmds):
                    qt_canvas.commit_view_lim_cmd(impls[0])
                while len(qt_canvas._commitd_cmds):
                    qt_canvas.push_view_lim_cmd()
                pool.arrive()
                self.app.processEvents()
                self.da.reads.clear()

                parser._hm.undo()
                self.app.processEvents()

                self.assertEqual(self.da.reads, [])
                while pool.pending():
                    pool.arrive()
                    self.app.processEvents()
                self.assertEqual([self._drawn(parser, impl) for impl in impls], [[[3600.0]], [[3600.0]]])

    def test_a_redraw_that_needs_other_data_reads_them_in_the_background(self):
        for backend in ('pyqt', 'matplotlib'):
            with self.subTest(backend=backend):
                qt_canvas, parser, impls, signals = self._draw(backend)
                AccessHelper.pool = pool = _Pool()
                self.da.reads.clear()
                # As focusing a plot gives its window to the plots it hides.
                for signal in signals:
                    signal.set_xranges(ZOOM)

                qt_canvas.refresh()
                self.app.processEvents()

                self.assertEqual(self.da.reads, [])
                self.assertEqual(sorted(self.da.worker_reads), [('VAR-A', *ZOOM), ('VAR-B', *ZOOM)])
                # The redraw made new implementation plots.
                impls = [parser._plot_impl_plot_lut.get(id(signal.parent()))[0] for signal in signals]
                self.assertEqual([self._drawn(parser, impl) for impl in impls], [[[60.0]], [[60.0]]])

    def test_without_worker_processes_a_zoom_reads_at_once(self):
        for backend in ('pyqt', 'matplotlib'):
            with self.subTest(backend=backend):
                qt_canvas, parser, impls, signals = self._draw(backend)
                self.da.reads.clear()

                parser.set_oaw_axis_limits(impls[0], 0, ZOOM)
                self.app.processEvents()

                self.assertEqual(sorted(self.da.reads), [('VAR-A', *ZOOM), ('VAR-B', *ZOOM)])
                self.assertEqual([self._drawn(parser, impl) for impl in impls], [[[60.0]], [[60.0]]])


if __name__ == '__main__':
    unittest.main()
