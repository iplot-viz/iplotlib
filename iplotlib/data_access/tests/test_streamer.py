"""Tests for the per-signal sample cap, archive-window kwargs
(envelope vs raw, nbp gating), the empty-window last-value fallback,
and the _streaming_has_live flag set during backfill."""

import time
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

    def __init__(self, name='sig', envelope=False, extremities=False, data=None, x_data=None):
        self.name = name
        self.uid = id(self)
        self.envelope = envelope
        self.extremities = extremities
        if data is None:
            self.data_store = [_FakeBuf([]), _FakeBuf([])]
        else:
            self.data_store = data
        self.inject_external = MagicMock()
        self._streaming_has_live = False
        self.isDownsampled = False
        # Mirrors the live buffer the handler reads back; the backfill no longer
        # consults it (the archive end is anchored at now - live_retention).
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

    def test_drops_oldest_when_raw_tail_fills_the_cap(self):
        # Timestamps within live_retention of the newest one are all raw.
        self.streamer._max_points = 2
        signal = _FakeSignal(
            data=[_FakeBuf([1, 2, 3, 4]), _FakeBuf([10, 20, 30, 40])])
        self.streamer._apply_cap(signal)
        signal.inject_external.assert_called_once()
        kwargs = signal.inject_external.call_args.kwargs
        self.assertFalse(kwargs['append'])
        self.assertEqual(list(kwargs['d0']), [3, 4])
        self.assertEqual(list(kwargs['d1']), [30, 40])

    def test_drops_oldest_without_decimating(self):
        # mint#78 point 5: over the cap we DROP points (no local
        # decimation); the refresh worker restores the older span from
        # the archive at the point budget.
        self.streamer._max_points = 1000
        sec = int(1e9)
        x = np.arange(2000) * sec
        y = np.arange(2000, dtype=float)
        signal = _FakeSignal(data=[_FakeBuf(x), _FakeBuf(y)])
        self.streamer._apply_cap(signal)
        kwargs = signal.inject_external.call_args.kwargs
        out_x = np.asarray(kwargs['d0'])
        out_y = np.asarray(kwargs['d1'])
        self.assertEqual(len(out_x), 1000)
        # The newest 1000 samples survive verbatim: no resampling.
        self.assertEqual(list(out_x), list(x[-1000:]))
        self.assertEqual(list(out_y), list(y[-1000:]))

    def test_reports_whether_the_buffer_was_reduced(self):
        self.streamer._max_points = 3
        signal = _FakeSignal(data=[_FakeBuf([1, 2, 3]), _FakeBuf([10, 20, 30])])
        self.assertFalse(self.streamer._apply_cap(signal))
        self.streamer._max_points = 2
        self.assertTrue(self.streamer._apply_cap(signal))

    def test_caps_envelope_buffers_by_dropping_oldest(self):
        self.streamer._max_points = 500
        sec = int(1e9)
        x = np.arange(1000) * sec
        y_min = np.arange(1000, dtype=float)
        y_max = np.arange(1000, dtype=float) + 1
        y_avg = np.arange(1000, dtype=float) + 0.5
        signal = _FakeSignal(
            envelope=True,
            data=[_FakeBuf(x), _FakeBuf(y_min), _FakeBuf(y_max),
                  _FakeBuf(y_avg)])
        self.streamer._apply_cap(signal)
        kwargs = signal.inject_external.call_args.kwargs
        self.assertEqual(len(kwargs['d0']), 500)
        # Newest 500 kept verbatim across all four buffers.
        self.assertEqual(list(np.asarray(kwargs['d0'])), list(x[-500:]))
        self.assertEqual(list(np.asarray(kwargs['d1'])), list(y_min[-500:]))
        self.assertEqual(list(np.asarray(kwargs['d2'])), list(y_max[-500:]))
        self.assertEqual(list(np.asarray(kwargs['d3'])), list(y_avg[-500:]))


