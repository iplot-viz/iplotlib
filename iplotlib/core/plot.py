from abc import ABC
from dataclasses import dataclass
from typing import Dict, List

from iplotlib.core.axis import Axis, LinearAxis
from iplotlib.core.signal import Signal


@dataclass
class Plot(ABC):

    """How many rows of the canvas grid this plot takes. Default: 1"""
    row_span: int = 1


    """How many columns of the canvas grid this plot takes. Default: 1"""
    col_span: int = 1

    """Plot title, should be shown above the plot"""
    title: str = None

    axes: List[Axis] = None
    signals: Dict[str, Signal] = None
    _type: str = None


    font_size: int = None
    font_color: str = None

    """Should the plot legend be included when drawing plot"""
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
class PlotContour(Plot):
    pass


@dataclass
class PlotSurface(Plot):
    pass


@dataclass
class PlotImage(Plot):
    pass


@dataclass
class PlotXY(Plot):

    grid: bool = None

    line_style: str = None
    line_size: int = None
    marker: str = None
    marker_size: int = None
    step: str = None
    """Boolean that suggests the data is sensitive to round off errors and requires special handling"""
    hi_precision_data: bool = None

    dec_samples: int = None

    def __post_init__(self):
        super().__post_init__()
        if self.axes is None:
            self.axes = [LinearAxis(), LinearAxis()]
