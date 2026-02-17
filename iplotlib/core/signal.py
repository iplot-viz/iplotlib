"""
This module contains definitions of various kinds of Signal (s)
one might want to use when plotting data.

:data:`~iplotlib.core.signal.SimpleSignal` is a commonly used concrete class for 
plotting XY or XYZ data.
:data:`~iplotlib.core.signal.ArraySignal` is a commonly used concrete class 
for when you wish to take over the data customization.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List

import numpy as np

from iplotlib.core.marker import Marker
from iplotlib.interface import IplotSignalAdapter


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
    hi_precision_data: bool = False
    lines = []
    _type: str = None
    parent = None
    stack: int = None

    def __post_init__(self):
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
        # keep label for legend plot
        self.label = self.label

    def merge(self, old_signal: dict):
        pass

    def get_id(self):
        return [self.parent().col, self.parent().row, self.stack]

    def get_stack(self) -> str:
        return ".".join(map(str, self.get_id()))


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
    color: str = None
    original_color: str = None
    new_color: bool = False
    line_style: str = None
    line_size: int = None
    marker: str = None
    marker_size: int = None
    step: str = None
    markers_list: List[Marker] = field(default_factory=list)

    def __post_init__(self):
        super().__post_init__()
        IplotSignalAdapter.__post_init__(self)

    def get_data(self) -> tuple:
        return IplotSignalAdapter.get_data(self)

    def set_data(self, data=None):
        IplotSignalAdapter.set_data(self, data)

    def reset_preferences(self):
        super().reset_preferences()
        self.color = SignalXY.color
        self.line_style = SignalXY.line_style
        self.line_size = SignalXY.line_size
        self.marker = SignalXY.marker
        self.marker_size = SignalXY.marker_size
        self.step = SignalXY.step

    def merge(self, old_signal: dict):
        super().merge(old_signal)
        self.new_color = old_signal['new_color']
        if self.new_color:
            self.color = old_signal['color']
            self.original_color = old_signal['original_color']
        self.line_style = old_signal['line_style']
        self.line_size = old_signal['line_size']
        self.marker = old_signal['marker']
        self.marker_size = old_signal['marker_size']
        self.step = old_signal['step']

    def add_marker(self, marker: Marker):
        self.markers_list.append(marker)

    def delete_marker(self, index):
        self.markers_list.pop(index)

    def set_limits(self, ranges):
        if self.x_expr != '${self}.time' and len(self.data_store[0]) > 0 and len(self.x_data) > 0:
            # Make sure that the x_data array is filter and sorted
            x_data = self.x_data[~np.isnan(self.x_data)]
            x_data_sorted = np.sort(x_data)

            idx1 = np.searchsorted(x_data_sorted, ranges[0])
            idx2 = np.searchsorted(x_data_sorted, ranges[1])

            if idx1 != 0:
                idx1 -= 1
            if idx2 != len(self.x_data):
                idx2 += 1

            signal_begin = self.data_store[0][idx1:idx2][0]
            signal_end = self.data_store[0][idx1:idx2][-1]

            self.set_xranges([signal_begin, signal_end])
        else:
            self.set_xranges(ranges)


@dataclass
class SignalContour(Signal, IplotSignalAdapter):
    """
    SignalContour [...]
    color_map : str
        signal contour color map
    contour_levels : int
         number of levels
    """
    color_map: str = None
    contour_levels: int = None

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

    def merge(self, old_signal: dict):
        super().merge(old_signal)
        self.color_map = old_signal['color_map']
        self.contour_levels = old_signal['contour_levels']