class ArchiveKwargsTests(unittest.TestCase):
    """Tests for CanvasStreamer._archive_kwargs."""

    def setUp(self):
        self.streamer = CanvasStreamer(da=None)

    def test_raw_signal_extremities_follows_the_table_column(self):
        self.streamer._max_points = 0
        kwargs = self.streamer._archive_kwargs(signal=_FakeSignal(envelope=False))
        self.assertEqual(kwargs, {'extremities': False})
        kwargs = self.streamer._archive_kwargs(
            signal=_FakeSignal(envelope=False, extremities=True))
        self.assertEqual(kwargs, {'extremities': True})

    def test_raw_signal_with_cap_adds_nbp_and_envelope_budget(self):
        # env_nbp keeps the point budget when the server overflows the raw
        # request into an envelope, instead of the coarse default.
        self.streamer._max_points = 100
        kwargs = self.streamer._archive_kwargs(signal=_FakeSignal(envelope=False))
        self.assertEqual(kwargs, {'nbp': 100, 'env_nbp': 100, 'extremities': False})

    def test_envelope_signal_omits_extremities(self):
        # Envelope buckets already cover boundaries; extremities=True crashes UDA.
        self.streamer._max_points = 50
        kwargs = self.streamer._archive_kwargs(
            signal=_FakeSignal(envelope=True, extremities=True))
        self.assertEqual(kwargs, {'nbp': 50, 'env_nbp': 50})
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
    """Tests for the archive seeding of a single signal (plus fallback)."""

    SEC = int(1e9)
    WINDOW = 3600 * int(1e9)

    def setUp(self):
        self.signal = _FakeSignal(name='var', x_data=[self.WINDOW])
        self.callback = MagicMock()

    def _mk_streamer(self, fake_da):
        streamer = CanvasStreamer(da=fake_da)
        streamer._max_points = 0
        return streamer

    def _full_reply(self, **kwargs):
        return _FakeArchiveResponse(
            x=[10 * self.SEC, 2000 * self.SEC, 3580 * self.SEC, 3590 * self.SEC],
            y=[1, 2, 3, 4], xunit='ns', yunit='V', **kwargs)

    def test_window_with_data_does_not_call_fallback(self):
        fake_da = MagicMock()
        fake_da.get_archive_window.return_value = self._full_reply()
        streamer = self._mk_streamer(fake_da)
        streamer._archive_backfill({'ds': [self.signal]}, self.WINDOW,
                                   self.callback)
        self.assertEqual(fake_da.get_archive_window.call_count, 1)
        self.assertTrue(self.signal._streaming_has_live)
        self.callback.assert_called_once_with(self.signal)

    def test_empty_window_triggers_last_value_fallback(self):
        fake_da = MagicMock()
        fake_da.get_archive_window.side_effect = [
            _FakeArchiveResponse(x=[], y=[]),     # empty window request
            _FakeArchiveResponse(x=[5], y=[99]),  # last-value fallback
        ]
        streamer = self._mk_streamer(fake_da)
        streamer._archive_backfill({'ds': [self.signal]}, self.WINDOW,
                                   self.callback)
        self.assertEqual(fake_da.get_archive_window.call_count, 2)
        last_kwargs = fake_da.get_archive_window.call_args_list[1].kwargs
        self.assertEqual(last_kwargs.get('nbp'), 1)
        self.assertEqual(last_kwargs.get('decType'), 'last')
        self.assertTrue(self.signal._streaming_has_live)
        self.callback.assert_called_once_with(self.signal)

    def test_envelope_reply_to_raw_request_flags_downsampled(self):
        # get_archive_window only returns an envelope when UDA overflowed.
        fake_da = MagicMock()
        fake_da.get_archive_window.return_value = self._full_reply(
            ymin=[0, 1, 2, 3], ymax=[2, 3, 4, 5])
        streamer = self._mk_streamer(fake_da)
        streamer._archive_backfill({'ds': [self.signal]}, self.WINDOW,
                                   self.callback)
        self.assertTrue(self.signal.isDownsampled)

    def test_raw_reply_does_not_flag_downsampled(self):
        fake_da = MagicMock()
        fake_da.get_archive_window.return_value = self._full_reply()
        streamer = self._mk_streamer(fake_da)
        streamer._archive_backfill({'ds': [self.signal]}, self.WINDOW,
                                   self.callback)
        self.assertFalse(self.signal.isDownsampled)

    def test_envelope_signal_reply_does_not_flag_downsampled(self):
        # Buckets are an envelope signal's normal representation, as in Draw.
        signal = _FakeSignal(name='var', envelope=True, x_data=[self.WINDOW])
        fake_da = MagicMock()
        fake_da.get_envelope.return_value = self._full_reply(
            ymin=[0, 1, 2, 3], ymax=[2, 3, 4, 5])
        streamer = self._mk_streamer(fake_da)
        streamer._archive_backfill({'ds': [signal]}, self.WINDOW,
                                   self.callback)
        self.assertFalse(signal.isDownsampled)

    def test_returns_silently_when_both_window_and_fallback_empty(self):
        fake_da = MagicMock()
        fake_da.get_archive_window.return_value = _FakeArchiveResponse(
            x=[], y=[], errcode=-1)
        streamer = self._mk_streamer(fake_da)
        streamer._archive_backfill({'ds': [self.signal]}, self.WINDOW,
                                   self.callback)
        self.assertFalse(self.signal._streaming_has_live)
        self.signal.inject_external.assert_not_called()
        self.callback.assert_not_called()


