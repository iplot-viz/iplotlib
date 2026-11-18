"""An x, y or z expression that can't be evaluated fails the processing of its signal, as an expression of the variable
does, and the status says which one. A read without samples has nothing to evaluate: the signal is empty.
"""

import unittest
from unittest.mock import patch

import numpy as np

from iplotlib.core.signal import SignalXY
from iplotlib.interface.iplotSignalAdapter import CachingAccessHelper, ParserHelper, Result, Stage

START = 1_700_000_000_000_000_000
STEP = 100_000_000  # 0.1 s
SECOND = 10 ** 9


class _Reader:
    """Reads over the range asked a sample every 0.1 s up to START + 10 s, or every 0.5 s of a pulse, from -5 s to 4 s
    when the range is empty; the data are the times in seconds."""

    def fetch_data(self, signal):
        if signal.ts_relative:
            begin = -5.0 if signal.ts_start == '' else signal.ts_start
            end = 4.0 if signal.ts_end == '' else signal.ts_end
            time = np.arange(begin, end + 0.25, 0.5)
        else:
            time = np.arange(signal.ts_start, min(signal.ts_end, START + 10 * SECOND) + 1, STEP, dtype=np.int64)
        signal.inject_external(alias_map={'time': {'idx': 0, 'independent': True}, 'data': {'idx': 1}},
                               d0=time, d1=time / 1e9, d2=np.zeros(0), d3=np.zeros(0))


class XYZExpressionFailuresTest(unittest.TestCase):
    def setUp(self):
        ParserHelper.env.clear()
        ParserHelper.dict_result.clear()
        patcher = patch.object(CachingAccessHelper, 'get', return_value=_Reader())
        patcher.start()
        self.addCleanup(patcher.stop)

    @staticmethod
    def _signal(**expressions):
        return SignalXY(name='VAR', data_source='test', ts_start=START, ts_end=START + 10 * SECOND, **expressions)

    @staticmethod
    def _zoom(signal, begin, end):
        signal.set_xranges((begin, end))
        signal.get_data()

    def assertFails(self, signal, expression, reason):
        status = signal.status_info
        self.assertEqual((status.result, status.stage, status.expression), (Result.FAIL, Stage.PROC, expression),
                         status.msg)
        self.assertIn(reason, status.msg)

    def test_a_y_that_fails_fails_the_signal(self):
        signal = self._signal(y_expr='${self}.data[::0]')
        signal.get_data()

        self.assertFails(signal, 'y', 'the y expression failed: ')

    def test_an_x_reading_a_start_time_the_row_has_not_says_so(self):
        # A whole pulse: no start time.
        signal = SignalXY(name='VAR', data_source='test', pulse_nb='ITER:MCTB-TEST/111',
                          x_expr='${self}.time - ${startTime}')
        signal.get_data()

        self.assertFails(signal, 'x', '${startTime} has no value')

    def test_the_signal_is_processed_again_with_the_next_data(self):
        # Fails with fewer than six samples.
        signal = self._signal(x_expr='${self}.time - ${self}.time[5]')
        self._zoom(signal, START, START + 3 * STEP)
        self.assertFails(signal, 'x', 'index 5 is out of bounds')

        self._zoom(signal, START, START + 2 * SECOND)

        self.assertEqual(signal.status_info.result, Result.SUCCESS, signal.status_info.msg)
        self.assertEqual(signal.status_info.expression, '')
        self.assertEqual(len(signal.x_data), 21)

    def test_without_samples_the_signal_is_empty(self):
        signal = self._signal(x_expr='(${self}.time - ${self}.time[0]) / 1e9')
        signal.get_data()
        self.assertEqual(len(signal.x_data), 101)

        # After the last sample.
        self._zoom(signal, START + 12 * SECOND, START + 14 * SECOND)

        self.assertEqual((signal.status_info.result, signal.status_info.num_points), (Result.SUCCESS, 0))
        self.assertEqual((len(signal.x_data), len(signal.y_data)), (0, 0))


if __name__ == '__main__':
    unittest.main()
