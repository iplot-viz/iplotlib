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
from typing import Collection, List
import numpy as np

from iplotlib.core.hierarchical_property import HierarchicalProperty


@dataclass
class SignalStyle(ABC):
    color: str = None


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

    color = HierarchicalProperty('color', default=None)
    line_style = HierarchicalProperty('line_style', default='Solid')
    line_size = HierarchicalProperty('line_size', default=1)
    marker = HierarchicalProperty('marker', default=None)
    marker_size = HierarchicalProperty('marker_size', default=0)
    step = HierarchicalProperty('step', default="linear")

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

    @abstractmethod
    def pick(self, sample):
        pass

    def reset_preferences(self):
        self.color = Signal.color
        self.line_style = Signal.line_style
        self.line_size = Signal.line_size
        self.marker = Signal.marker
        self.marker_size = Signal.marker_size
        self.step = Signal.step

    def merge(self, old_signal: 'Signal'):
        self.color = old_signal.color
        self.line_style = old_signal.line_style
        self.line_size = old_signal.line_size
        self.marker = old_signal.marker
        self.marker_size = old_signal.marker_size
        self.step = old_signal.step


@dataclass
class ArraySignal(Signal):
    """
    A concrete subclass to permit implementors to write their own get/set data functions.
    This class implements a generic `pick` function to select data from a sample value.
    """

    @abstractmethod
    def get_data(self) -> tuple:
        pass

    @abstractmethod
    def set_data(self, data=None):
        pass

    def pick(self, sample):
        def gather(arrs, idx):
            return [arrs[i][idx] if isinstance(arrs[i], Collection) and len(arrs[i]) > idx else None for i in
                    range(len(arrs))]

        try:
            data_arrays = self.get_data()
            if len(data_arrays) >= 2:
                data_arrays = data_arrays[:2]
            x = data_arrays[0]

            if not isinstance(x, List):
                x = list(x)

            index = np.searchsorted(x, sample)
            if index == len(x):
                index = len(x) - 1

            # Either return values at index or values at index-1
            if index > 0 and abs(x[index - 1] - sample) < abs(x[index] - sample):
                index = index - 1

            return gather(data_arrays, index)
        except Exception as e:
            print(f"Error : {e}")
            pass

        return None


@dataclass
class SimpleSignal(ArraySignal):
    """
    A concrete subclass that freezes the data to three numpy arrays (x, y, z).
    You can use this when you have no requirement for custom data-handling.

    Attributes
    ----------
    x_data : np.ndarray
        array containing x-axis data points
    y_data : np.ndarray
        array containing y-axis data points
    z_data : np.ndarray
        array containing z-axis data points
    x_unit : str
        unit of measurement for x-axis data
    y_unit : str
        unit of measurement for y-axis data
    z_unit : str
        unit of measurement for z-axis data
    """

    x_data: np.ndarray = field(default_factory=lambda: np.empty(0))
    y_data: np.ndarray = field(default_factory=lambda: np.empty(0))
    z_data: np.ndarray = field(default_factory=lambda: np.empty(0))
    x_unit: str = ''
    y_unit: str = ''
    z_unit: str = ''

    def get_data(self) -> List[np.ndarray]:
        return [self.x_data, self.y_data, self.z_data]

    def set_data(self, data=None):
        try:
            self.x_data = data[0]
            self.y_data = data[1]
            self.z_data = data[2]
        except (IndexError, TypeError) as _:
            return
