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
from iplotlib.core.signal import Signal
from iplotlib.core.hierarchical_property import HierarchicalProperty


@dataclass
class Plot(ABC):
    """
    Main abstraction of a Plot

    Attributes
    ----------
    row_span : int
        nº of rows of canvas grid that this plot will span '!"·
    col_span : int
        nº of columns of canvas grid that this plot will span
    title : str
        a plot title text, will be shown above the plot
    axes : List[Union[Axis, List[Axis]]]
        the plot axes
    signals : Dict[int, List[Signal]]
        the signals drawn in this plot
    background_color : str
        indicate background color of the plot
    legend : bool
        indicate if the plot legend must be shown
    legend_position : str
        indicate the location of the plot legend
    legend_layout : str
        indicate the layout of the plot legend
    _type : str
        type of the plot
    """

    row_span: int = 1
    col_span: int = 1
    title: str = None
    axes: List[Union[Axis, List[Axis]]] = None
    signals: Dict[int, List[Signal]] = None
    background_color = HierarchicalProperty('background_color', default='#FFFFFF')
    legend = HierarchicalProperty('legend', default=True)
    legend_position = HierarchicalProperty('legend_position', default='upper right')
    legend_layout = HierarchicalProperty('legend_layout', default='vertical')
    _type: str = None

    def __post_init__(self):
        self._type = self.__class__.__module__ + '.' + self.__class__.__qualname__
        if self.signals is None:
            self.signals = {}

    def add_signal(self, signal, stack: int = 1):
        signal.parent = self
        if stack not in self.signals:
            self.signals[stack] = []
        self.signals[stack].append(signal)

    def reset_preferences(self):
        self.legend = Plot.legend
        self.legend_position = Plot.legend_position
        self.legend_layout = Plot.legend_layout
        self.background_color = Plot.background_color

    def merge(self, old_plot: 'Plot'):
        self.title = old_plot.title
        self.legend = old_plot.legend
        self.legend_position = old_plot.legend_position
        self.legend_layout = old_plot.legend_layout
        self.background_color = old_plot.background_color

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
    pass

    def reset_preferences(self):
        super().reset_preferences()

    def merge(self, old_plot: 'PlotContour'):
        super().merge(old_plot)


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


@dataclass
class PlotXY(Plot):
    """
    A concrete Plot class specialized for 2D plotting

    Attributes
    ----------
    log_scale : bool
        A boolean that represents the log scale
    grid : bool
        indicate if the grid must be drawn
    _color_cycle : List[str]
        A list of colors for cycling through plot lines, ensuring variety in signal colors
    _color_index : int
        Current index within the color cycle for assigning a new color
    """

    _color_cycle = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd', '#8c564b', '#e377c2', '#7f7f7f',
                    '#bcbd22', '#17becf', '#ff5733', '#7f00ff', '#33ff57', '#5733ff', '#ff33e6', '#17becf',
                    '#e6ff33', '#8a2be2', '#000080', '#cc6600']
    _color_index: int = 0
    axes: List[Union[Axis, List[Axis]]] = None

    log_scale = HierarchicalProperty('log_scale', default=False)
    grid = HierarchicalProperty('grid', default=True)

    # Axis
    label = HierarchicalProperty('label', default=None)
    font_size = HierarchicalProperty('font_size', default=10)
    font_color = HierarchicalProperty('font_color', default='#000000')
    tick_number = HierarchicalProperty('tick_number', default=7)
    autoscale = HierarchicalProperty('autoscale', default=True)

    # SignalXY
    color = HierarchicalProperty('color', default=None)
    line_style = HierarchicalProperty('line_style', default='Solid')
    line_size = HierarchicalProperty('line_size', default=1)
    marker = HierarchicalProperty('marker', default=None)
    marker_size = HierarchicalProperty('marker_size', default=0)
    step = HierarchicalProperty('step', default="linear")

    def __post_init__(self):
        super().__post_init__()
        if self.axes is None:
            self.axes = [LinearAxis(), [LinearAxis()]]

        # ~TODO change
        self.axes[0].parent = self
        for axe in self.axes[1]:
            axe.parent = self

    def get_next_color(self):
        position = self._color_index % len(self._color_cycle)
        color_signal = self._color_cycle[position]
        self._color_index += 1

        return color_signal

    def reset_preferences(self):
        self.log_scale = PlotXY.log_scale
        self.grid = PlotXY.grid
        super().reset_preferences()

    def merge(self, old_plot: 'PlotXY'):
        self.log_scale = old_plot.log_scale
        self.grid = old_plot.grid
        self._color_index = old_plot._color_index
        super().merge(old_plot)
