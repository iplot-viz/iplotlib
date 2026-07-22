"""Tests for the per-signal sample cap, archive-window kwargs
(envelope vs raw, nbp gating), the empty-window last-value fallback,
and the _streaming_has_live flag set during backfill."""

import unittest
from threading import Event
from unittest.mock import MagicMock

import numpy as np

from iplotlib.data_access.streamer import CanvasStreamer


class _FakeBuf:
    """Stand-in for a BufferObject: array-like with a `unit` attribute."""

    def __init__(self, arr, unit=''):
        self._a = np.asarray(arr)
        self.unit = unit

    def __len__(self):
        return len(self._a)

    def __getitem__(self, item):
        return self._a[item]

    def __array__(self, dtype=None):
        return self._a if dtype is None else self._a.astype(dtype)


class _FakeSignal:
    """Minimal signal stub exposing only what the streamer touches."""

    def __init__(self, name='sig', envelope=False, data=None, x_data=None):
        self.name = name
        self.uid = id(self)
        self.envelope = envelope
        if data is None:
            self.data_store = [_FakeBuf([]), _FakeBuf([])]
        else:
            self.data_store = data
        self.inject_external = MagicMock()
        self._streaming_has_live = False
        # x_data is read by _wait_for_first_live; non-empty short-circuits the wait.
        self.x_data = [] if x_data is None else x_data
        self.y_data = []


class _FakeArchiveResponse:
    """Stand-in for a DataObj / DataEnvelope returned by UDA."""

    def __init__(self, x, y, errcode=0, xunit='', yunit='', ymin=None, ymax=None):
        self.xdata = np.asarray(x)
        self.ydata = np.asarray(y)
        self.errcode = errcode
        self.xunit = xunit
        self.yunit = yunit
        if ymin is not None:
            self.ydata_min = np.asarray(ymin)
            self.ydata_max = np.asarray(ymax)
            self.ydata_avg = np.asarray(y)


class ApplyCapTests(unittest.TestCase):
    """Tests for CanvasStreamer._apply_cap."""

    def setUp(self):
        self.streamer = CanvasStreamer(da=None)

    def test_noop_when_cap_is_zero(self):
        self.streamer._max_points = 0
        signal = _FakeSignal(data=[_FakeBuf([1, 2, 3]), _FakeBuf([10, 20, 30])])
        self.streamer._apply_cap(signal)
        signal.inject_external.assert_not_called()

    def test_noop_when_length_below_cap(self):
        self.streamer._max_points = 5
        signal = _FakeSignal(data=[_FakeBuf([1, 2, 3]), _FakeBuf([10, 20, 30])])
        self.streamer._apply_cap(signal)
        signal.inject_external.assert_not_called()

    def test_noop_when_length_equals_cap(self):
        self.streamer._max_points = 3
        signal = _FakeSignal(data=[_FakeBuf([1, 2, 3]), _FakeBuf([10, 20, 30])])
        self.streamer._apply_cap(signal)
        signal.inject_external.assert_not_called()

    def test_drops_oldest_when_length_exceeds_cap(self):
        self.streamer._max_points = 2
        signal = _FakeSignal(
            data=[_FakeBuf([1, 2, 3, 4]), _FakeBuf([10, 20, 30, 40])])
        self.streamer._apply_cap(signal)
        signal.inject_external.assert_called_once()
        kwargs = signal.inject_external.call_args.kwargs
        self.assertFalse(kwargs['append'])
        self.assertEqual(list(kwargs['d0']), [3, 4])
        self.assertEqual(list(kwargs['d1']), [30, 40])


