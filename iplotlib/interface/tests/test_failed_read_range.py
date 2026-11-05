"""A signal whose data could not be read over a range, as when its variable does not exist, is drawn with none. A zoom
or a pan within that range does not read it again in vain; one that goes out of it, or another pulse, does.
"""

import unittest
from unittest.mock import patch

from iplotlib.core.signal import SignalXY
from iplotlib.interface.iplotSignalAdapter import CachingAccessHelper, ParserHelper


class _Failing:
    """Each read fails, and is noted with the range and the pulse it was for."""

    def __init__(self):
        self.reads = []

    def fetch_data(self, signal):
        self.reads.append((signal.ts_start, signal.ts_end, signal.pulse_nb))
        signal.set_da_fail('no such variable')


class FailedReadRangeTest(unittest.TestCase):
    def setUp(self):
        ParserHelper.env.clear()
        self.access = _Failing()
        patcher = patch.object(CachingAccessHelper, 'get', return_value=self.access)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_range_within_the_one_a_read_failed_over_is_not_read_again(self):
        signal = SignalXY(name='PLAIN-VAR', data_source='test', ts_start=0, ts_end=10)
        signal.get_data()

        for begin, end in ((2, 8), (0, 10), (-5, 20), (-5, 5)):
            signal.set_xranges((begin, end))
            signal.get_data()

        self.assertEqual(self.access.reads, [(0, 10, None), (-5, 20, None)])

    def test_another_pulse_is_read_again(self):
        signal = SignalXY(name='PLAIN-VAR', data_source='test', pulse_nb=['P1'])
        signal.get_data()

        signal.pulse_nb = ['P2']
        signal.get_data()

        self.assertEqual(self.access.reads, [('', '', ['P1']), ('', '', ['P2'])])

    def test_a_zoom_on_a_whole_pulse_that_could_not_be_read_does_not_read_it_again(self):
        signal = SignalXY(name='PLAIN-VAR', data_source='test', pulse_nb=['P1'])
        signal.get_data()

        signal.set_xranges((2, 8))
        signal.get_data()

        self.assertEqual(self.access.reads, [('', '', ['P1'])])


if __name__ == '__main__':
    unittest.main()
