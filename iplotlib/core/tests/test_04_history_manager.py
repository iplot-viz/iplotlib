"""Unit tests for the iplotlib HistoryManager."""

import unittest

from iplotlib.core.command import IplotCommand
from iplotlib.core.history_manager import HistoryManager


class _RecordingCommand(IplotCommand):
    """Minimal command that records invocation order for assertions."""

    def __init__(self, name: str, log: list):
        super().__init__(name)
        self._log = log

    def __call__(self):
        self._log.append(("redo", self.name))

    def undo(self):
        self._log.append(("undo", self.name))


class TestHistoryManager(unittest.TestCase):
    def setUp(self) -> None:
        self.hm = HistoryManager()
        self.log = []

    def test_initial_state(self):
        self.assertFalse(self.hm.can_undo())
        self.assertFalse(self.hm.can_redo())
        self.assertEqual(self.hm.get_next_undo_cmd_name(), "")
        self.assertEqual(self.hm.get_next_redo_cmd_name(), "")

    def test_done_enables_undo(self):
        cmd = _RecordingCommand("Zoom", self.log)
        self.hm.done(cmd)
        self.assertTrue(self.hm.can_undo())
        self.assertEqual(self.hm.get_next_undo_cmd_name(), "Zoom")

    def test_undo_then_redo(self):
        cmd = _RecordingCommand("Zoom", self.log)
        self.hm.done(cmd)
        self.hm.undo()
        self.assertFalse(self.hm.can_undo())
        self.assertTrue(self.hm.can_redo())
        self.assertEqual(self.log, [("undo", "Zoom")])

        self.hm.redo()
        self.assertTrue(self.hm.can_undo())
        self.assertFalse(self.hm.can_redo())
        self.assertEqual(self.log, [("undo", "Zoom"), ("redo", "Zoom")])

    def test_done_clears_redo_stack(self):
        cmd1 = _RecordingCommand("Zoom", self.log)
        cmd2 = _RecordingCommand("Pan", self.log)
        self.hm.done(cmd1)
        self.hm.undo()
        self.assertTrue(self.hm.can_redo())

        self.hm.done(cmd2)
        self.assertFalse(self.hm.can_redo())

    def test_undo_on_empty_does_not_raise(self):
        # Should log a warning but not raise.
        self.hm.undo()
        self.assertFalse(self.hm.can_undo())

    def test_drop_clears_both_stacks(self):
        self.hm.done(_RecordingCommand("Zoom", self.log))
        self.hm.undo()
        self.hm.drop()
        self.assertFalse(self.hm.can_undo())
        self.assertFalse(self.hm.can_redo())

    def test_non_redoable_command_not_pushed_to_redo(self):
        cmd = _RecordingCommand("OtherAction", self.log)
        self.hm.done(cmd)
        self.hm.undo()
        # HistoryManager only re-pushes known interactive commands onto the redo stack.
        self.assertFalse(self.hm.can_redo())


if __name__ == "__main__":
    unittest.main()
