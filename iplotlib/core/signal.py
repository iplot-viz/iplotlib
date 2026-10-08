"""
This module contains definitions of various kinds of Signal (s)
one might want to use when plotting data.

:data:`~iplotlib.core.signal.SimpleSignal` is a commonly used concrete class for 
plotting XY or XYZ data.
:data:`~iplotlib.core.signal.ArraySignal` is a commonly used concrete class 
for when you wish to take over the data customization.
"""

import numbers
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
        if self._x_maps_samples_to_time():
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
            signal_begin, signal_end = self._extend_beyond_samples(ranges, signal_begin, signal_end)

            if self._is_requested_window(signal_begin, signal_end):
                return
            self.set_xranges([signal_begin, signal_end])
        else:
            self.set_xranges(ranges)

    def restore_xranges(self, ranges):
        """Restore a recorded request window.

        Restoring a view already re-derived the window of an X expression from
        its samples; when both name the same request, keeping it avoids fetching
        the same data twice.
        """
        if self._x_maps_samples_to_time() and self._is_requested_window(*ranges):
            return
        self.set_xranges(ranges)

    def _x_maps_samples_to_time(self):
        """Whether X is an expression evaluated sample by sample over the time
        buffer. Sparse x_data (e.g. [time[0], time[-1]]) does not map back to time."""
        return (self.x_expr != '${self}.time'
                and len(self.data_store[0]) > 0
                and len(self.x_data) == len(self.data_store[0]))

    def _extend_beyond_samples(self, ranges, begin, end):
        """Extend [begin, end] where the X range reaches past the samples in memory.

        Snapping only selects samples already loaded, so a wider view (zoom out,
        undo, pan) could never bring the rest back. Along a strictly increasing X
        the window follows the slope of the edge segment, bounded by what was
        drawn at first so a shallow edge cannot blow up the request.
        """
        bounds = self.draw_time_bounds()
        if bounds is None:
            return begin, end
        x = np.asarray(self.x_data, dtype=float)
        if x.size < 2 or not np.all(np.isfinite(x)) or not np.all(np.diff(x) > 0):
            return begin, end

        time = self.data_store[0]
        exact = np.issubdtype(np.asarray(time).dtype, np.integer)
        cast = int if exact else float

        def along_edge(edge, inner, x_target):
            slope = (cast(time[edge]) - cast(time[inner])) / (x[edge] - x[inner])
            shift = (float(x_target) - x[edge]) * slope
            # Nanosecond timestamps exceed what a float holds exactly.
            return cast(time[edge]) + (int(round(shift)) if exact else shift)

        lower, upper = cast(bounds[0]), cast(bounds[1])
        if ranges[0] < x[0]:
            begin = min(max(along_edge(0, 1, ranges[0]), lower), cast(time[0]))
        if ranges[1] > x[-1]:
            end = max(min(along_edge(-1, -2, ranges[1]), upper), cast(time[-1]))
        return begin, end

    def _is_requested_window(self, begin, end):
        """Whether [begin, end] is the window already requested, up to the
        sampling step at each edge: the data server returns the samples inside
        the window, so the first and last ones lie less than a step within it."""
        time = self.data_store[0]
        candidate = self._numeric_window(begin, end)
        requested = self._numeric_window(self.ts_start, self.ts_end)
        if len(time) < 2 or candidate is None or requested is None:
            return False

        cast = int if np.issubdtype(np.asarray(time).dtype, np.integer) else float
        first_step = abs(cast(time[1]) - cast(time[0]))
        last_step = abs(cast(time[-1]) - cast(time[-2]))
        return (abs(cast(candidate[0]) - cast(requested[0])) <= first_step
                and abs(cast(candidate[1]) - cast(requested[1])) <= last_step)

    def _numeric_window(self, begin, end):
        """(begin, end) as numbers, or None. A request without bounds (a whole
        pulse) spans what was drawn."""
        if begin == '' and end == '':
            return self.draw_time_bounds()
        if all(isinstance(value, numbers.Real) for value in (begin, end)):
            return begin, end
        return None


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
