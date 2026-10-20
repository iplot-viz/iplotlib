"""With worker processes, a change of the view draws at once the data the signals have and reads
the data of the new range in the background; the signals are drawn again when they arrive."""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
from PySide6.QtCore import QTimer

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


def _variable(name, **kwargs):
    return SignalXY(name=name, label=name, data_source='uda', ts_start=T0, ts_end=T0 + HOUR, **kwargs)


class ViewReadsInBackgroundTest(unittest.TestCase):
    def setUp(self):
        self.app = ensure_qapp()
        ParserHelper.env.clear()
        self.addCleanup(ParserHelper.env.clear)
        for name in ('da', 'pool'):
            self.addCleanup(setattr, AccessHelper, name, getattr(AccessHelper, name))
        AccessHelper.da = self.da = _DataAccess()
        AccessHelper.pool = None

    def _draw(self, backend, autoscale=False, signals=None):
        """A plot for each signal, VAR-A and VAR-B unless given, sharing the time axis."""
        signals = signals or [_variable(name) for name in ('VAR-A', 'VAR-B')]
        core = Canvas(len(signals), 1, title="background reads", shared_x_axis=True, autoscale=autoscale)
        for signal in signals:
            plot = PlotXY()
            plot.add_signal(signal)
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
        impls = [parser._plot_impl_plot_lut.get(id(core.plots[0][row]))[0] for row in range(len(signals))]
        return qt_canvas, parser, impls, signals

    @staticmethod
    def _drawn(parser, impl):
        lines, _, _ = parser.get_impl_lines(impl)
        return [np.unique(np.asarray(parser.get_impl_data(line)[1])).tolist() for line in lines]

    @staticmethod
    def _zoom(parser, impl, window):
        """A zoom drawn with the mouse: the X range, then the Y range, whose change autoscales the canvas."""
        low, high = parser.get_oaw_axis_limits(impl, 1)
        parser.set_oaw_axis_limits(impl, 0, window)
        parser.set_oaw_axis_limits(impl, 1, (low + (high - low) / 4, high - (high - low) / 4))

    def _zoom_cmd(self, qt_canvas, parser, impl, window):
        """A zoom drawn with the mouse, recorded in the history as the mouse gestures record it."""
        qt_canvas.stage_view_lim_cmd(impl, name='Zoom')
        self._zoom(parser, impl, window)
        self.app.processEvents()
        while len(qt_canvas._staging_cmds):
            qt_canvas.commit_view_lim_cmd(impl)
        while len(qt_canvas._commitd_cmds):
            qt_canvas.push_view_lim_cmd()

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

    def test_a_canvas_that_autoscales_fits_the_y_axis_to_the_data_that_arrive(self):
        for backend in ('pyqt', 'matplotlib'):
            with self.subTest(backend=backend):
                qt_canvas, parser, impls, signals = self._draw(backend, autoscale=True)
                AccessHelper.pool = pool = _Pool()
                self._zoom(parser, impls[0], ZOOM)
                self.app.processEvents()

                with self.assertNoLogs('iplotlib.core.impl_base', level='ERROR'), \
                        self.assertNoLogs('iplotlib.data_access.access_pool', level='ERROR'):
                    pool.arrive()
                    self.app.processEvents()

                self.assertEqual([self._drawn(parser, impl) for impl in impls], [[[60.0]], [[60.0]]])
                for impl in impls:
                    low, high = parser.get_oaw_axis_limits(impl, 1)
                    self.assertTrue(0 < low < 60.0 < high, (low, high))

    def test_redo_shows_the_y_axis_fitted_to_the_data_that_arrived(self):
        for backend in ('pyqt', 'matplotlib'):
            for during_commit in (False, True):
                with self.subTest(backend=backend, during_commit=during_commit):
                    qt_canvas, parser, impls, signals = self._draw(backend, autoscale=True)
                    AccessHelper.pool = pool = _Pool()
                    qt_canvas.stage_view_lim_cmd(impls[0], name='Zoom')
                    self._zoom(parser, impls[0], ZOOM)
                    if during_commit:
                        # As the data a worker still holds in its cache arrive.
                        QTimer.singleShot(0, pool.arrive)
                    while len(qt_canvas._staging_cmds):
                        qt_canvas.commit_view_lim_cmd(impls[0])
                    while len(qt_canvas._commitd_cmds):
                        qt_canvas.push_view_lim_cmd()
                    self._arrive_all(pool)
                    fitted = [parser.get_oaw_axis_limits(impl, 1) for impl in impls]
                    self.assertTrue(all(0 < low < 60.0 < high for low, high in fitted), fitted)

                    parser._hm.undo()
                    self._arrive_all(pool)
                    parser._hm.redo()
                    self._arrive_all(pool)

                    np.testing.assert_allclose([parser.get_oaw_axis_limits(impl, 1) for impl in impls], fitted)

    def test_the_history_fits_again_a_y_axis_recorded_before_the_data_of_its_view_arrived(self):
        # Undo before the data of a zoom arrive, then redo; a second zoom before they arrive, then undo: the view
        # comes back with the Y axis fitted to its data, as when they are read at once.
        zoom2 = (ZOOM[0] + 20 * 10**9, ZOOM[1] - 20 * 10**9)
        for backend in ('pyqt', 'matplotlib'):
            for first, then in (('undo', 'redo'), ('zoom', 'undo')):
                with self.subTest(backend=backend, steps=(first, then)):
                    qt_canvas, parser, impls, signals = self._draw(backend, autoscale=True)
                    AccessHelper.pool = pool = _Pool()
                    self._zoom_cmd(qt_canvas, parser, impls[0], ZOOM)
                    if first == 'undo':
                        parser._hm.undo()
                    else:
                        self._zoom_cmd(qt_canvas, parser, impls[0], zoom2)
                    self._arrive_all(pool)
                    getattr(parser._hm, then)()
                    self._arrive_all(pool)

                    self.assertEqual([self._drawn(parser, impl) for impl in impls], [[[60.0]], [[60.0]]])
                    self._assert_y_axes_show(parser, impls, 60.0)
                    # Going back and forth again shows it before any data arrive, and after.
                    getattr(parser._hm, 'undo' if then == 'redo' else 'redo')()
                    getattr(parser._hm, then)()
                    self.app.processEvents()
                    self._assert_y_axes_show(parser, impls, 60.0)
                    self._arrive_all(pool)
                    self._assert_y_axes_show(parser, impls, 60.0)

    def test_a_redraw_before_the_data_of_a_zoom_arrive_fits_the_y_axis_to_the_data_it_draws(self):
        # A redraw reads the data at once; the plots that the focus hides fit them once they are drawn again.
        for backend in ('pyqt', 'matplotlib'):
            for redraw in ('refresh', 'focus'):
                with self.subTest(backend=backend, redraw=redraw):
                    qt_canvas, parser, impls, signals = self._draw(backend, autoscale=True)
                    AccessHelper.pool = pool = _Pool()
                    self._zoom(parser, impls[0], ZOOM)
                    self.app.processEvents()

                    if redraw == 'refresh':
                        qt_canvas.refresh()
                    else:
                        qt_canvas._full_screen_mode_on(impls[0])
                        self._arrive_all(pool)
                        qt_canvas._full_screen_mode_off()
                    self._arrive_all(pool)

                    impls = [parser._plot_impl_plot_lut.get(id(signal.parent()))[0] for signal in signals]
                    self.assertEqual([self._drawn(parser, impl) for impl in impls], [[[60.0]], [[60.0]]])
                    self._assert_y_axes_show(parser, impls, 60.0)

    def _assert_y_axes_show(self, parser, impls, value):
        y_ranges = [parser.get_oaw_axis_limits(impl, 1) for impl in impls]
        self.assertTrue(all(low < value < high for low, high in y_ranges), y_ranges)

    def test_a_change_of_the_x_range_alone_keeps_the_y_axis_as_when_the_data_are_read_at_once(self):
        # As a drag along the time axis: no change of the Y range follows it to autoscale the canvas.
        for backend in ('pyqt', 'matplotlib'):
            with self.subTest(backend=backend):
                shown = []
                for workers in (False, True):
                    qt_canvas, parser, impls, signals = self._draw(backend, autoscale=True)
                    AccessHelper.pool = pool = _Pool() if workers else None
                    parser.set_oaw_axis_limits(impls[0], 0, ZOOM)
                    self._arrive_all(pool)
                    self.assertEqual([self._drawn(parser, impl) for impl in impls], [[[60.0]], [[60.0]]])
                    shown.append([parser.get_oaw_axis_limits(impl, 1) for impl in impls])
                np.testing.assert_allclose(shown[1], shown[0])

    def _arrive_all(self, pool, last_first=False):
        """Let every read in the background arrive, those asked for last first if `last_first`."""
        self.app.processEvents()
        while pool is not None and pool.pending():
            pending = pool.pending()
            for fetch in reversed(pending) if last_first else pending:
                if fetch in pool.pending():
                    fetch.arrive()
            self.app.processEvents()

    def test_the_expressions_of_an_alias_drawn_in_the_next_plots_get_the_new_range_too(self):
        for backend in ('pyqt', 'matplotlib'):
            for workers, last_first in ((True, False), (True, True), (False, False)):
                with self.subTest(backend=backend, workers=workers, last_first=last_first):
                    ParserHelper.env.clear()
                    signals = [_variable('VAR-A', alias='a'), _variable('${a}*2', alias='p'), _variable('${p}+1')]
                    qt_canvas, parser, impls, _ = self._draw(backend, signals=signals)
                    AccessHelper.pool = pool = _Pool() if workers else None

                    parser.set_oaw_axis_limits(impls[0], 0, ZOOM)
                    self._arrive_all(pool, last_first)

                    drawn = {signal.label: self._drawn(parser, impl) for signal, impl in zip(signals, impls)}
                    self.assertEqual(drawn, {'a': [[60.0]], 'p': [[120.0]], '${p}+1': [[121.0]]})
                    if workers:
                        self.assertEqual(self.da.reads, [])

    def test_a_signal_whose_y_uses_another_alias_gets_the_data_of_both(self):
        for backend in ('pyqt', 'matplotlib'):
            with self.subTest(backend=backend):
                ParserHelper.env.clear()
                _variable('VAR-A', alias='a')  # read by the expression only
                signal = _variable('VAR-B', y_expr='${self}.data + ${a}.data')
                qt_canvas, parser, impls, _ = self._draw(backend, signals=[signal])
                AccessHelper.pool = pool = _Pool()

                with self.assertNoLogs('iplotlib.core.impl_base', level='WARNING'):
                    parser.set_oaw_axis_limits(impls[0], 0, ZOOM)
                    self._arrive_all(pool)
                signal.get_data()

                self.assertEqual(self._drawn(parser, impls[0]), [[120.0]])
                self.assertEqual(self.da.reads, [])

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
            for arrive_first in (True, False):
                with self.subTest(backend=backend, arrive_first=arrive_first):
                    qt_canvas, parser, impls, signals = self._draw(backend)
                    AccessHelper.pool = pool = _Pool()
                    parser.set_oaw_axis_limits(impls[0], 0, ZOOM)
                    self.app.processEvents()
                    fetches = len(pool.fetches)

                    parser.begin_interactive_pan()
                    if arrive_first:
                        pool.arrive()
                        self.app.processEvents()
                    # Away and back. The width changes a little: pyqtgraph takes a move of the same width in the
                    # offset of its axis, without a change of its range.
                    parser.set_oaw_axis_limits(impls[0], 0, (ZOOM[0] + 5 * 10**9, ZOOM[1] + 5 * 10**9 + 5000))
                    self.app.processEvents()
                    parser.set_oaw_axis_limits(impls[0], 0, ZOOM)
                    self.app.processEvents()
                    if not arrive_first:
                        pool.arrive()
                        self.app.processEvents()

                    self.assertEqual([self._drawn(parser, impl) for impl in impls], [[[3600.0]], [[3600.0]]])
                    # A drag that ends where it began leaves the data that arrived meanwhile valid.
                    parser.end_interactive_pan()
                    self.app.processEvents()
                    self.assertEqual([self._drawn(parser, impl) for impl in impls], [[[60.0]], [[60.0]]])
                    self.assertEqual(len(pool.fetches), fetches)
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
