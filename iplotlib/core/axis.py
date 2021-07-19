from abc import ABC
from dataclasses import dataclass


@dataclass
class Axis:
    """Main abstraction of an axis"""

    """Axis label: Should be shown next to an axis"""
    label: str = None
    """Axis font size, applies both for axis label and axis tick labels"""
    font_size: int = None
    """Axis font color, applies both for axis label and axis tick labels"""
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

    """Boolean that suggests that axis should be formatted as date instead of number"""
    is_date: bool = False
    """Implies that instead of using (begin,end) to specify axis range the range is specified by (end-window,end)"""
    window: float = None
    """If true plot 'follows' the data which means it is refreshed when new data arrives and range is automatically changed to show new data"""
    follow: bool = False
