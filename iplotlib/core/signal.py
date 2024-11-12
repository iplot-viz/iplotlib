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

from iplotlib.interface import IplotSignalAdapter


@dataclass
class Signal(ABC):
    """
    Main abstraction for a Signal.
    """
    uid: str = None  #: Signal uid.
    name: str = ''  #: Signal variable name.
    label: str = None  #: Signal label. This value is presented on plot legend
    color: str = None
    plot_type: str = ''
    _type: str = None

    def __post_init__(self):
        self._type = self.__class__.__module__ + '.' + self.__class__.__qualname__

    @abstractmethod
    def get_data(self) -> tuple:
        pass

    @abstractmethod
    def set_data(self, data=None):
        pass

    def reset_preferences(self):
        self.color = Signal.color

    def merge(self, old_signal: 'Signal'):
        self.color = old_signal.color


@dataclass
class SignalXY(Signal, IplotSignalAdapter):
    """
    SignalXY [...]
    """

    line_style: str = None
    line_size: int = None
    marker: str = None
    marker_size: int = 5
    step: str = None
    plot_type: str = "PlotXY"
    lines = []

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

    # color_map: str = None  - for the moment this property is commented until we realize that it is needed
    levels: int = None  # set the number of levels
    filled: bool = False  # set if the plot is filled or not
    plot_type: str = "PlotContour"

    def __post_init__(self):
        super().__post_init__()
        IplotSignalAdapter.__post_init__(self)

    def get_data(self) -> tuple:
        return IplotSignalAdapter.get_data(self)

    def set_data(self, data=None):
        IplotSignalAdapter.set_data(self, data)


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


@dataclass
class SimpleSignal(ArraySignal):
    """
    A concrete subclass that freezes the data to three numpy arrays (x, y, z).
    You can use this when you have no requirement for custom data-handling.
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