class EnvelopeSelectionBackfillTests(unittest.TestCase):
    """Envelope is opt-in per signal (Envelope column), independent of window
    size: a plain signal is read raw, an envelope signal as a single
    server-side envelope; one request per signal. The archive is read up to
    live_retention behind now, and the feed covers the newest span."""

    SEC = int(1e9)
    HOUR = 3600 * int(1e9)
    RETENTION = 120 * int(1e9)

    def _full(self, **kwargs):
        return _FakeArchiveResponse(
            x=[10 * self.SEC, 2000 * self.SEC], y=[1, 2],
            xunit='ns', yunit='V', **kwargs)

    def _streamer(self, fake_da):
        streamer = CanvasStreamer(da=fake_da)
        streamer._max_points = 0
        return streamer

    def test_plain_signal_reads_raw_regardless_of_window(self):
        fake_da = MagicMock()
        fake_da.get_archive_window.return_value = self._full()
        signal = _FakeSignal(name='var', envelope=False)
        streamer = self._streamer(fake_da)
        # A very wide window still reads raw when the signal is not envelope.
        streamer._archive_backfill({'ds': [signal]}, 10 * self.HOUR, MagicMock())
        self.assertEqual(fake_da.get_archive_window.call_count, 1)
        fake_da.get_envelope.assert_not_called()

    def test_envelope_signal_reads_a_single_envelope(self):
        fake_da = MagicMock()
        fake_da.get_envelope.return_value = self._full(ymin=[0, 1], ymax=[2, 3])
        signal = _FakeSignal(name='var', envelope=True)
        streamer = self._streamer(fake_da)
        streamer._archive_backfill({'ds': [signal]}, self.HOUR, MagicMock())
        self.assertEqual(fake_da.get_envelope.call_count, 1)
        fake_da.get_archive_window.assert_not_called()
        self.assertEqual(fake_da.get_envelope.call_args.kwargs['nbp'], 1920)

    def test_envelope_request_uses_the_point_budget_when_set(self):
        # The per-signal cap sizes every archive query; the coarse default is
        # only a fallback for capless runs.
        fake_da = MagicMock()
        fake_da.get_envelope.return_value = self._full(ymin=[0, 1], ymax=[2, 3])
        signal = _FakeSignal(name='var', envelope=True)
        streamer = self._streamer(fake_da)
        streamer._max_points = 10_000
        streamer._archive_backfill({'ds': [signal]}, self.HOUR, MagicMock())
        self.assertEqual(fake_da.get_envelope.call_args.kwargs['nbp'], 10_000)

    def test_one_request_per_signal(self):
        fake_da = MagicMock()
        fake_da.get_archive_window.return_value = self._full()
        sigs = [_FakeSignal(name='a'), _FakeSignal(name='b')]
        streamer = self._streamer(fake_da)
        streamer._archive_backfill({'ds': sigs}, self.HOUR, MagicMock())
        self.assertEqual(fake_da.get_archive_window.call_count, 2)
        self.assertEqual([c.kwargs['varname']
                          for c in fake_da.get_archive_window.call_args_list],
                         ['a', 'b'])

    def test_archive_ends_a_retention_behind_now(self):
        fake_da = MagicMock()
        fake_da.get_archive_window.return_value = self._full()
        signal = _FakeSignal(name='var')
        streamer = self._streamer(fake_da)
        before = int(time.time() * 1e9)
        streamer._archive_backfill({'ds': [signal]}, self.HOUR, MagicMock())
        after = int(time.time() * 1e9)
        kw = fake_da.get_archive_window.call_args.kwargs
        tsS, tsE = int(kw['tsS']), int(kw['tsE'])
        # End sits ~live_retention behind now; the archive spans exactly the
        # window minus that retention (the feed fills the rest).
        self.assertLessEqual(before - tsE, self.RETENTION)
        self.assertGreaterEqual(after - tsE, self.RETENTION)
        self.assertEqual(tsE - tsS, self.HOUR - self.RETENTION)