class ArchiveKwargsTests(unittest.TestCase):
    """Tests for CanvasStreamer._archive_kwargs."""

    def setUp(self):
        self.streamer = CanvasStreamer(da=None)

    def test_raw_signal_without_cap_requests_extremities_only(self):
        self.streamer._max_points = 0
        kwargs = self.streamer._archive_kwargs(signal=_FakeSignal(envelope=False))
        self.assertEqual(kwargs, {'extremities': True})

    def test_raw_signal_with_cap_adds_nbp(self):
        self.streamer._max_points = 100
        kwargs = self.streamer._archive_kwargs(signal=_FakeSignal(envelope=False))
        self.assertEqual(kwargs, {'nbp': 100, 'extremities': True})

    def test_envelope_signal_omits_extremities(self):
        # Envelope buckets already cover boundaries; extremities=True crashes UDA.
        self.streamer._max_points = 50
        kwargs = self.streamer._archive_kwargs(signal=_FakeSignal(envelope=True))
        self.assertEqual(kwargs, {'nbp': 50})
        self.assertNotIn('extremities', kwargs)


class FetchLastArchiveValueTests(unittest.TestCase):
    """Tests for CanvasStreamer._fetch_last_archive_value (empty-window fallback)."""

    def setUp(self):
        self.signal = _FakeSignal(name='var')

    def test_passes_last_value_kwargs_to_data_access(self):
        fake_da = MagicMock()
        fake_da.get_archive_window.return_value = _FakeArchiveResponse(
            x=[42], y=[7.0], xunit='ns', yunit='V')
        streamer = CanvasStreamer(da=fake_da)
        result = streamer._fetch_last_archive_value('ds', self.signal, end_ns=999)
        fake_da.get_archive_window.assert_called_once_with(
            'ds', varname='var', tsS='0', tsE='999', nbp=1, decType='last')
        self.assertEqual(result[0].tolist(), [42])
        self.assertEqual(result[1].tolist(), [7.0])
        self.assertEqual(result[4], 'ns')
        self.assertEqual(result[5], 'V')

    def test_returns_six_nones_when_errcode_nonzero(self):
        fake_da = MagicMock()
        fake_da.get_archive_window.return_value = _FakeArchiveResponse(
            x=[], y=[], errcode=-1)
        streamer = CanvasStreamer(da=fake_da)
        result = streamer._fetch_last_archive_value('ds', self.signal, end_ns=999)
        self.assertEqual(result, (None,) * 6)

    def test_returns_six_nones_when_data_access_raises(self):
        fake_da = MagicMock()
        fake_da.get_archive_window.side_effect = RuntimeError('boom')
        streamer = CanvasStreamer(da=fake_da)
        result = streamer._fetch_last_archive_value('ds', self.signal, end_ns=999)
        self.assertEqual(result, (None,) * 6)


class BackfillSignalTests(unittest.TestCase):
    """Tests for CanvasStreamer._backfill_signal (archive seeding + fallback)."""

    def setUp(self):
        # Non-empty x_data short-circuits _wait_for_first_live (no 2s sleep).
        self.signal = _FakeSignal(name='var', x_data=[100])
        self.callback = MagicMock()

    def test_window_with_data_does_not_call_fallback(self):
        fake_da = MagicMock()
        fake_da.get_archive_window.return_value = _FakeArchiveResponse(
            x=[10, 20, 30], y=[1, 2, 3], xunit='ns', yunit='V')
        streamer = CanvasStreamer(da=fake_da)
        streamer._max_points = 0
        streamer._backfill_signal('ds', self.signal, window_ns=100,
                                  callback=self.callback)
        self.assertEqual(fake_da.get_archive_window.call_count, 1)
        self.assertTrue(self.signal._streaming_has_live)
        self.callback.assert_called_once_with(self.signal)

    def test_empty_window_triggers_last_value_fallback(self):
        fake_da = MagicMock()
        fake_da.get_archive_window.side_effect = [
            _FakeArchiveResponse(x=[], y=[]),
            _FakeArchiveResponse(x=[5], y=[99]),
        ]
        streamer = CanvasStreamer(da=fake_da)
        streamer._max_points = 0
        streamer._backfill_signal('ds', self.signal, window_ns=100,
                                  callback=self.callback)
        self.assertEqual(fake_da.get_archive_window.call_count, 2)
        second_kwargs = fake_da.get_archive_window.call_args_list[1].kwargs
        self.assertEqual(second_kwargs.get('nbp'), 1)
        self.assertEqual(second_kwargs.get('decType'), 'last')
        self.assertTrue(self.signal._streaming_has_live)
        self.callback.assert_called_once_with(self.signal)

    def test_returns_silently_when_both_window_and_fallback_empty(self):
        fake_da = MagicMock()
        fake_da.get_archive_window.return_value = _FakeArchiveResponse(
            x=[], y=[], errcode=-1)
        streamer = CanvasStreamer(da=fake_da)
        streamer._max_points = 0
        streamer._backfill_signal('ds', self.signal, window_ns=100,
                                  callback=self.callback)
        self.assertFalse(self.signal._streaming_has_live)
        self.signal.inject_external.assert_not_called()
        self.callback.assert_not_called()


