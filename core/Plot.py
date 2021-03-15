from abc import ABC
from dataclasses import dataclass
from typing import Dict, List

from iplotlib.core.Axis import Axis, LinearAxis
from iplotlib.core.Signal import Signal

"""
A plot is assumed to be a container for set of axes.
Plot can also contain multiple signals
"""

@dataclass
class Plot(ABC):

    title: str = None
    grid: bool = None
    axes: List[Axis] = None
    signals: Dict[str, Signal] = None
    _type: str = None

    font_size: int = None
    font_color: str = None

    line_style: str = None
    line_size: int = None
    marker: str = None
    marker_size: int = None
    step: str = None


    dec_samples: int = None
    legend: bool = None

    def __post_init__(self):
        self._type = self.__class__.__module__+'.'+self.__class__.__qualname__
        if self.signals is None:
            self.signals = {}

    def add_signal(self, signal, stack: int = 1):
        if str(stack) not in self.signals:
            self.signals[str(stack)] = []
        self.signals[str(stack)].append(signal)


@dataclass
class Plot2D(Plot):

    row_span: int = 1
    col_span: int = 1

    def __post_init__(self):
        super().__post_init__()
        if self.axes is None:
            self.axes = [LinearAxis(), LinearAxis()]
