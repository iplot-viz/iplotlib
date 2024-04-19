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
from typing import Collection, List
import numpy as np


@dataclass
class SignalStyle(ABC):
    color: str = None


@dataclass
class Signal(ABC):
    """
    Main abstraction for a Signal.
    """
    uid: str = None  #: Signal uid.
    name: str = ''  #: Signal variable name.
    label: str = None  #: Signal label. This value is presented on plot legend
    color: str = None
    line_style: str = None
    line_size: int = None
    marker: str = None
    marker_size: int = None
    step: str = None
    hi_precision_data: bool = None
    plot_type: str = ''
    _type: str = None
    lines = []

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
    """
    x_data: np.ndarray = np.empty(0)
    y_data: np.ndarray = np.empty(0)
    z_data: np.ndarray = np.empty(0)
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
