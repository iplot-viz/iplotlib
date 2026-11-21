"""AccessHelper reads every sample in one request, with a fallback sample count, and marks
decimated replies as downsampled; data access layers without the fallback are asked again."""

import types
import unittest

import numpy as np

from iplotlib.interface.iplotSignalAdapter import AccessHelper

TOO_MANY = ('Number of samples in reply exceeds available limit. Reduce request interval,'
            ' use decimation or read data by chunks.')


def _reply(**flags):
    y = np.ones(4)
    return types.SimpleNamespace(errcode=0, errdesc='OK', xdata=np.arange(4, dtype=np.int64), ydata=y,
                                 ydata_min=y, ydata_max=y, ydata_avg=y, xunit='ns', yunit='V',
                                 resolved_pulse=None, **flags)


class _DataAccessStub:
    """Answers each request with the next queued reply."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.requests = []

    def get_data_source(self, name):
        return None

    def get_data(self, data_s_name, **request):
        self.requests.append(request)
        return self.replies.pop(0)

    get_envelope = get_data


class AccessHelperDecimationTests(unittest.TestCase):
    def setUp(self):
        self._saved = AccessHelper.da, AccessHelper.num_samples, AccessHelper.num_samples_override
        AccessHelper.num_samples, AccessHelper.num_samples_override = 1920, False

    def tearDown(self):
        AccessHelper.da, AccessHelper.num_samples, AccessHelper.num_samples_override = self._saved

    @staticmethod
    def _request(*replies, envelope=False):
        AccessHelper.da = _DataAccessStub(*replies)
        signal = types.SimpleNamespace(data_source='ds', name='VAR', ts_start=1, ts_end=2, ts_relative=False,
                                       pulse_nb=None, envelope=envelope, extremities=False, calibrated=False)
        result = AccessHelper._request_data(**AccessHelper.construct_da_params(signal))
        return result, AccessHelper.da.requests

    def test_every_sample_is_asked_for_with_the_fallback(self):
        for envelope in (False, True):
            with self.subTest(envelope=envelope):
                result, requests = self._request(_reply(isdecimated=False), envelope=envelope)
                self.assertEqual(len(requests), 1)
                self.assertEqual((requests[0]['nbp'], requests[0]['fallback_nbp']), (-1, 1920))
                self.assertFalse(result['isds'])

    def test_decimated_reply_is_downsampled(self):
        for envelope in (False, True):
            with self.subTest(envelope=envelope):
                result, requests = self._request(_reply(isdecimated=True), envelope=envelope)
                self.assertEqual(len(requests), 1)
                self.assertTrue(result['isds'])

    def test_data_access_without_the_fallback_is_asked_again(self):
        for envelope in (False, True):
            with self.subTest(envelope=envelope):
                too_many = types.SimpleNamespace(errcode=-1, errdesc=TOO_MANY)
                result, requests = self._request(too_many, _reply(), envelope=envelope)
                self.assertEqual([r['nbp'] for r in requests], [-1, 1920])
                self.assertTrue(result['isds'])

    def test_reply_without_the_flag_is_raw(self):
        result, _ = self._request(_reply())
        self.assertFalse(result['isds'])

    def test_forced_sample_count_is_kept(self):
        AccessHelper.num_samples_override = True
        _, requests = self._request(_reply())
        self.assertEqual(requests[0]['nbp'], 1920)


if __name__ == '__main__':
    unittest.main()
