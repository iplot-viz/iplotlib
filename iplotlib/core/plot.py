"""
This module contains definitions of various kinds of Plot (s)
one might want to use when plotting data.

:data:`~iplotlib.core.plot.PlotXY` is a commonly used concrete class for plotting XY data.
"""

from abc import ABC
from dataclasses import dataclass
from typing import Dict, List

from iplotlib.core.axis import Axis, LinearAxis
from iplotlib.core.signal import Signal


@dataclass
class Plot(ABC):
    """
    Main abstraction of a Plot
    """

    row_span: int = 1 #: no. of rows of canvas grid that this plot will span
    col_span: int = 1 #: no. of columns of canvas grid that this plot will span

    title: str = None #: a plot title text, will be shown above the plot

    axes: List[Axis] = None #: the plot axes.
    signals: Dict[str, Signal] = None #: the signals drawn in this plot
    _type: str = None


    font_size: int = None #: the font size of the plot title text
    font_color: str = None #: the font color of the plot title text
    legend: bool = None #: indicate if the plot legend must be shown

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
    """
    Ä concrete Plot class specialized for 2D plottling.
    """
    
    grid: bool = None #: indiacte if the grid must be drawn
    line_style: str = None #: set the line style of all signals.
    line_size: int = None #: set the line size of all signals.
    marker: str = None #: set the marker shape of all signals.
    marker_size: int = None #: set the marker size of all signals.
    step: str = None #: indicate if the step function of the data must be plotted for all signals. Ex: 'steps-post', 'steps-mid', 'steps-pre', 'None'
    hi_precision_data: bool = None #: indicate whether the data is sensitive to round off errors and requires special handling
    dec_samples: int = None #: DEPRECATED No. of samplesfor each signal. Forwarded to data-access module.

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
