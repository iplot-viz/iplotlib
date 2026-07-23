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
        self.isDownsampled = False
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

    def test_drops_oldest_when_raw_tail_fills_the_cap(self):
        # Timestamps closer than _RAW_TAIL_S to the newest one are all raw.
        self.streamer._max_points = 2
        signal = _FakeSignal(
            data=[_FakeBuf([1, 2, 3, 4]), _FakeBuf([10, 20, 30, 40])])
        self.streamer._apply_cap(signal)
        signal.inject_external.assert_called_once()
        kwargs = signal.inject_external.call_args.kwargs
        self.assertFalse(kwargs['append'])
        self.assertEqual(list(kwargs['d0']), [3, 4])
        self.assertEqual(list(kwargs['d1']), [30, 40])

    def test_decimates_old_samples_and_keeps_raw_tail(self):
        self.streamer._max_points = 1000
        sec = int(1e9)
        x = np.arange(2000) * sec  # 1 Hz over ~33 min; tail = last 2 min
        y = np.zeros(2000)
        y[500] = -50.0
        y[600] = 50.0
        signal = _FakeSignal(data=[_FakeBuf(x), _FakeBuf(y)])
        self.streamer._apply_cap(signal)
        kwargs = signal.inject_external.call_args.kwargs
        out_x = np.asarray(kwargs['d0'])
        out_y = np.asarray(kwargs['d1'])
        self.assertLessEqual(len(out_x), 1000)
        self.assertTrue(np.all(np.diff(out_x) >= 0))
        # Extremes survive decimation; the raw tail is untouched.
        self.assertIn(-50.0, out_y)
        self.assertIn(50.0, out_y)
        tail = x[x >= x[-1] - 120 * sec]
        self.assertEqual(list(out_x[-len(tail):]), list(tail))

    def test_reports_whether_the_buffer_was_reduced(self):
        self.streamer._max_points = 3
        signal = _FakeSignal(data=[_FakeBuf([1, 2, 3]), _FakeBuf([10, 20, 30])])
        self.assertFalse(self.streamer._apply_cap(signal))
        self.streamer._max_points = 2
        self.assertTrue(self.streamer._apply_cap(signal))

    def test_decimates_envelope_buffers_preserving_band(self):
        self.streamer._max_points = 500
        sec = int(1e9)
        x = np.arange(1000) * sec
        y_min = np.zeros(1000)
        y_max = np.ones(1000)
        y_avg = np.full(1000, 0.5)
        y_min[100] = -9.0
        y_max[200] = 9.0
        signal = _FakeSignal(
            envelope=True,
            data=[_FakeBuf(x), _FakeBuf(y_min), _FakeBuf(y_max),
                  _FakeBuf(y_avg)])
        self.streamer._apply_cap(signal)
        kwargs = signal.inject_external.call_args.kwargs
        self.assertLessEqual(len(kwargs['d0']), 500)
        self.assertEqual(np.min(np.asarray(kwargs['d1'])), -9.0)
        self.assertEqual(np.max(np.asarray(kwargs['d2'])), 9.0)


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


