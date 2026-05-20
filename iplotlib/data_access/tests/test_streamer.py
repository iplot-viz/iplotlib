"""Streamer regression tests covering branch 78 behaviour.

Locks in the wiring for the per-signal sample cap, the archive-window
kwargs (envelope vs raw, nbp gating), the last-value fallback used when
the visible window has no samples, and the _streaming_has_live flag set
during backfill. Tests use lightweight fakes (no Qt, no UDA, no
threading) so they run on both Linux and Windows CI.
"""

import unittest
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
            _FakeArchiveResponse(x=[], y=[]),              # window: empty
            _FakeArchiveResponse(x=[5], y=[99]),           # fallback: one point
        ]
        streamer = CanvasStreamer(da=fake_da)
        streamer._max_points = 0
        streamer._backfill_signal('ds', self.signal, window_ns=100,
                                  callback=self.callback)
        self.assertEqual(fake_da.get_archive_window.call_count, 2)
        # Second call must carry the last-value kwargs.
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


if __name__ == '__main__':
    unittest.main()
