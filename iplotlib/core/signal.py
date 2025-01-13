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

from iplotlib.core.property_manager import SignalContourProp, SignalXYProp
from iplotlib.interface import IplotSignalAdapter


@dataclass
class SimpleSignal(ABC, IplotSignalAdapter):
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
    hi_precision_data: bool = None
    lines = []
    _type: str = None

    def __post_init__(self):
        super().__post_init__()
        self._type = self.__class__.__module__ + '.' + self.__class__.__qualname__

    @abstractmethod
    def get_data(self) -> tuple:
        pass

    @abstractmethod
    def set_data(self, data=None):
        pass

    def get_style(self):
        pass

    def reset_preferences(self):
        self.label = SimpleSignal.label

    def merge(self, old_signal: 'SimpleSignal'):
        self.label = old_signal.label


@dataclass
class SignalXY(SimpleSignal, IplotSignalAdapter):
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
    properties: SignalXYProp = SignalXYProp()

    def __post_init__(self):
        super().__post_init__()
        IplotSignalAdapter.__post_init__(self)

    def get_data(self) -> tuple:
        return IplotSignalAdapter.get_data(self)

    def set_data(self, data=None):
        IplotSignalAdapter.set_data(self, data)

    def reset_preferences(self):
        super().reset_preferences()
        self.properties.reset_preferences()

    def merge(self, old_signal: 'SignalXY'):
        super().merge(old_signal)
        self.properties.merge(old_signal.properties)


@dataclass
class SignalContour(SimpleSignal, IplotSignalAdapter):
    """
    SignalContour [...]
    color_map : str
        signal contour color map
    contour_levels : int
         number of levels
    """
    properties: SignalContourProp = SignalContourProp()

    def __post_init__(self):
        super().__post_init__()
        IplotSignalAdapter.__post_init__(self)

    def get_data(self) -> tuple:
        return IplotSignalAdapter.get_data(self)

    def set_data(self, data=None):
        IplotSignalAdapter.set_data(self, data)

    def reset_preferences(self):
        super().reset_preferences()
        self.properties.reset_preferences()

    def merge(self, old_signal: 'SignalContour'):
        super().merge(old_signal)
        self.properties.merge(old_signal.properties)
