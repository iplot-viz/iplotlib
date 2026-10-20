"""Tests for the requests a signal makes and for serving them from data read ahead
(AccessHelper.data_requests, AccessHelper.prefetched)."""

import threading
import unittest
from types import SimpleNamespace

import numpy as np

from iplotlib.core.signal import SignalXY
from iplotlib.interface.iplotSignalAdapter import AccessHelper, DataAccessError, ParserHelper, Result

T0 = 1_700_000_000_000_000_000
T1 = T0 + 60_000_000_000


class _DataAccessStub:
    """Answers every request with three samples and records the variables it is asked for."""

    def __init__(self):
        self.reads = []

    def get_data(self, data_s_name, **kwargs):
        self.reads.append(kwargs['varname'])
        return SimpleNamespace(errcode=0, errdesc='', xdata=T0 + np.arange(3), ydata=np.arange(3) * 2.0,
                               xunit='ns', yunit='A', resolved_pulse=None)

    def get_data_source(self, name):
        return None


def _signal(name='VAR-A', **kwargs):
    return SignalXY(name=name, data_source='uda', ts_start=T0, ts_end=T1, **kwargs)


def _result(values):
    return dict(alias_map={'time': {'idx': 0, 'independent': True}, 'data': {'idx': 1}},
                d0=T0 + np.arange(len(values)), d1=np.asarray(values, dtype=float),
                d2=np.empty(0), d3=np.empty(0), d0_unit='ns', d1_unit='A', d2_unit='', d3_unit='', isds=False)


class DataRequestsTests(unittest.TestCase):
    def setUp(self):
        ParserHelper.env.clear()
        self._da = AccessHelper.da
        AccessHelper.da = _DataAccessStub()

    def tearDown(self):
        AccessHelper.da = self._da
        ParserHelper.env.clear()

    def test_request_key_identifies_the_parameters(self):
        params = AccessHelper.construct_da_params(_signal())
        self.assertEqual(AccessHelper.request_key(params), AccessHelper.request_key(dict(params)))
        self.assertNotEqual(AccessHelper.request_key(params), AccessHelper.request_key(dict(params, tsE=T1 + 1)))
        hash(AccessHelper.request_key(params))

    def test_request_key_tells_every_parameter_apart(self):
        params = AccessHelper.construct_da_params(_signal())
        changes = dict(data_s_name='other', varname='VAR-B', tsS=T0 + 1, tsE=T1 + 1, tsFormat='relative',
                       pulse='ITER:MCTB-TEST/222', envelope=True, extremities=True, nbp=1920,
                       retType='doubleCalibrated')
        # Every parameter construct_da_params() makes, and the calibration it may add.
        self.assertEqual(set(changes) - {'retType'}, set(params))

        for name, value in changes.items():
            with self.subTest(parameter=name):
                self.assertNotEqual(AccessHelper.request_key(params),
                                    AccessHelper.request_key(dict(params, **{name: value})))

    def test_a_signal_asks_for_its_range_until_it_is_read(self):
        signal = _signal()
        self.assertEqual(AccessHelper.data_requests(signal), [AccessHelper.construct_da_params(signal)])

        signal.get_data()

        self.assertEqual(AccessHelper.data_requests(signal), [])
        signal.ts_end = T1 + 1
        self.assertEqual(AccessHelper.data_requests(signal), [AccessHelper.construct_da_params(signal)])

    def test_signals_without_data_access_ask_for_nothing(self):
        disabled = _signal()
        disabled.data_access_enabled = False
        self.assertEqual(AccessHelper.data_requests(disabled), [])
        self.assertEqual(AccessHelper.data_requests(_signal(name='')), [])

    def test_an_expression_asks_for_the_data_of_its_children(self):
        expression = _signal(name='${VAR-A} + ${VAR-B}')

        requests = AccessHelper.data_requests(expression)

        self.assertEqual({params['varname'] for params in requests}, {'VAR-A', 'VAR-B'})
        self.assertEqual(requests, [AccessHelper.construct_da_params(child) for child in expression.children])

    def test_a_child_already_read_is_not_asked_for_again(self):
        expression = _signal(name='${VAR-A} + ${VAR-B}')
        read, unread = expression.children
        read.get_data()

        self.assertEqual(AccessHelper.data_requests(expression), [AccessHelper.construct_da_params(unread)])

    def test_an_alias_used_in_y_is_asked_for_over_the_signal_range(self):
        alias = SignalXY(name='VAR-B', alias='b', data_source='uda', ts_start=T0 + 10, ts_end=T1 - 10)
        alias.get_data()
        signal = _signal(y_expr='${b}.data * 2')
        AccessHelper.da.reads.clear()

        requests = AccessHelper.data_requests(signal)
        with AccessHelper.prefetched({AccessHelper.request_key(params): _result([1.0, 2.0, 3.0])
                                      for params in requests}):
            signal.get_data()

        self.assertEqual(AccessHelper.da.reads, [])
        self.assertIn(dict(AccessHelper.construct_da_params(alias), tsS=T0, tsE=T1), requests)
        np.testing.assert_array_equal(np.asarray(signal.y_data), [2.0, 4.0, 6.0])


