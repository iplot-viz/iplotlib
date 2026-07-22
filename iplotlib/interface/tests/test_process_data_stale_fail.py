"""Regression tests for IplotSignalAdapter._process_data status handling.

With data access disabled (streaming), an expression signal evaluated before
its children have data is marked Fail. A later successful re-evaluation must
supersede that stale Fail and populate x/y data; a Fail on a signal with no
expression to re-evaluate must persist.
"""

import unittest

import numpy as np

from iplotlib.core.signal import SignalXY
from iplotlib.interface.iplotSignalAdapter import ParserHelper, Result


class ProcessDataStaleFailTests(unittest.TestCase):
    def setUp(self):
        # ParserHelper holds class-level state that would leak across tests.
        ParserHelper.env.clear()
        ParserHelper.dict_result.clear()

    def _make_expression_signal(self):
        # Mirrors the mint streaming build: the signal is constructed with data
        # access enabled (children get created) and disabled right afterwards.
        parent = SignalXY(name='${VAR1}*10', data_source='test')
        parent.data_access_enabled = False
        self.assertEqual(len(parent.children), 1)
        child = parent.children[0]
        child.data_access_enabled = False
        return parent, child

    def test_successful_reevaluation_supersedes_stale_fail(self):
        parent, child = self._make_expression_signal()

        parent._do_data_processing()  # child has no data yet
        self.assertEqual(parent.status_info.result, Result.FAIL)

        x = np.arange(5, dtype=np.int64)
        y = np.arange(5, dtype=np.float64)
        child.set_data([x, y, np.array([])])

        parent._do_data_processing()
        self.assertEqual(parent.status_info.result, Result.SUCCESS)
        np.testing.assert_array_equal(np.asarray(parent.x_data), x)
        np.testing.assert_array_equal(np.asarray(parent.y_data), y * 10)

    def test_fail_persists_without_children_to_reevaluate(self):
        signal = SignalXY(name='PLAIN-VAR', data_source='test')
        signal.data_access_enabled = False
        signal.set_proc_fail('fetch broke')

        signal._do_data_processing()
        self.assertEqual(signal.status_info.result, Result.FAIL)
        self.assertEqual(len(signal.x_data), 0)


if __name__ == '__main__':
    unittest.main()
