"""Regression tests for IplotSignalAdapter.truncate_to_target (issue #69).

These lock in the behaviour of the shape-alignment helper that sits on the
signal-processing hot path: dtype preservation on single-point replication,
silent no-op on empty source, per-signature warning deduplication, and the
clear-labelled warning message format.
"""

import logging
import unittest

import numpy as np
from iplotProcessing.core import BufferObject

from iplotlib.interface import iplotSignalAdapter as adapter_module
from iplotlib.interface.iplotSignalAdapter import IplotSignalAdapter


class TruncateToTargetTests(unittest.TestCase):
    def setUp(self):
        # Each test starts with a fresh dedup set so warning assertions are stable.
        adapter_module._TRUNCATE_WARN_KEYS.clear()

    def test_single_point_replication_preserves_int_dtype(self):
        source = BufferObject(np.array([7], dtype=np.int64))
        target = BufferObject(np.array([0, 1, 2, 3], dtype=np.int64))
        out = IplotSignalAdapter.truncate_to_target(source, target)
        self.assertEqual(len(out), 4)
        self.assertEqual(out.dtype, np.int64)
        self.assertTrue((np.asarray(out) == 7).all())

    def test_single_point_replication_preserves_datetime_dtype(self):
        ts = np.datetime64('2026-04-20T12:00:00', 'ns')
        source = BufferObject(np.array([ts]))
        target = BufferObject(np.arange(3))
        out = IplotSignalAdapter.truncate_to_target(source, target)
        self.assertEqual(len(out), 3)
        self.assertEqual(out.dtype, source.dtype)
        self.assertTrue((np.asarray(out) == ts).all())

    def test_empty_source_returns_as_is_without_warning(self):
        source = BufferObject(np.array([], dtype=np.float64))
        target = BufferObject(np.arange(10))
        with self.assertLogs(adapter_module.logger.name, level='WARNING') as cm:
            out = IplotSignalAdapter.truncate_to_target(
                source, target, source_label='z', target_label='x')
            # Ensure assertLogs has at least one entry to not raise: log harmlessly.
            adapter_module.logger.warning("_sentinel_")
        self.assertEqual(len(out), 0)
        self.assertEqual(
            [m for m in cm.output if 'different lengths' in m], [],
            "Empty source must not produce a shape-mismatch warning")

    def test_truncation_when_source_longer_than_target(self):
        source = BufferObject(np.arange(10, dtype=np.int64))
        target = BufferObject(np.arange(3))
        out = IplotSignalAdapter.truncate_to_target(source, target)
        self.assertEqual(len(out), 3)
        self.assertEqual(out.dtype, np.int64)
        self.assertTrue((np.asarray(out) == np.array([0, 1, 2])).all())

    def test_warning_dedup_across_signatures(self):
        source = BufferObject(np.array([1]))
        target = BufferObject(np.arange(2))
        with self.assertLogs(adapter_module.logger.name, level='DEBUG') as cm:
            IplotSignalAdapter.truncate_to_target(
                source, target, source_label='y', target_label='x')
            IplotSignalAdapter.truncate_to_target(
                source, target, source_label='y', target_label='x')
        warnings = [r for r in cm.records if r.levelno == logging.WARNING
                    and 'different lengths' in r.getMessage()]
        debugs = [r for r in cm.records if r.levelno == logging.DEBUG
                  and 'different lengths' in r.getMessage()]
        self.assertEqual(len(warnings), 1,
                         "Identical mismatches must warn once per session")
        self.assertEqual(len(debugs), 1,
                         "Identical repeats must downgrade to debug")

    def test_warning_uses_axis_labels_for_y_x_pair(self):
        source = BufferObject(np.array([1]))
        target = BufferObject(np.arange(2))
        with self.assertLogs(adapter_module.logger.name, level='WARNING') as cm:
            IplotSignalAdapter.truncate_to_target(
                source, target, source_label='y', target_label='x')
        combined = '\n'.join(cm.output)
        self.assertIn('y and x expressions', combined)
        self.assertNotIn('source and target', combined)


if __name__ == '__main__':
    unittest.main()
