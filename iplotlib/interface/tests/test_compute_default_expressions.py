"""IplotSignalAdapter.compute with only some expressions changed.

An expression left at its default reads its buffer directly, whatever the other
axes use. An envelope signal has no 'data' alias, so evaluating the default Y
expression through the parser failed as soon as its X was an expression, and
the whole signal came out empty.
"""

import unittest

import numpy as np

from iplotlib.core.signal import SignalXY
from iplotlib.interface.iplotSignalAdapter import ParserHelper


class ComputeDefaultExpressionsTest(unittest.TestCase):
    def setUp(self):
        # ParserHelper holds class-level state that would leak across tests.
        ParserHelper.env.clear()
        ParserHelper.dict_result.clear()

    @staticmethod
    def _signal(envelope):
        signal = SignalXY(label="s", x_expr="${self}.time - 100", envelope=envelope)
        time = np.arange(100, 110, dtype=np.int64)
        if envelope:
            # Same aliases an envelope fetch leaves (AccessHelper.on_fetch_done): no 'data'.
            signal.alias_map.clear()
            signal.alias_map.update({'time': {'idx': 0, 'independent': True},
                                     'dmin': {'idx': 1}, 'dmax': {'idx': 2}, 'davg': {'idx': 3}})
            while len(signal.data_store) < 4:
                signal.data_store.append(np.zeros(0))
            signal.data_store[1] = np.arange(10.0) - 1
            signal.data_store[2] = np.arange(10.0) + 1
            signal.data_store[3] = np.arange(10.0)
        else:
            signal.alias_map.update({'time': {'idx': 0, 'independent': True}, 'data': {'idx': 1}})
            signal.data_store[1] = np.arange(10.0) * 2
        signal.data_store[0] = time
        return signal

    def test_envelope_with_x_expression_keeps_its_min_and_max(self):
        signal = self._signal(envelope=True)
        result = signal.compute(x=signal.x_expr, y=signal.y_expr, z=signal.z_expr)
        np.testing.assert_array_equal(np.asarray(result['x']), np.arange(10))
        np.testing.assert_array_equal(np.asarray(result['y']), np.arange(10.0) - 1)
        np.testing.assert_array_equal(np.asarray(result['z']), np.arange(10.0) + 1)

    def test_default_y_reads_the_same_values_as_before(self):
        signal = self._signal(envelope=False)
        result = signal.compute(x=signal.x_expr, y=signal.y_expr, z=signal.z_expr)
        np.testing.assert_array_equal(np.asarray(result['x']), np.arange(10))
        np.testing.assert_array_equal(np.asarray(result['y']), np.arange(10.0) * 2)

    def test_changed_expression_is_still_evaluated(self):
        signal = self._signal(envelope=False)
        result = signal.compute(x=signal.x_expr, y="${self}.data + 1", z=signal.z_expr)
        np.testing.assert_array_equal(np.asarray(result['y']), np.arange(10.0) * 2 + 1)


if __name__ == '__main__':
    unittest.main()
