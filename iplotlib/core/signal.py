"""
This module contains definitions of various kinds of Signal (s)
one might want to use when plotting data.

:data:`~iplotlib.core.signal.SimpleSignal` is a commonly used concrete class for 
plotting XY or XYZ data.
:data:`~iplotlib.core.signal.ArraySignal` is a commonly used concrete class 
for when you wish to take over the data customization.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass

from iplotlib.interface import IplotSignalAdapter

from iplotlib.core.hierarchical_property import HierarchicalProperty


@dataclass
class Signal(ABC, IplotSignalAdapter):
    """
    Main abstraction for a Signal

    Attributes
    ----------
    uid : str
        Signal uid
    name : str
        Signal variable name
    label : str
        Signal label. This value is presented on plot legend
    hi_precision_data : bool
        indicate whether the data is sensitive to round off errors and requires special handling. Keep for VTK
    _type : str
        type of the signal
    lines = []
        collection of line elements associated with the signal
    """
    uid: str = None
    name: str = ''
    label: str = None
    hi_precision_data: bool = None  # TODO review this utility
    lines = []
    _type: str = None

    def __post_init__(self):
        super().__post_init__()
        self._type = self.__class__.__module__ + '.' + self.__class__.__qualname__
        self.parent = None

    @abstractmethod
    def get_data(self) -> tuple:
        pass

    @abstractmethod
    def set_data(self, data=None):
        pass

    def get_style(self):
        pass

    def reset_preferences(self):
        self.label = Signal.label

    def merge(self, old_signal: 'Signal'):
        self.label = old_signal.label


@dataclass
class SignalXY(Signal, IplotSignalAdapter):
    """
    SignalXY [...]
    color : str
        signal color
    line_style : str
        Style of the line used for plotting. Supported types: 'Solid', 'Dashed', 'Dotted'
    line_size : int
        Thickness of the signal line
    marker : str
        default marker type to display. If set a marker is drawn at every point of the data sample. Markers and lines
        can be drawn together and are not mutually exclusive. Supported types: 'x','o', None, default: None
        (no markers are drawn)
    marker_size : int
        default marker size. Whether it is mapped to pixels or DPI independent points should be canvas implementation
        dependent
    step : str
        default line style - 'post', 'mid', 'pre', 'None', defaults to 'None'.
    """
    lines = []
    color: HierarchicalProperty = HierarchicalProperty('color', default=None)
    line_style: HierarchicalProperty = HierarchicalProperty('line_style', default='Solid')
    line_size: HierarchicalProperty = HierarchicalProperty('line_size', default=1)
    marker: HierarchicalProperty = HierarchicalProperty('marker', default=None)
    marker_size: HierarchicalProperty = HierarchicalProperty('marker_size', default=1)
    step: HierarchicalProperty = HierarchicalProperty('step', default="default")

    def __post_init__(self):
        super().__post_init__()
        IplotSignalAdapter.__post_init__(self)

    def get_data(self) -> tuple:
        return IplotSignalAdapter.get_data(self)

    def set_data(self, data=None):
        IplotSignalAdapter.set_data(self, data)

    def get_style(self):
        style = dict()

        style['label'] = self.label
        style['color'] = self.color

        style['linewidth'] = self.line_size
        style['linestyle'] = self.line_style.lower()
        style['marker'] = self.marker
        style['markersize'] = self.marker_size
        style["drawstyle"] = self.step

        return style

    def reset_preferences(self):
        super().reset_preferences()
        self.color = SignalXY.color
        self.line_style = SignalXY.line_style
        self.line_size = SignalXY.line_size
        self.marker = SignalXY.marker
        self.marker_size = SignalXY.marker_size
        self.step = SignalXY.step

    def merge(self, old_signal: 'SignalXY'):
        super().merge(old_signal)
        self.color = getattr(old_signal, "_color", None)
        self.line_style = getattr(old_signal, "_line_style", None)
        self.line_size = getattr(old_signal, "_line_size", None)
        self.marker = getattr(old_signal, "_marker", None)
        self.marker_size = getattr(old_signal, "_marker_size", None)
        self.step = getattr(old_signal, "_step", None)


@dataclass
class SignalContour(Signal, IplotSignalAdapter):
    """
    SignalContour [...]
    """
    color_map: HierarchicalProperty = HierarchicalProperty('color_map', default="viridis")
    contour_levels: HierarchicalProperty = HierarchicalProperty('contour_levels', default=10)

    def __post_init__(self):
        super().__post_init__()
        IplotSignalAdapter.__post_init__(self)

    def get_data(self) -> tuple:
        return IplotSignalAdapter.get_data(self)

    def set_data(self, data=None):
        IplotSignalAdapter.set_data(self, data)

    def reset_preferences(self):
        super().reset_preferences()
        self.color_map = SignalContour.color_map
        self.contour_levels = SignalContour.contour_levels

    def merge(self, old_signal: 'SignalContour'):
        super().merge(old_signal)
        self.color_map = getattr(old_signal, "_color_map", None)
        self.contour_levels = getattr(old_signal, "_contour_levels", None)
