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
class Signal(ABC):
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
    hi_precision_data : bool
        indicate whether the data is sensitive to round off errors and requires special handling. Keep for VTK
    plot_type : str
        indicates the type of plot for the signal
    _type : str
        type of the signal
    lines = []
        collection of line elements associated with the signal
    attrs_propagated : dict
        used for attribute propagation
    """

    plot_type: str = ''
    uid: str = None
    name: str = ''
    label: str = None
    hi_precision_data: bool = None
    lines = []
    _type: str = None

    def __init__(self):
        self.parent = None

    def __post_init__(self):
        self._type = self.__class__.__module__ + '.' + self.__class__.__qualname__

    @abstractmethod
    def get_data(self) -> tuple:
        pass

    @abstractmethod
    def set_data(self, data=None):
        pass

    def reset_preferences(self):
        pass

    def merge(self, old_signal: 'Signal'):
        pass


@dataclass
class SignalXY(Signal, IplotSignalAdapter):
    """
    SignalXY [...]
    """

    plot_type: str = "PlotXY"
    lines = []
    color = HierarchicalProperty('color', default=None)
    line_style = HierarchicalProperty('line_style', default='Solid')
    line_size = HierarchicalProperty('line_size', default=1)
    marker = HierarchicalProperty('marker', default=None)
    marker_size = HierarchicalProperty('marker_size', default=0)
    step = HierarchicalProperty('step', default="linear")

    def __post_init__(self):
        super().__post_init__()
        IplotSignalAdapter.__post_init__(self)

    def get_data(self) -> tuple:
        return IplotSignalAdapter.get_data(self)

    def set_data(self, data=None):
        IplotSignalAdapter.set_data(self, data)

    def reset_preferences(self):
        self.line_style = SignalXY.line_style
        self.line_size = SignalXY.line_size
        self.marker = SignalXY.marker
        self.marker_size = SignalXY.marker_size
        self.step = SignalXY.step
        super().reset_preferences()

    def merge(self, old_signal: 'SignalXY'):
        self.line_style = old_signal.line_style
        self.line_size = old_signal.line_size
        self.marker = old_signal.marker
        self.marker_size = old_signal.marker_size
        self.step = old_signal.step
        super().merge(old_signal)


@dataclass
class SignalContour(Signal, IplotSignalAdapter):
    """
    SignalContour [...]
    """

    plot_type: str = "PlotContour"
    color_map = HierarchicalProperty('color_map', default="viridis")
    contour_levels = HierarchicalProperty('contour_levels', default=10)

    def __post_init__(self):
        super().__post_init__()
        IplotSignalAdapter.__post_init__(self)

    def get_data(self) -> tuple:
        return IplotSignalAdapter.get_data(self)

    def set_data(self, data=None):
        IplotSignalAdapter.set_data(self, data)

    def reset_preferences(self):
        self.color_map = SignalContour.color_map
        self.contour_levels = SignalContour.contour_levels
        super().reset_preferences()

    def merge(self, old_signal: 'SignalContour'):
        self.color_map = old_signal.color_map
        self.contour_levels = old_signal.contour_levels
        super().merge(old_signal)