class HandlerEmptyPayloadTests(unittest.TestCase):
    """An empty poll must not inject data, but still requests a redraw so
    the visible window keeps sliding."""

    def test_empty_payload_skips_injection_but_requests_redraw(self):
        streamer = CanvasStreamer(da=MagicMock())
        signal = _FakeSignal(name='var')
        streamer.signals = {'var': [signal]}
        callback = MagicMock()
        dobj = MagicMock(xdata=[], ydata=[])
        streamer.handler(callback, 'var', dobj)
        signal.inject_external.assert_not_called()
        callback.assert_called_once_with(signal)

    def test_non_empty_payload_still_injects(self):
        streamer = CanvasStreamer(da=MagicMock())
        signal = _FakeSignal(name='var')
        streamer.signals = {'var': [signal]}
        callback = MagicMock()
        dobj = MagicMock(xdata=[1, 2], ydata=[3.0, 4.0], xunit='ns', yunit='V')
        streamer.handler(callback, 'var', dobj)
        signal.inject_external.assert_called_once()
        callback.assert_called_once_with(signal)


class _StatefulSignal(_FakeSignal):
    """Fake signal whose inject_external mutates data_store like
    AccessHelper.on_fetch_done (append or replace)."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        def _apply(append=False, **res):
            d0 = np.asarray(res['d0'])
            d1 = np.asarray(res['d1'])
            if append and len(self.data_store[0]) > 0:
                d0 = np.append(np.asarray(self.data_store[0]), d0)
                d1 = np.append(np.asarray(self.data_store[1]), d1)
            self.data_store = [_FakeBuf(d0), _FakeBuf(d1)]
            self.x_data = d0
            self.y_data = d1

        self.inject_external = _apply


class MonotonicTimeAxisTests(unittest.TestCase):
    """The buffer's time axis must never go backwards: archive fetches append
    a synthetic end-of-window point that can sit ahead of the next live batch
    (client/server clock skew)."""

    def test_backfill_drops_archive_points_at_or_after_first_live(self):
        fake_da = MagicMock()
        # 1000 is the synthetic boundary point at the first live timestamp.
        fake_da.get_archive_window.return_value = _FakeArchiveResponse(
            x=[900, 950, 1000], y=[1.0, 2.0, 3.0])
        streamer = CanvasStreamer(da=fake_da)
        streamer._max_points = 0
        signal = _StatefulSignal(name='var')
        signal.inject_external(append=False, d0=[1000, 1001], d1=[7.0, 8.0])
        streamer._backfill_signal('ds', signal, window_ns=100,
                                  callback=MagicMock())
        self.assertEqual(list(signal.x_data), [900, 950, 1000, 1001])

    def test_handler_drops_stale_synthetic_tail_before_append(self):
        streamer = CanvasStreamer(da=MagicMock())
        signal = _StatefulSignal(name='var')
        # 1000 emulates a synthetic point at client-now, ahead of server time.
        signal.inject_external(append=False, d0=[900, 950, 1000],
                               d1=[1.0, 2.0, 3.0])
        streamer.signals = {'var': [signal]}
        streamer._first_live_pending.add(signal.uid)
        dobj = MagicMock(xdata=[995, 996], ydata=[5.0, 6.0],
                         xunit='ns', yunit='V')
        streamer.handler(MagicMock(), 'var', dobj)
        x = list(signal.x_data)
        self.assertEqual(x, sorted(x))
        self.assertNotIn(1000, x)
        self.assertEqual(x[-1], 996)

    def test_handler_append_without_overlap_is_plain_append(self):
        streamer = CanvasStreamer(da=MagicMock())
        signal = _StatefulSignal(name='var')
        signal.inject_external(append=False, d0=[900, 950], d1=[1.0, 2.0])
        streamer.signals = {'var': [signal]}
        dobj = MagicMock(xdata=[995, 996], ydata=[5.0, 6.0],
                         xunit='ns', yunit='V')
        streamer.handler(MagicMock(), 'var', dobj)
        self.assertEqual(list(signal.x_data), [900, 950, 995, 996])


class BatchMergeTests(unittest.TestCase):
    """Polled chunks are buffered and merged into one injection per flush."""

    def test_merge_concatenates_chunks_and_keeps_last_units(self):
        chunks = [
            _FakeArchiveResponse(x=[1, 2], y=[10, 20], xunit='ns', yunit='V'),
            _FakeArchiveResponse(x=[3], y=[30], xunit='ns', yunit='mV'),
        ]
        merged = CanvasStreamer._merge_chunks(chunks)
        self.assertEqual(list(merged.xdata), [1, 2, 3])
        self.assertEqual(list(merged.ydata), [10, 20, 30])
        self.assertEqual(merged.yunit, 'mV')

    def test_merge_skips_empty_chunks(self):
        chunks = [
            _FakeArchiveResponse(x=[], y=[]),
            _FakeArchiveResponse(x=[5], y=[50], xunit='ns', yunit='V'),
            _FakeArchiveResponse(x=[], y=[]),
        ]
        merged = CanvasStreamer._merge_chunks(chunks)
        self.assertEqual(list(merged.xdata), [5])
        self.assertEqual(list(merged.ydata), [50])

    def test_merge_of_all_empty_chunks_returns_empty_payload(self):
        chunks = [_FakeArchiveResponse(x=[], y=[]),
                  _FakeArchiveResponse(x=[], y=[])]
        merged = CanvasStreamer._merge_chunks(chunks)
        self.assertEqual(len(merged.xdata), 0)

    def test_flush_batches_calls_back_once_per_varname_and_clears(self):
        pending = {
            'a': [_FakeArchiveResponse(x=[1], y=[10], xunit='ns', yunit='V'),
                  _FakeArchiveResponse(x=[2], y=[20], xunit='ns', yunit='V')],
            'b': [],
        }
        callback = MagicMock()
        CanvasStreamer._flush_batches(pending, callback)
        callback.assert_called_once()
        varname, merged = callback.call_args.args
        self.assertEqual(varname, 'a')
        self.assertEqual(list(merged.xdata), [1, 2])
        self.assertEqual(pending, {'a': [], 'b': []})


class SpawnLifecycleTests(unittest.TestCase):
    """Streaming workers run on QThreads (worker/moveToThread pattern)
    and stop() joins finished threads without leaking them."""

    def test_spawn_runs_target_on_qthread_and_finishes(self):
        streamer = CanvasStreamer(da=MagicMock())
        ran = Event()
        thread = streamer._spawn("test-job", ran.set)
        self.assertTrue(ran.wait(5))
        self.assertTrue(thread.wait(5000))

    def test_worker_exception_is_contained_and_thread_finishes(self):
        streamer = CanvasStreamer(da=MagicMock())

        def boom():
            raise RuntimeError("boom")

        thread = streamer._spawn("boom-job", boom)
        self.assertTrue(thread.wait(5000))

    def test_stop_clears_thread_registry(self):
        streamer = CanvasStreamer(da=MagicMock())
        thread = streamer._spawn("quick-job", lambda: None)
        self.assertTrue(thread.wait(5000))
        streamer.stop()
        self.assertEqual(streamer._qt_threads, [])
        self.assertTrue(streamer.stop_flag)


if __name__ == '__main__':
    unittest.main()
