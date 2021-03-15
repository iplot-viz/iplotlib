from abc import ABC
from dataclasses import dataclass

"""
Main abstraction of an axis
"""


@dataclass
class Axis:

    label: str = None
    font_size: int = None
    font_color: str = None

    _type: str = None


    def __post_init__(self):
        self._type = self.__class__.__module__+'.'+self.__class__.__qualname__

    def ticks(self, num: int):
        return []


@dataclass
class RangeAxis(Axis):

    begin: any = None
    end: any = None




@dataclass
class LinearAxis(RangeAxis):

    is_date: bool = False
    window: float = None
    follow: bool = False

