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
    
    def reset_preferences(self):
        self.font_size = Axis.font_size
        self.font_color = Axis.font_color


@dataclass
class RangeAxis(Axis):

    original_begin: any = None
    original_end: any = None
    begin: any = None
    end: any = None

    def get_limits(self, which: str = 'current') -> tuple:
        if which == 'current':
            return self.begin, self.end
        else: # which == 'original'
            return self.original_begin, self.original_end

    def reset_preferences(self):
        self.begin = RangeAxis.begin
        self.end = RangeAxis.end
        return super().reset_preferences()


@dataclass
class LinearAxis(RangeAxis):

    """Boolean that suggests that axis should be formatted as date instead of number"""
    is_date: bool = False
    """Implies that instead of using (begin,end) to specify axis range the range is specified by (end-window,end)"""
    window: float = None
    """If true plot 'follows' the data which means it is refreshed when new data arrives and range is automatically changed to show new data"""
    follow: bool = False
