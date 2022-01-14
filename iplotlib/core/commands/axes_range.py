from typing import List
from iplotlib.core.command import IplotCommand
from iplotlib.core.impl_base import BackendParserBase
from iplotlib.core.limits import IplPlotViewLimits

class IplotAxesRangeCmd(IplotCommand):
    def __init__(self, name: str, old_limits: List[IplPlotViewLimits], new_limits: List[IplPlotViewLimits] = [], parser: BackendParserBase=None) -> None:
        super().__init__(name)
        self.old_lim = old_limits
        self.new_lim = new_limits
        self._parser = parser

    def __call__(self):
        super().__call__()
        for limits in self.new_lim:
            self._parser.set_plot_limits(limits)

    def undo(self):
        super().undo()
        for limits in self.old_lim:
            self._parser.set_plot_limits(limits)

    def __str__(self):
        return f"{self.__class__.__name__}({hex(id(self))}) {self.name}"
