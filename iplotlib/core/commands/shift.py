"""
Command for undo/redo of signal shift operations.

Supports two modes:
- Inline mode: applies offset via signal metadata (_drag_shift_dx, _drag_shift_dy)
- Pulse isolation mode: emits signals for table handlers to manage rows
"""

import weakref
from iplotlib.core.command import IplotCommand


class ShiftCommand(IplotCommand):
    """Command to undo/redo shift operations on a signal."""

    def __init__(self,
                 signal,
                 dx: float,
                 dy: float,
                 parser,
                 qt_canvas=None,
                 is_pulse_isolation: bool = False,
                 pulse_id: str = None,
                 source: str = 'drag') -> None:
        super().__init__('Shift')
        self._signal = signal
        self._signal_uid = signal.uid if signal else None
        self._dx = dx
        self._dy = dy
        self._parser = parser
        self._qt_canvas = weakref.ref(qt_canvas) if qt_canvas else None
        self._source = source
        self._previous_dx = getattr(signal, '_drag_shift_dx', 0.0) if signal else 0.0
        self._previous_dy = getattr(signal, '_drag_shift_dy', 0.0) if signal else 0.0
        self._is_pulse_isolation = is_pulse_isolation
        self._pulse_id = pulse_id

    def _apply_offset(self, dx_total: float, dy_total: float):
        """Apply offset via metadata and redraw."""
        if self._signal is None:
            return

        if abs(dx_total) > 1e-10:
            self._signal._drag_shift_dx = dx_total
        elif hasattr(self._signal, '_drag_shift_dx'):
            delattr(self._signal, '_drag_shift_dx')

        if abs(dy_total) > 1e-10:
            self._signal._drag_shift_dy = dy_total
        elif hasattr(self._signal, '_drag_shift_dy'):
            delattr(self._signal, '_drag_shift_dy')

        self._parser.process_ipl_signal(self._signal)

        # Get plot and rebuild legend
        plot = None
        if hasattr(self._signal, 'parent'):
            parent = self._signal.parent
            plot = parent() if callable(parent) else parent

        impl_plot = self._parser._signal_impl_plot_lut.get(self._signal_uid)
        if impl_plot and plot:
            self._parser.rebuild_legend(impl_plot, plot)

    def _emit_table_signal(self, is_undo: bool):
        """Emit Qt signal for table handlers."""
        if self._qt_canvas is None:
            return
        canvas = self._qt_canvas()
        if canvas is None:
            return

        if self._is_pulse_isolation:
            if is_undo:
                if hasattr(canvas, 'signalShiftPulseUndone'):
                    canvas.signalShiftPulseUndone.emit(
                        self._signal_uid, self._pulse_id, self._previous_dx, self._previous_dy)
            else:
                if hasattr(canvas, 'signalShiftPulseApplied'):
                    canvas.signalShiftPulseApplied.emit(
                        self._signal_uid, self._pulse_id, self._dx, self._dy, self._source)
        else:
            if is_undo:
                if hasattr(canvas, 'signalShiftUndone'):
                    canvas.signalShiftUndone.emit(self._signal_uid, self._dx, self._dy, self._source)
            else:
                if hasattr(canvas, 'signalShiftApplied'):
                    canvas.signalShiftApplied.emit(self._signal_uid, self._dx, self._dy, self._source)

    def undo(self):
        """Undo: restore previous offset state."""
        super().undo()
        if self._signal is None:
            return
        self._apply_offset(self._previous_dx, self._previous_dy)
        self._emit_table_signal(is_undo=True)

    def __call__(self):
        """Redo: apply the offset."""
        super().__call__()
        if self._signal is None:
            return
        self._apply_offset(self._previous_dx + self._dx, self._previous_dy + self._dy)
        self._emit_table_signal(is_undo=False)

    def __str__(self):
        name = getattr(self._signal, 'name', 'unknown') if self._signal else 'None'
        mode = "pulse" if self._is_pulse_isolation else "inline"
        return f"ShiftCommand({name}, dx={self._dx:.4f}, dy={self._dy:.4f}, {mode})"

