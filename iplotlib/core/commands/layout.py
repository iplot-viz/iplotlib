"""
Command for undo/redo of moving or resizing a plot on the grid of a canvas.
"""

import weakref
from typing import Callable

from iplotlib.core.command import IplotCommand
from iplotlib.core.layout import Arrangement


class ArrangeCommand(IplotCommand):
    """Command to undo/redo a change of the places of the plots of a canvas."""

    def __init__(self, name: str, before: Arrangement, after: Arrangement, arrange: Callable) -> None:
        super().__init__(name)
        self._before = before
        self._after = after
        # Lays the canvas out as an arrangement says, given what moved (see Arrangement.changes): a method of the
        # Qt canvas, which the history does not keep alive.
        self._arrange = weakref.WeakMethod(arrange)

    def _apply(self, arrangement: Arrangement, changes: list):
        arrange = self._arrange()
        if arrange is not None:
            arrange(arrangement, changes)

    def undo(self):
        super().undo()
        self._apply(self._before, [(after, before) for before, after in self._after.changes])

    def __call__(self):
        super().__call__()
        self._apply(self._after, self._after.changes)

    def __str__(self):
        return f"ArrangeCommand({self.name}, {len(self._after.changes)} changes)"
