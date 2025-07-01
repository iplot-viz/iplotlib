# Copyright (c) 2020-2025 ITER Organization,
#               CS 90046
#               13067 St Paul Lez Durance Cedex
#               France
# Author IO
#
# This file is part of iplotlib module.
# iplotlib python module is free software: you can redistribute it and/or modify it under
# the terms of the MIT license.
#
# This file is part of ITER CODAC software.
# For the terms and conditions of redistribution or use of this software
# refer to the file LICENSE located in the top level directory
# of the distribution package
#


"""
The history manager is responsible for maintaining a list of
actions that were done in the past and offering the ability to
'undo' the actions in the reverse order. It is possible to redo
the actions by unwinding the redo stack.

Traditionally, the history was backend dependent. This proved less
robust when we needed to retain the view limits, for example: 
after applying plot preferences.

An action is represented by a :data:`~iplotlib.core.command.IplotCommand`
instance. Each command has an `undo` method and the command itself is
callable.
"""

# Author: Jaswant Sai Panchumarti

from collections import deque
from typing import Deque
from iplotlib.core.command import IplotCommand
import iplotLogging.setupLogger as Sl

logger = Sl.get_logger(__name__)


class HistoryManager:
    """
    The history manager maintains two deques.
    A deque is used instead of a list to offer more features
    like event bubbling in the future, if necessary.
    """

    def __init__(self) -> None:
        self._undo_stack = deque()  # type: Deque[IplotCommand]
        self._redo_stack = deque()  # type: Deque[IplotCommand]

    def done(self, cmd: IplotCommand):
        """
        Call this with the command object to push it onto the undo stack.
        """
        assert isinstance(cmd, IplotCommand)
        self._redo_stack.clear()
        self._undo_stack.append(cmd)
        logger.debug(f"UndoStack: {self._undo_stack}")
        logger.debug(f"RedoStack: {self._redo_stack}")

    def undo(self) -> None:
        """
        Unwind the undo stack.
        This undoes the action of the command at the back of the undo stack.
        """
        try:
            cmd = self._undo_stack.pop()  # type: IplotCommand
            cmd.undo()
            if cmd.name == 'Zoom' or cmd.name == 'Select':
                self._redo_stack.append(cmd)
            logger.debug(f"Undo {cmd.name}")
            logger.debug(f"UndoStack: {self._undo_stack}")
            logger.debug(f"RedoStack: {self._redo_stack}")
        except (IndexError, AssertionError) as _:
            logger.warning(f"Cannot undo. No more commands.")
            return

    def redo(self) -> None:
        """
        Unwind the redo stack.
        This redoes the action of the command at the back of the redo stack.
        """
        try:
            cmd = self._redo_stack.pop()  # type: IplotCommand
            cmd()
            self._undo_stack.append(cmd)
            logger.debug(f"Redo {cmd.name}")
            logger.debug(f"UndoStack: {self._undo_stack}")
            logger.debug(f"RedoStack: {self._redo_stack}")
        except (IndexError, AssertionError) as _:
            logger.warning(f"Cannot redo. No more commands.")
            return

    def drop(self) -> None:
        """
        Clear history.
        """
        self._undo_stack.clear()
        self._redo_stack.clear()
        logger.debug(f"UndoStack: {self._undo_stack}")
        logger.debug(f"RedoStack: {self._redo_stack}")

    # utilities
    def can_undo(self) -> bool:
        """
        Return True if undo is possible.
        """
        return bool(self._undo_stack)

    def can_redo(self) -> bool:
        """
        Return True if redo is possible.
        """
        return bool(self._redo_stack)

    def get_next_undo_cmd_name(self) -> str:
        """
        Peek at the next undo command name.
        """
        return self._undo_stack[-1].name if self.can_undo() else ''

    def get_next_redo_cmd_name(self) -> str:
        """
        Peek at the next redo command name.
        """
        return self._redo_stack[-1].name if self.can_redo() else ''