class WindowRefreshTests(unittest.TestCase):
    """Tests for the full-window archive refresh (mint#78 point 5):
    one archive call for [now - window, now - live_retention] at the
    point budget, keeping the newest live_retention span from live."""

    SEC = int(1e9)
    WINDOW = 3600 * int(1e9)

    def _mk(self, reply, data):
        fake_da = MagicMock()
        fake_da.get_archive_window.return_value = reply
        streamer = CanvasStreamer(da=fake_da)
        streamer._max_points = 10000
        streamer._window_ns = self.WINDOW
        streamer._callback = MagicMock()
        signal = _FakeSignal(name='var', data=data)
        return streamer, fake_da, signal

    def test_one_call_ending_a_retention_behind_now(self):
        reply = _FakeArchiveResponse(x=[1 * self.SEC], y=[1.0])
        streamer, fake_da, signal = self._mk(
            reply, data=[_FakeBuf([]), _FakeBuf([])])
        before = time.time()
        streamer._refresh_signal('ds', signal)
        after = time.time()
        self.assertEqual(fake_da.get_archive_window.call_count, 1)
        kwargs = fake_da.get_archive_window.call_args.kwargs
        end_ns = int(kwargs['tsE'])
        self.assertLessEqual(end_ns, int(after * 1e9) - 110 * self.SEC)
        self.assertGreaterEqual(end_ns, int(before * 1e9) - 130 * self.SEC)
        self.assertEqual(int(kwargs['tsE']) - int(kwargs['tsS']),
                         self.WINDOW - 120 * self.SEC)
        self.assertEqual(kwargs['nbp'], 10000)

    def test_keeps_live_tail_and_replaces_older_span(self):
        now_ns = int(time.time() * 1e9)
        boundary_ns = now_ns - 120 * self.SEC
        # Buffer: one stale live sample well before the boundary (should be
        # replaced by archive) and two fresh ones after it (kept).
        stale = boundary_ns - 600 * self.SEC
        fresh1 = boundary_ns + 10 * self.SEC
        fresh2 = boundary_ns + 20 * self.SEC
        arch1 = boundary_ns - 1000 * self.SEC
        arch2 = boundary_ns - 500 * self.SEC
        reply = _FakeArchiveResponse(x=[arch1, arch2], y=[1.0, 2.0])
        streamer, fake_da, signal = self._mk(
            reply,
            data=[_FakeBuf([stale, fresh1, fresh2]),
                  _FakeBuf([-1.0, 3.0, 4.0])])
        streamer._refresh_signal('ds', signal)
        kwargs = signal.inject_external.call_args.kwargs
        self.assertFalse(kwargs['append'])
        self.assertEqual(list(kwargs['d0']), [arch1, arch2, fresh1, fresh2])
        self.assertEqual(list(kwargs['d1']), [1.0, 2.0, 3.0, 4.0])
        self.assertTrue(signal._streaming_has_live)
        streamer._callback.assert_called_once_with(signal)

    def test_empty_archive_reply_leaves_buffer_untouched(self):
        reply = _FakeArchiveResponse(x=[], y=[])
        streamer, fake_da, signal = self._mk(
            reply, data=[_FakeBuf([1, 2]), _FakeBuf([10, 20])])
        streamer._refresh_signal('ds', signal)
        signal.inject_external.assert_not_called()
        streamer._callback.assert_not_called()

    def test_cap_overflow_marks_signal_for_refresh(self):
        streamer = CanvasStreamer(da=None)
        streamer._max_points = 2
        signal = _FakeSignal(
            data=[_FakeBuf([1, 2, 3, 4]), _FakeBuf([10, 20, 30, 40])])
        streamer._mark_refresh(signal)
        self.assertIn(signal.uid, streamer._refresh_pending)
        streamer.stop()
        self.assertFalse(streamer._refresh_pending)


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
    """The buffer's time axis must never go backwards, and the first live batch
    breaks the line so the archive block and the feed are not joined."""

    def test_backfill_merges_archive_ahead_of_existing_buffer(self):
        fake_da = MagicMock()
        fake_da.get_archive_window.return_value = _FakeArchiveResponse(
            x=[900, 950, 1000], y=[1.0, 2.0, 3.0])
        streamer = CanvasStreamer(da=fake_da)
        streamer._max_points = 0
        signal = _StatefulSignal(name='var')
        # A live sample already sits in the buffer; the archive is prepended and
        # the buffer wins a timestamp collision (1000).
        signal.inject_external(append=False, d0=[1000, 1001], d1=[7.0, 8.0])
        streamer._archive_backfill({'ds': [signal]}, 100, MagicMock())
        self.assertEqual(list(signal.x_data), [900, 950, 1000, 1001])
        self.assertEqual(list(signal.y_data), [1.0, 2.0, 7.0, 8.0])

    def test_first_live_batch_inserts_a_break_after_the_archive(self):
        streamer = CanvasStreamer(da=MagicMock())
        signal = _StatefulSignal(name='var')
        # Archive block; the first live batch arrives well ahead of it.
        signal.inject_external(append=False, d0=[900, 950], d1=[1.0, 2.0])
        streamer.signals = {'var': [signal]}
        streamer._first_live_pending.add(signal.uid)
        dobj = MagicMock(xdata=[1000, 1001], ydata=[5.0, 6.0],
                         xunit='ns', yunit='V')
        streamer.handler(MagicMock(), 'var', dobj)
        x = list(signal.x_data)
        y = list(signal.y_data)
        # A NaN just before the first live sample breaks the line so the two
        # blocks are not joined by a diagonal.
        self.assertEqual(x, [900, 950, 999, 1000, 1001])
        self.assertTrue(np.isnan(y[2]))
        self.assertEqual([y[0], y[1], y[3], y[4]], [1.0, 2.0, 5.0, 6.0])
        self.assertNotIn(signal.uid, streamer._first_live_pending)

    def test_handler_folds_overlapped_live_samples_into_the_batch(self):
        streamer = CanvasStreamer(da=MagicMock())
        signal = _StatefulSignal(name='var')
        signal.inject_external(append=False, d0=[900, 950, 970],
                               d1=[1.0, 2.0, 3.0])
        streamer.signals = {'var': [signal]}
        dobj = MagicMock(xdata=[960, 980], ydata=[5.0, 6.0],
                         xunit='ns', yunit='V')
        streamer.handler(MagicMock(), 'var', dobj)
        self.assertEqual(list(signal.x_data), [900, 950, 960, 970, 980])
        self.assertEqual(list(signal.y_data), [1.0, 2.0, 5.0, 3.0, 6.0])

    def test_handler_fold_prefers_the_batch_on_a_re_emitted_timestamp(self):
        streamer = CanvasStreamer(da=MagicMock())
        signal = _StatefulSignal(name='var')
        signal.inject_external(append=False, d0=[900, 950], d1=[1.0, 2.0])
        streamer.signals = {'var': [signal]}
        dobj = MagicMock(xdata=[950, 960], ydata=[9.0, 6.0],
                         xunit='ns', yunit='V')
        streamer.handler(MagicMock(), 'var', dobj)
        self.assertEqual(list(signal.x_data), [900, 950, 960])
        self.assertEqual(list(signal.y_data), [1.0, 9.0, 6.0])

    def test_handler_append_without_overlap_is_plain_append(self):
        streamer = CanvasStreamer(da=MagicMock())
        signal = _StatefulSignal(name='var')
        signal.inject_external(append=False, d0=[900, 950], d1=[1.0, 2.0])
        streamer.signals = {'var': [signal]}
        dobj = MagicMock(xdata=[995, 996], ydata=[5.0, 6.0],
                         xunit='ns', yunit='V')
        streamer.handler(MagicMock(), 'var', dobj)
        self.assertEqual(list(signal.x_data), [900, 950, 995, 996])


