from abc import abstractmethod
from collections import namedtuple
from iplotlib.core.command import IplotCommand
from iplotlib.core.plot import Plot

XYLimits = namedtuple('XYLimits', ['xmin', 'xmax', 'ymin', 'ymax'])

class IplotAxesRangeCmd(IplotCommand):
    def __init__(self, name: str, old_lim: XYLimits, new_lim: XYLimits, plot: Plot) -> None:
        super().__init__(name)
        self.old_lim = old_lim
        self.new_lim = new_lim
        self.plot = plot

    @abstractmethod
    def __call__(self):
        return super().__call__()

    @abstractmethod
    def undo(self):
        return super().undo()

    def __str__(self):
        return f"{self.__class__.__name__}({hex(id(self))}) {self.name}"