class FetchArchiveWindowCompleteTests(unittest.TestCase):
    """The UDA server can return a window truncated in time; the fetch must
    resume from the last received sample until the window is covered."""

    SEC = int(1e9)

    def _streamer(self, replies):
        fake_da = MagicMock()
        fake_da.get_archive_window.side_effect = replies
        streamer = CanvasStreamer(da=fake_da)
        streamer._max_points = 0
        return streamer, fake_da

    def test_truncated_reply_is_resumed_until_covered(self):
        end = 1000 * self.SEC
        streamer, fake_da = self._streamer([
            _FakeArchiveResponse(x=[0, 500 * self.SEC], y=[1.0, 2.0]),
            _FakeArchiveResponse(x=[600 * self.SEC, end], y=[3.0, 4.0]),
        ])
        x, y, *_ = streamer._fetch_archive_window_complete(
            'ds', _FakeSignal(name='var'), 0, end)
        self.assertEqual(fake_da.get_archive_window.call_count, 2)
        second = fake_da.get_archive_window.call_args_list[1].kwargs
        self.assertEqual(second['tsS'], str(500 * self.SEC + 1))
        self.assertEqual(list(x), [0, 500 * self.SEC, 600 * self.SEC, end])
        self.assertEqual(list(y), [1.0, 2.0, 3.0, 4.0])

    def test_full_reply_is_fetched_once(self):
        end = 1000 * self.SEC
        streamer, fake_da = self._streamer([
            _FakeArchiveResponse(x=[0, end], y=[1.0, 2.0]),
        ])
        x, *_ = streamer._fetch_archive_window_complete(
            'ds', _FakeSignal(name='var'), 0, end)
        self.assertEqual(fake_da.get_archive_window.call_count, 1)
        self.assertEqual(list(x), [0, end])

    def test_reply_short_of_the_end_by_a_margin_is_not_resumed(self):
        # Envelope buckets legitimately stop just short of the window end.
        end = 1000 * self.SEC
        streamer, fake_da = self._streamer([
            _FakeArchiveResponse(x=[0, 995 * self.SEC], y=[1.0, 2.0]),
        ])
        streamer._fetch_archive_window_complete(
            'ds', _FakeSignal(name='var'), 0, end)
        self.assertEqual(fake_da.get_archive_window.call_count, 1)

    def test_truncated_reply_with_synthetic_end_point_is_resumed(self):
        # The dense part stops at 500s but extremities appends a point at the
        # requested end; coverage must be judged by the sample before the jump.
        end = 1000 * self.SEC
        streamer, fake_da = self._streamer([
            _FakeArchiveResponse(x=[0, 500 * self.SEC, end], y=[1.0, 2.0, 9.0]),
            _FakeArchiveResponse(x=[600 * self.SEC, end], y=[3.0, 4.0]),
        ])
        x, y, *_ = streamer._fetch_archive_window_complete(
            'ds', _FakeSignal(name='var'), 0, end)
        self.assertEqual(fake_da.get_archive_window.call_count, 2)
        second = fake_da.get_archive_window.call_args_list[1].kwargs
        self.assertEqual(second['tsS'], str(500 * self.SEC + 1))
        self.assertEqual(list(x), [0, 500 * self.SEC, 600 * self.SEC, end])
        self.assertEqual(list(y), [1.0, 2.0, 3.0, 4.0])

    def test_flat_signal_two_boundary_points_are_not_resumed(self):
        end = 1000 * self.SEC
        streamer, fake_da = self._streamer([
            _FakeArchiveResponse(x=[0, end], y=[5.0, 5.0]),
        ])
        x, *_ = streamer._fetch_archive_window_complete(
            'ds', _FakeSignal(name='var'), 0, end)
        self.assertEqual(fake_da.get_archive_window.call_count, 1)
        self.assertEqual(list(x), [0, end])

    def test_refused_remainder_marches_on_in_slices(self):
        # After a truncated first reply the fetch continues in hour slices,
        # skipping a slice the server returns empty.
        end = 10800 * self.SEC
        streamer, fake_da = self._streamer([
            _FakeArchiveResponse(x=[0, 600 * self.SEC], y=[1.0, 1.0]),
            _FakeArchiveResponse(x=[], y=[]),
            _FakeArchiveResponse(x=[5000 * self.SEC, 7000 * self.SEC], y=[2.0, 2.0]),
            _FakeArchiveResponse(x=[8000 * self.SEC, 10750 * self.SEC], y=[3.0, 3.0]),
        ])
        x, *_ = streamer._fetch_archive_window_complete(
            'ds', _FakeSignal(name='var'), 0, end)
        self.assertEqual(fake_da.get_archive_window.call_count, 4)
        self.assertEqual(
            list(x),
            [0, 600 * self.SEC, 5000 * self.SEC, 7000 * self.SEC,
             8000 * self.SEC, 10750 * self.SEC])
        second = fake_da.get_archive_window.call_args_list[1].kwargs
        self.assertEqual(second['tsS'], str(600 * self.SEC + 1))
        self.assertEqual(second['tsE'], str(600 * self.SEC + 1 + 3600 * self.SEC))

    def test_non_advancing_reply_stops_the_loop(self):
        end = 1000 * self.SEC
        streamer, fake_da = self._streamer([
            _FakeArchiveResponse(x=[0, 500 * self.SEC], y=[1.0, 2.0]),
            _FakeArchiveResponse(x=[100 * self.SEC, 400 * self.SEC], y=[9.0, 9.0]),
        ])
        x, *_ = streamer._fetch_archive_window_complete(
            'ds', _FakeSignal(name='var'), 0, end)
        self.assertEqual(fake_da.get_archive_window.call_count, 2)
        self.assertEqual(list(x), [0, 500 * self.SEC])


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

    def test_envelope_reply_to_raw_request_flags_downsampled(self):
        # get_archive_window only returns an envelope when UDA overflowed.
        fake_da = MagicMock()
        fake_da.get_archive_window.return_value = _FakeArchiveResponse(
            x=[10, 20, 30], y=[1, 2, 3], xunit='ns', yunit='V',
            ymin=[0, 1, 2], ymax=[2, 3, 4])
        streamer = CanvasStreamer(da=fake_da)
        streamer._max_points = 0
        streamer._backfill_signal('ds', self.signal, window_ns=100,
                                  callback=self.callback)
        self.assertTrue(self.signal.isDownsampled)

    def test_raw_reply_does_not_flag_downsampled(self):
        fake_da = MagicMock()
        fake_da.get_archive_window.return_value = _FakeArchiveResponse(
            x=[10, 20, 30], y=[1, 2, 3], xunit='ns', yunit='V')
        streamer = CanvasStreamer(da=fake_da)
        streamer._max_points = 0
        streamer._backfill_signal('ds', self.signal, window_ns=100,
                                  callback=self.callback)
        self.assertFalse(self.signal.isDownsampled)

    def test_envelope_signal_reply_does_not_flag_downsampled(self):
        # Buckets are an envelope signal's normal representation, as in Draw.
        signal = _FakeSignal(name='var', envelope=True, x_data=[100])
        fake_da = MagicMock()
        fake_da.get_envelope.return_value = _FakeArchiveResponse(
            x=[10, 20, 30], y=[1, 2, 3], xunit='ns', yunit='V',
            ymin=[0, 1, 2], ymax=[2, 3, 4])
        streamer = CanvasStreamer(da=fake_da)
        streamer._max_points = 0
        streamer._backfill_signal('ds', signal, window_ns=100,
                                  callback=self.callback)
        self.assertFalse(signal.isDownsampled)

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