class PrefetchedTests(unittest.TestCase):
    def setUp(self):
        ParserHelper.env.clear()
        self._da = AccessHelper.da
        self.stub = AccessHelper.da = _DataAccessStub()

    def tearDown(self):
        AccessHelper.da = self._da
        ParserHelper.env.clear()

    def _results(self, signal, value):
        return {AccessHelper.request_key(AccessHelper.construct_da_params(signal)): value}

    def test_a_result_read_ahead_is_used_instead_of_a_read(self):
        signal = _signal()

        with AccessHelper.prefetched(self._results(signal, _result([5.0, 6.0]))):
            signal.get_data()

        self.assertEqual(self.stub.reads, [])
        self.assertEqual(signal.status_info.result, Result.SUCCESS)
        np.testing.assert_array_equal(np.asarray(signal.y_data), [5.0, 6.0])

    def test_an_error_read_ahead_fails_the_signal_as_a_read_would(self):
        error = DataAccessError("ErrCode: -1 | getData failed. Error: no data")
        read_ahead, read_now = _signal(), _signal()

        with AccessHelper.prefetched(self._results(read_ahead, error)):
            read_ahead.get_data()
        self.stub.get_data = lambda data_s_name, **kwargs: SimpleNamespace(errcode=-1, errdesc='no data')
        read_now.get_data()

        self.assertEqual(read_ahead.status_info.result, Result.FAIL)
        self.assertEqual(read_ahead.status_info.msg, read_now.status_info.msg)

    def test_signals_sharing_a_request_get_buffers_of_their_own(self):
        first, second = _signal(), _signal()

        with AccessHelper.prefetched(self._results(first, _result([1.0, 2.0]))):
            first.get_data()
            second.get_data()
        first.data_store[1][0] = 99.0

        self.assertEqual(self.stub.reads, [])
        np.testing.assert_array_equal(np.asarray(second.data_store[1]), [1.0, 2.0])

    def test_requests_not_read_ahead_are_read(self):
        other = _signal(name='VAR-B')

        with AccessHelper.prefetched(self._results(_signal(), _result([1.0]))):
            other.get_data()

        self.assertEqual(self.stub.reads, ['VAR-B'])
        self.assertEqual(other.status_info.result, Result.SUCCESS)

    def test_reads_of_another_thread_are_not_served(self):
        signal = _signal()

        with AccessHelper.prefetched(self._results(signal, _result([5.0]))):
            reader = threading.Thread(target=signal.get_data)
            reader.start()
            reader.join()

        self.assertEqual(self.stub.reads, ['VAR-A'])

    def test_the_latest_pulse_read_ahead_is_not_read_again_under_its_number(self):
        # Pulse 0 asks for the latest pulse; the reply says which one it is.
        signal = _signal(pulse_nb='0')

        with AccessHelper.prefetched(self._results(signal, dict(_result([5.0, 6.0]), resolved_pulse='42'))):
            signal.get_data()
        signal.get_data()

        self.assertEqual(self.stub.reads, [])
        self.assertEqual(signal.pulse_nb, '42')
        np.testing.assert_array_equal(np.asarray(signal.y_data), [5.0, 6.0])

    def test_results_are_not_served_after_the_block(self):
        before, after = _signal(), _signal()
        with AccessHelper.prefetched(self._results(before, _result([1.0]))):
            before.get_data()

        after.get_data()

        self.assertEqual(self.stub.reads, ['VAR-A'])
        np.testing.assert_array_equal(np.asarray(after.y_data), [0.0, 2.0, 4.0])


if __name__ == '__main__':
    unittest.main()
