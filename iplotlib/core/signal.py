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
    _type: str = None

    def __post_init__(self):
        self._type = self.__class__.__module__ + '.' + self.__class__.__qualname__
        self.signals = {}

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
    color: str = None
    line_style: str = None
    line_size: int = None
    marker: str = None
    marker_size: int = None
    step: str = None
    hi_precision_data: bool = None

    def __post_init__(self):
        super().__post_init__()
        self.data = None

    def get_data(self):
        return self.data

    def set_data(self, data=None):
        self.data = data

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
