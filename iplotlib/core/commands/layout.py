"""
Command for undo/redo of moving or resizing a plot on the grid of a canvas, or of laying its plots out on a grid.
"""

import weakref
from typing import Callable, List, Optional

from iplotlib.core.command import IplotCommand
from iplotlib.core.layout import Arrangement


class ArrangeCommand(IplotCommand):
    """Command to undo/redo a change of the places of the plots of a canvas."""

    def __init__(self, name: str, before: Arrangement, after: Arrangement, arrange: Callable,
                 views: List = None) -> None:
        super().__init__(name)
        self._before = before
        self._after = after
        # Lays the canvas out as an arrangement says, given what moved (see Arrangement.changes), the arrangement it
        # replaces and the views of the plots that come back, and gives the views the plots had before: a method of
        # the Qt canvas, which the history does not keep alive.
        self._arrange = weakref.WeakMethod(arrange)
        # The views of the plots before the change, which the plots joined into one take back on undo.
        self._views = views or []

    def _apply(self, arrangement: Arrangement, changes: list, replaced: Arrangement, views: List = None) \
            -> Optional[List]:
        arrange = self._arrange()
        return arrange(arrangement, changes, replaced, views) if arrange is not None else None

    def undo(self):
        super().undo()
        self._apply(self._before, [(after, before) for before, after in self._after.changes], self._after,
                    self._views)

    def __call__(self):
        super().__call__()
        views = self._apply(self._after, self._after.changes, self._before)
        if views is not None:
            self._views = views

    def __str__(self):
        return f"ArrangeCommand({self.name}, {len(self._after.changes)} changes)"