class ExpressionCarrierTests(unittest.TestCase):
    """Expression signals stream through their single child: raw data goes to
    the child's buffers and the parent re-evaluates after each injection."""

    def test_carrier_of_plain_signal_is_itself(self):
        signal = _FakeSignal(name='var')
        self.assertIs(CanvasStreamer._carrier(signal), signal)

    def test_carrier_of_expression_signal_is_its_child(self):
        child = _FakeSignal(name='VAR')
        parent = _FakeSignal(name='${VAR}*10')
        parent.children = [child]
        self.assertIs(CanvasStreamer._carrier(parent), child)

    def test_handler_injects_into_child_and_reprocesses_parent(self):
        streamer = CanvasStreamer(da=MagicMock())
        child = _StatefulSignal(name='VAR')
        parent = _FakeSignal(name='${VAR}*10')
        parent.children = [child]
        parent._do_data_processing = MagicMock()
        streamer.signals = {'VAR': [parent]}
        callback = MagicMock()
        dobj = MagicMock(xdata=[1, 2], ydata=[3.0, 4.0], xunit='ns', yunit='V')
        streamer.handler(callback, 'VAR', dobj)
        self.assertEqual(list(child.x_data), [1, 2])
        parent._do_data_processing.assert_called_once()
        callback.assert_called_once_with(parent)

    def test_parent_processing_error_does_not_break_the_stream(self):
        streamer = CanvasStreamer(da=MagicMock())
        child = _StatefulSignal(name='VAR')
        parent = _FakeSignal(name='${VAR}*10')
        parent.children = [child]
        parent._do_data_processing = MagicMock(side_effect=RuntimeError('boom'))
        streamer.signals = {'VAR': [parent]}
        callback = MagicMock()
        dobj = MagicMock(xdata=[1], ydata=[3.0], xunit='ns', yunit='V')
        streamer.handler(callback, 'VAR', dobj)
        callback.assert_called_once_with(parent)


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

    def test_merge_sorts_interleaved_samples_across_chunks(self):
        chunks = [
            _FakeArchiveResponse(x=[1, 2, 5], y=[10, 20, 50], xunit='ns', yunit='V'),
            _FakeArchiveResponse(x=[4, 6], y=[40, 60], xunit='ns', yunit='V'),
        ]
        merged = CanvasStreamer._merge_chunks(chunks)
        self.assertEqual(list(merged.xdata), [1, 2, 4, 5, 6])
        self.assertEqual(list(merged.ydata), [10, 20, 40, 50, 60])

    def test_merge_sorts_within_a_single_chunk_keeping_newest_duplicate(self):
        chunks = [_FakeArchiveResponse(x=[1, 3, 2, 3, 4], y=[10, 30, 20, 31, 40],
                                       xunit='ns', yunit='V')]
        merged = CanvasStreamer._merge_chunks(chunks)
        self.assertEqual(list(merged.xdata), [1, 2, 3, 4])
        self.assertEqual(list(merged.ydata), [10, 20, 31, 40])

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
