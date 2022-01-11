from collections import deque

from iplotlib.core.command import IplotCommand
import iplotLogging.setupLogger as ls

logger = ls.get_logger(__name__)

class HistoryManager:
    def __init__(self) -> None:
        self._undo_stack = deque()
        self._redo_stack = deque()

    def done(self, cmd: IplotCommand):
        assert isinstance(cmd, IplotCommand)
        self._redo_stack.clear()
        self._undo_stack.append(cmd)
        logger.debug(f"UndoStack: {self._undo_stack}")
        logger.debug(f"RedoStack: {self._redo_stack}")

    def undo(self) -> None:
        try:
            cmd = self._undo_stack.pop() # type: IplotCommand
            cmd.undo()
            self._redo_stack.append(cmd)
            logger.debug(f"Undo {cmd.name}")
            logger.debug(f"UndoStack: {self._undo_stack}")
            logger.debug(f"RedoStack: {self._redo_stack}")
        except (IndexError, AssertionError) as _:
            logger.warning(f"Cannot undo. No more commands.")
            return

    def redo(self) -> None:
        try:
            cmd = self._redo_stack.pop() # type: IplotCommand
            cmd()
            self._undo_stack.append(cmd)
            logger.debug(f"Redo {cmd.name}")
            logger.debug(f"UndoStack: {self._undo_stack}")
            logger.debug(f"RedoStack: {self._redo_stack}")
        except (IndexError, AssertionError) as _:
            logger.warning(f"Cannot redo. No more commands.")
            return

    def drop(self) -> None:
        self._iplot_commands.clear()
        logger.debug(f"UndoStack: {self._undo_stack}")
        logger.debug(f"RedoStack: {self._redo_stack}")
