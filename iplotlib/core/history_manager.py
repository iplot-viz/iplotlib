from iplotlib.core.command import IplotCommand
import iplotLogging.setupLogger as ls
logger = ls.get_logger(__name__, 'DEBUG')

class HistoryManager:
    def __init__(self) -> None:
        self.iplot_commands = []
        self._location = -1 # index points to the next command in iplot_commands

    def do_command(self, cmd: IplotCommand):
        self.iplot_commands.append(cmd)
        self._location = len(self.iplot_commands) - 1

    def undo(self) -> None:
        try:
            cmd = self.iplot_commands[self._location] # type: IplotCommand
            assert callable(cmd)
            cmd()
            self._location -= 1
            logger.debug(f"Undo {cmd.name}")
        except (IndexError, AssertionError) as _:
            logger.debug(f"Cannot undo. No more commands.")
            return

    def redo(self) -> None:
        try:
            cmd = self.iplot_commands[self._location + 1]
            assert callable(cmd)
            self._location += 1
            logger.debug(f"Redo {cmd.name}")
        except (IndexError, AssertionError) as _:
            logger.debug(f"Cannot redo. No more commands.")
            return

    def drop(self) -> None:
        self.iplot_commands.clear()
        self._location = -1

# Ex: For the following sequence..
# 0. Zoom -1, 1 
# 1. Pan -3, 3
# 2. Zoom -2, 2

# Hit undo
# _location is 2. Will undo command with id 2. the zoom will be undone. _location is decremented.
# Hit redo
# _location is 1. Will redo command with id _location + 1 = 2. the zoom will be redone. _location is incremented.
# Hit redo
# _location is 2. IndexError is raised, so cannot redo.

