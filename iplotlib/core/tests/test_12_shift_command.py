"""Unit tests for the ShiftCommand undo/redo semantics.

ShiftCommand is the concrete IplotCommand used when the user drags a signal
in the UI (or triggers a shift from the signals table). The undo/redo path
is what keeps the history stack consistent when the user zooms/pans in and
out of a shifted state, so the invariants below must not drift silently.
"""

import types
import unittest
from unittest.mock import MagicMock

from iplotlib.core.commands.shift import ShiftCommand


def _fake_signal(uid: str = 'uid-1', initial_dx: float = 0.0, initial_dy: float = 0.0):
    signal = types.SimpleNamespace(uid=uid, name='sig')
    if initial_dx:
        signal._drag_shift_dx = initial_dx
    if initial_dy:
        signal._drag_shift_dy = initial_dy
    return signal


def _fake_parser():
    parser = MagicMock()
    parser._signal_impl_plot_lut = {}
    return parser


class ShiftCommandApplyTest(unittest.TestCase):
    def test_apply_sets_drag_shift_metadata(self):
        signal = _fake_signal()
        parser = _fake_parser()
        cmd = ShiftCommand(signal, dx=2.5, dy=-1.0, parser=parser)

        cmd()

        self.assertAlmostEqual(signal._drag_shift_dx, 2.5)
        self.assertAlmostEqual(signal._drag_shift_dy, -1.0)
        parser.process_ipl_signal.assert_called_with(signal)

    def test_apply_accumulates_on_top_of_existing_offset(self):
        """A second shift stacks on top of the previous one."""
        signal = _fake_signal(initial_dx=1.0, initial_dy=0.5)
        parser = _fake_parser()
        cmd = ShiftCommand(signal, dx=2.0, dy=0.5, parser=parser)

        cmd()

        self.assertAlmostEqual(signal._drag_shift_dx, 3.0)
        self.assertAlmostEqual(signal._drag_shift_dy, 1.0)

    def test_undo_restores_previous_offset(self):
        signal = _fake_signal(initial_dx=1.0, initial_dy=2.0)
        parser = _fake_parser()
        cmd = ShiftCommand(signal, dx=0.5, dy=-1.0, parser=parser)

        cmd()
        cmd.undo()

        self.assertAlmostEqual(signal._drag_shift_dx, 1.0)
        self.assertAlmostEqual(signal._drag_shift_dy, 2.0)

    def test_undo_clears_attribute_when_offset_returns_to_zero(self):
        """After undo of a shift applied on a pristine signal, metadata is cleared."""
        signal = _fake_signal()
        parser = _fake_parser()
        cmd = ShiftCommand(signal, dx=3.0, dy=4.0, parser=parser)

        cmd()
        cmd.undo()

        self.assertFalse(hasattr(signal, '_drag_shift_dx'))
        self.assertFalse(hasattr(signal, '_drag_shift_dy'))

    def test_none_signal_is_tolerated(self):
        """Construction and apply with a None signal must not raise."""
        parser = _fake_parser()
        cmd = ShiftCommand(None, dx=1.0, dy=1.0, parser=parser)

        cmd()
        cmd.undo()

        parser.process_ipl_signal.assert_not_called()


class ShiftCommandQtSignalEmissionTest(unittest.TestCase):
    def test_apply_emits_inline_signal_on_qt_canvas(self):
        signal = _fake_signal(uid='uid-42')
        parser = _fake_parser()
        qt_canvas = MagicMock()
        cmd = ShiftCommand(signal, dx=1.0, dy=2.0, parser=parser,
                           qt_canvas=qt_canvas, source='drag')

        cmd()

        qt_canvas.signalShiftApplied.emit.assert_called_once_with(
            'uid-42', 1.0, 2.0, 'drag')

    def test_undo_emits_undone_signal_on_qt_canvas(self):
        signal = _fake_signal(uid='uid-42')
        parser = _fake_parser()
        qt_canvas = MagicMock()
        cmd = ShiftCommand(signal, dx=1.0, dy=2.0, parser=parser,
                           qt_canvas=qt_canvas, source='drag')

        cmd()
        cmd.undo()

        qt_canvas.signalShiftUndone.emit.assert_called_once_with(
            'uid-42', 1.0, 2.0, 'drag')

    def test_pulse_isolation_uses_pulse_specific_signals(self):
        signal = _fake_signal(uid='uid-9')
        parser = _fake_parser()
        qt_canvas = MagicMock()
        cmd = ShiftCommand(signal, dx=0.5, dy=0.1, parser=parser,
                           qt_canvas=qt_canvas, is_pulse_isolation=True,
                           pulse_id='ITER:A/1', source='table')

        cmd()

        qt_canvas.signalShiftPulseApplied.emit.assert_called_once_with(
            'uid-9', 'ITER:A/1', 0.5, 0.1, 'table')


class ShiftCommandStringTest(unittest.TestCase):
    def test_str_contains_name_and_deltas(self):
        signal = _fake_signal()
        signal.name = 'MAG-MCTB-F1:VAR1'
        cmd = ShiftCommand(signal, dx=1.5, dy=-0.25, parser=_fake_parser())

        text = str(cmd)

        self.assertIn('MAG-MCTB-F1:VAR1', text)
        self.assertIn('1.5', text)
        self.assertIn('inline', text)


if __name__ == '__main__':
    unittest.main()
