import collections
from abc import ABC, abstractmethod
from dataclasses import dataclass
from collections import Collection

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

        if isinstance(self.data, Collection) and isinstance(self.data[0], Collection):
            index = np.searchsorted(self.data[0], sample)

            if index == len(self.data[0]):
                index = len(self.data[0]) - 1

            # Either return values at index or values at index-1
            if index > 0 and abs(self.data[0][index - 1] - sample) < abs(self.data[0][index] - sample):
                index = index - 1

            return gather(self.data, index) if index > 0 else None

        return None
