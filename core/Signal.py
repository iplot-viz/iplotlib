from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class SignalStyle(ABC):

    color: str = None

@dataclass
class Signal(ABC):

    title: str = None
    _type: str = None

    def __post_init__(self):
        self._type = self.__class__.__module__+'.'+self.__class__.__qualname__
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

    #TODO: Implement for finding the nearest point
    def pick(self, sample):
        return None
