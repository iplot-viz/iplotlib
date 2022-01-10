from abc import abstractmethod
from iplotlib.core.command import IplotCommand

class IplotAxesRangeCmd(IplotCommand):
    def __init__(self, old_lim: tuple, new_lim: tuple, axis_id: int) -> None:
        super().__init__(name=f"{hex(axis_id)} {old_lim} -> {new_lim}")
        self.old_lim = old_lim
        self.new_lim = new_lim

    @abstractmethod
    def __call__(self):
        return super().__call__()

    @abstractmethod
    def undo(self):
        return super().undo()
