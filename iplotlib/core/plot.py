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

    def reset_preferences(self):
        self.legend = Plot.legend
        self.font_size = Plot.font_size
        self.font_color = Plot.font_color


@dataclass
class PlotContour(Plot):
    pass

    def reset_preferences(self):
        super().reset_preferences()


@dataclass
class PlotSurface(Plot):
    pass

    def reset_preferences(self):
        super().reset_preferences()


@dataclass
class PlotImage(Plot):
    pass

    def reset_preferences(self):
        super().reset_preferences()


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

    def reset_preferences(self):
        self.grid = PlotXY.grid
        self.line_style = PlotXY.line_style
        self.line_size = PlotXY.line_size
        self.marker = PlotXY.marker
        self.marker_size = PlotXY.marker_size
        self.step = PlotXY.step
        return super().reset_preferences()
