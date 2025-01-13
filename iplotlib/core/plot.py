"""
This module contains definitions of various kinds of Plot (s)
one might want to use when plotting data.

:data:`~iplotlib.core.plot.PlotXY` is a commonly used concrete class for plotting XY data.
"""

# Changelog:
#   Jan 2023:   -Added legend position and layout properties [Alberto Luengo]

from abc import ABC
from dataclasses import dataclass
from typing import Dict, List, Collection, Union

from iplotlib.core.axis import Axis, LinearAxis
from iplotlib.core.property_manager import PlotContourProp, PlotXYProp, PlotProp
from iplotlib.core.signal import SimpleSignal, SignalXY, SignalContour


@dataclass
class Plot(ABC):
    """
    Main abstraction of a Plot

    Attributes
    ----------
    row_span : int
        nº of rows of canvas grid that this plot will span
    col_span : int
        nº of columns of canvas grid that this plot will span
    title : str
        a plot title text, will be shown above the plot
    axes : List[Union[Axis, List[Axis]]]
        the plot axes
    signals : Dict[int, List[SimpleSignal]]
        the signals drawn in this plot
    background_color : str
        indicate background color of the plot
    legend : bool
        indicate if the plot legend must be shown
    legend_position : str
        indicate the location of the plot legend
    legend_layout : str
        indicate the layout of the plot legend
    grid : bool
        indicate if the grid must be drawn
    log_scale : bool
        A boolean that represents the log scale
    _type : str
        type of the plot
    """

    row_span: int = 1
    col_span: int = 1
    title: str = None
    axes: List[Union[LinearAxis, List[LinearAxis]]] = None
    signals: Dict[int, List[SimpleSignal]] = None
    properties: PlotProp = PlotProp()

    def __post_init__(self):
        self._type = self.__class__.__module__ + '.' + self.__class__.__qualname__
        if self.signals is None:
            self.signals = {}
        if self.axes is None:
            self.axes = [LinearAxis(), [LinearAxis()]]

        self.axes[0].properties.parent = self.properties
        for axe in self.axes[1]:
            axe.properties.parent = self.properties

    def add_signal(self, signal, stack: int = 1):
        signal.properties.parent = self.properties
        if stack not in self.signals:
            self.signals[stack] = []
        self.signals[stack].append(signal)

    def reset_preferences(self):
        self.properties.reset_preferences()

        self.axes[0].reset_preferences()
        for axe in self.axes[1]:
            axe.reset_preferences()

    def merge(self, old_plot: 'Plot'):
        self.title = old_plot.title
        self.properties.merge(old_plot.properties)
        for idxAxis, axis in enumerate(self.axes):
            if axis and idxAxis < len(old_plot.axes):
                # Found matching axes
                if isinstance(axis, Collection) and isinstance(old_plot.axes[idxAxis], Collection):
                    for idxSubAxis, subAxis in enumerate(axis):
                        if subAxis and idxSubAxis < len(old_plot.axes[idxAxis]):
                            old_axis = old_plot.axes[idxAxis][idxSubAxis]
                            subAxis.merge(old_axis)
                else:
                    old_axis = old_plot.axes[idxAxis]
                    axis.merge(old_axis)

        # signals are merged at canvas level to handle move between plots


@dataclass
class PlotContour(Plot):
    """
    A concrete Plot class specialized for contour

    Attributes
    ----------

    """
    signals: Dict[int, List[SignalContour]] = None
    properties: PlotContourProp = PlotContourProp()

    def __post_init__(self):
        super().__post_init__()

    def reset_preferences(self):
        super().reset_preferences()
        self.properties.reset_preferences()

    def merge(self, old_plot: 'PlotContour'):
        super().merge(old_plot)
        self.properties.merge(old_plot.properties)


@dataclass
class PlotXY(Plot):
    """
    A concrete Plot class specialized for 2D plotting

    Attributes
    ----------
    _color_cycle : List[str]
        A list of colors for cycling through plot lines, ensuring variety in signal colors
    _color_index : int
        Current index within the color cycle for assigning a new color
    """

    _color_cycle = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd', '#8c564b', '#e377c2', '#7f7f7f',
                    '#bcbd22', '#17becf', '#ff5733', '#7f00ff', '#33ff57', '#5733ff', '#ff33e6', '#17becf',
                    '#e6ff33', '#8a2be2', '#000080', '#cc6600']
    _color_index: int = 0
    signals: Dict[int, List[SignalXY]] = None
    properties: PlotXYProp = PlotXYProp()

    def __post_init__(self):
        super().__post_init__()

    def add_signal(self, signal, stack: int = 1):
        super().add_signal(signal, stack)
        if signal.properties.color is None:
            signal.properties.color = self.get_next_color()

    def get_next_color(self):
        position = self._color_index % len(self._color_cycle)
        color_signal = self._color_cycle[position]
        self._color_index += 1

        return color_signal

    def reset_preferences(self):
        super().reset_preferences()
        self._color_index = PlotXY._color_index
        self.properties.reset_preferences()

    def merge(self, old_plot: 'PlotXY'):
        super().merge(old_plot)
        self._color_index = old_plot._color_index
        self.properties.merge(old_plot.properties)


@dataclass
class PlotSurface(Plot):
    pass

    def reset_preferences(self):
        super().reset_preferences()

    def merge(self, old_plot: 'PlotSurface'):
        super().merge(old_plot)


@dataclass
class PlotImage(Plot):
    pass

    def reset_preferences(self):
        super().reset_preferences()

    def merge(self, old_plot: 'PlotImage'):
        super().merge(old_plot)
