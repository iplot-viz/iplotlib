"""The expressions of a row read the time range the table gives it as ${startTime} and ${endTime}, and its pulse as
${pulseID}. A zoom reads the data again over its own range: those values stay the ones of the table, so an X taken
from ${startTime} keeps its origin, where one taken from the first time read moves with each zoom.
"""

import unittest
from unittest.mock import patch

import numpy as np

from iplotlib.core.signal import SignalXY
from iplotlib.interface.iplotSignalAdapter import CachingAccessHelper, ParserHelper, Result

START, END = 1_700_000_000_000_000_000, 1_700_000_010_000_000_000  # ten seconds, in nanoseconds
STEP = 100_000_000


class _Reader:
    """Reads over the range asked a sample every 0.1 s, or every 0.5 s of a pulse, from -5 s to 4 s when the range
    is empty; the data are the times in seconds."""

    def __init__(self):
        self.reads = []

    def fetch_data(self, signal):
        self.reads.append((signal.name, signal.ts_start, signal.ts_end))
        if signal.ts_relative:
            begin = -5.0 if signal.ts_start == '' else signal.ts_start
            end = 4.0 if signal.ts_end == '' else signal.ts_end
            time = np.arange(begin, end + 0.25, 0.5)
        else:
            time = np.arange(signal.ts_start, signal.ts_end + 1, STEP, dtype=np.int64)
        signal.inject_external(alias_map={'time': {'idx': 0, 'independent': True}, 'data': {'idx': 1}},
                               d0=time, d1=time / 1e9, d2=np.zeros(0), d3=np.zeros(0))


class RowValuesTest(unittest.TestCase):
    def setUp(self):
        ParserHelper.env.clear()
        ParserHelper.dict_result.clear()
        self.reader = _Reader()
        patcher = patch.object(CachingAccessHelper, 'get', return_value=self.reader)
        patcher.start()
        self.addCleanup(patcher.stop)

    @staticmethod
    def _zoom(signal, begin, end):
        signal.set_xranges((begin, end))
        signal.get_data()

    def test_an_x_from_the_start_time_keeps_its_origin_through_a_zoom(self):
        signal = SignalXY(name='VAR', data_source='test', ts_start=START, ts_end=END,
                          x_expr='(${self}.time - ${startTime}) / 1e9')
        signal.get_data()
        np.testing.assert_allclose(np.asarray(signal.x_data)[[0, -1]], [0.0, 10.0])

        self._zoom(signal, START + 4 * 10 ** 9, START + 6 * 10 ** 9)

        self.assertEqual(self.reader.reads[-1], ('VAR', START + 4 * 10 ** 9, START + 6 * 10 ** 9))
        np.testing.assert_allclose(np.asarray(signal.x_data)[[0, -1]], [4.0, 6.0])

    def test_an_x_from_the_first_time_read_moves_with_a_zoom(self):
        # What ${startTime} is for.
        signal = SignalXY(name='VAR', data_source='test', ts_start=START, ts_end=END,
                          x_expr='(${self}.time - ${self}.time[0]) / 1e9')
        signal.get_data()

        self._zoom(signal, START + 4 * 10 ** 9, START + 6 * 10 ** 9)

        np.testing.assert_allclose(np.asarray(signal.x_data)[[0, -1]], [0.0, 2.0])

    def test_the_end_time_and_the_pulse(self):
        signal = SignalXY(name='VAR', data_source='test', ts_start=-5.0, ts_end=4.0, pulse_nb='ITER:MCTB-TEST/111',
                          y_expr='${self}.data * 0 + ${endTime}')
        signal.get_data()

        self.assertEqual(signal.status_info.result, Result.SUCCESS, signal.status_info.msg)
        np.testing.assert_array_equal(np.unique(np.asarray(signal.y_data)), [4.0])
        self.assertEqual(signal.row_values(['pulseID'])['pulseID'].data, 'ITER:MCTB-TEST/111')

    def test_an_expression_of_the_variable_column_reads_them_too(self):
        SignalXY(name='VAR', alias='A', data_source='test', ts_start=START, ts_end=END)
        signal = SignalXY(name='${A} - ${startTime} / 1e9', data_source='test', ts_start=START, ts_end=END)
        signal.get_data()

        self.assertEqual(signal.status_info.result, Result.SUCCESS, signal.status_info.msg)
        np.testing.assert_allclose(np.asarray(signal.y_data)[[0, -1]], [0.0, 10.0])
        self.assertEqual([read[0] for read in self.reader.reads], ['VAR'])  # the variable of A, and nothing else

    def test_they_are_no_signals_to_read(self):
        signal = SignalXY(name='VAR', data_source='test', ts_start=START, ts_end=END,
                          x_expr='${self}.time - ${startTime}', y_expr='${self}.data + ${endTime} - ${pulseID}')

        self.assertEqual(signal.depends_on, {'self'})
        self.assertEqual(signal.children, [])

    def test_an_alias_cannot_take_the_name_of_a_value_of_the_row(self):
        signal = SignalXY(name='VAR', alias='startTime', data_source='test', ts_start=START, ts_end=END)

        self.assertEqual(signal.status_info.result, Result.INVALID)
        self.assertIn("The alias 'startTime' is taken", signal.status_info.msg)
        self.assertNotIn('startTime', ParserHelper.env)

    def test_a_value_the_row_has_none_of_says_so(self):
        # A whole pulse: no start time.
        SignalXY(name='VAR', alias='B', data_source='test', pulse_nb='ITER:MCTB-TEST/111')
        signal = SignalXY(name='${B} - ${startTime}', data_source='test', pulse_nb='ITER:MCTB-TEST/111')
        signal.get_data()

        self.assertEqual(signal.status_info.result, Result.FAIL)
        self.assertIn('${startTime} has no value', signal.status_info.msg)

if __name__ == '__main__':
    unittest.main()
