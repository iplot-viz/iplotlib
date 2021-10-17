from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Collection
import numpy as np

@dataclass
class SignalStyle(ABC):
    color: str = None


@dataclass
class Signal(ABC):
    """Signal title. This value is presented on plot legend"""
    title: str = None
    color: str = None
    line_style: str = None
    line_size: int = None
    marker: str = None
    marker_size: int = None
    step: str = None
    hi_precision_data: bool = None
    plot_type: str = ''
    _type: str = None

    def __post_init__(self):
        self._type = self.__class__.__module__ + '.' + self.__class__.__qualname__

    @abstractmethod
    def get_data(self):
        pass

    @abstractmethod
    def set_data(self, data=None):
        pass

    @abstractmethod
    def pick(self, sample):
        pass


@dataclass
class ArraySignal(Signal):

    @abstractmethod
    def get_data(self):
        pass

    @abstractmethod
    def set_data(self, data=None):
        pass

    def pick(self, sample):
        def gather(arrs, idx):
            return [arrs[i][idx] if isinstance(arrs[i], Collection) and len(arrs[i]) > idx else None for i in range(len(arrs))]

        try:
            data_arrays = self.get_data()
            x = data_arrays[0]
            if isinstance(x, Collection):
                index = np.searchsorted(x, sample)

                if index == len(x):
                    index = len(x) - 1

                # Either return values at index or values at index-1
                if index > 0 and abs(x[index - 1] - sample) < abs(x[index] - sample):
                    index = index - 1

                return gather(data_arrays, index)
        except:
            pass

        return None


@dataclass
class SimpleSignal(ArraySignal):
    x_data: np.ndarray = np.empty((0))
    y_data: np.ndarray = np.empty((0))
    z_data: np.ndarray = np.empty((0))
    x_unit: str = ''
    y_unit: str = ''
    z_unit: str = ''

    def get_data(self):
        return [self.x_data, self.y_data, self.z_data]

    def set_data(self, data=None):
        try:
            self.x_data = data[0]
            self.y_data = data[1]
            self.z_data = data[2]
        except IndexError:
            return
