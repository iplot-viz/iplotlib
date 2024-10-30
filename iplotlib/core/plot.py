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
from iplotlib.core.signal import Signal, SimpleSignal


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
    background_color: str = '#FFFFFF'
    legend: bool = True
    legend_position: str = 'upper right'
    legend_layout: str = 'vertical'
    _type: str = None

    def __post_init__(self):
        self._type = self.__class__.__module__ + '.' + self.__class__.__qualname__
        if self.signals is None:
            self.signals = {}

    def add_signal(self, signal, stack: int = 1):
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
    attrs_propagated : dict
        contains all hierarchical attributes, combining signal and axis properties
    _attribute_hierarchy_signal : dict
        inherited attributes specific to signal properties
    _attribute_hierarchy_axis : dict
        inherited attributes specific to axis properties
    """

    log_scale: bool = False
    grid: bool = True
    _color_cycle = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd', '#8c564b', '#e377c2', '#7f7f7f',
                    '#bcbd22', '#17becf', '#ff5733', '#7f00ff', '#33ff57', '#5733ff', '#ff33e6', '#17becf',
                    '#e6ff33', '#8a2be2', '#000080', '#cc6600']
    _color_index: int = 0
    attrs_propagated = None
    _attribute_hierarchy_signal = SimpleSignal().attrs_propagated
    _attribute_hierarchy_axis = LinearAxis().attrs_propagated

    def __new__(cls, *args, **kwargs):
        instance = super().__new__(cls)
        instance.__dict__.update(cls._attribute_hierarchy_signal)
        instance.__dict__.update(cls._attribute_hierarchy_axis)
        return instance

    def __post_init__(self):
        super().__post_init__()
        if self.axes is None:
            self.axes = [LinearAxis(), [LinearAxis()]]

        combined_attrs = {**vars(super(type(self), self)), **self.__dict__}

        self.attrs_propagated = {k: v for k, v in combined_attrs.items() if
                                 k in ["background_color", "legend", "legend_position", "legend_layout", "log_scale",
                                       "grid"]}
        self.attrs_propagated.update(self._attribute_hierarchy_signal)
        self.attrs_propagated.update(self._attribute_hierarchy_axis)

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
        for attr in self.attrs_propagated.keys():
            super().__setattr__(attr, getattr(old_plot, attr))
        self.log_scale = old_plot.log_scale
        self.grid = old_plot.grid
        self._color_index = old_plot._color_index
        super().merge(old_plot)

    def __setattr__(self, key, value):
        super().__setattr__(key, value)
        if key in self._attribute_hierarchy_signal.keys() and self.signals:
            for signal_list in self.signals.values():
                for signal in signal_list:
                    setattr(signal, key, value)
        elif key in self._attribute_hierarchy_axis.keys() and self.axes:
            for idxAxis, axis in enumerate(self.axes):
                if isinstance(axis, Collection):
                    for idxSubAxis, subAxis in enumerate(axis):
                        setattr(subAxis, key, value)
                else:
                    setattr(axis, key, value)
