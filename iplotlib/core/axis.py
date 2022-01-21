"""
This module contains definitions of various kinds of Axis
one might want to use when plotting data.

The base class :data:`~iplotlib.core.axis.Axis` exposes the basic properties
to adjust font size and color.

:data:`~iplotlib.core.axis.RangeAxis` and :data:`~iplotlib.core.axis.LinearAxis`  are specialized concrete implementations
for description of ranges and datetime properties.

"""

from dataclasses import dataclass

@dataclass
class Axis:
    """
    Main abstraction of an axis
    """

    label: str = None #: a text to be shown next to an axis.
    font_size: int = None #: font size applies both for axis label and axis tick labels.
    font_color: str = None #: color applies to an axis label and axis tick labels.

    _type: str = None

    def __post_init__(self):
        self._type = self.__class__.__module__+'.'+self.__class__.__qualname__

    def ticks(self, num: int):
        return []
    
    def reset_preferences(self):
        """
        Reset font size and font color
        """
        self.font_size = Axis.font_size
        self.font_color = Axis.font_color


@dataclass
class RangeAxis(Axis):
    """
    Expose `begin`, `end` properties of an axis.
    """
    original_begin: any = None
    original_end: any = None
    begin: any = None
    end: any = None

    def get_limits(self, which: str = 'current') -> tuple:
        """
        Return the limits of this axis.

        :param which: Either original or current, defaults to 'current'
        :type which: str, optional
        :return: (begin, end)
        :rtype: tuple
        """
        if which == 'current':
            return self.begin, self.end
        else: # which == 'original'
            return self.original_begin, self.original_end

    def reset_preferences(self):
        """
        Reset begin and end.
        """
        self.begin = RangeAxis.begin
        self.end = RangeAxis.end
        return super().reset_preferences()


@dataclass
class LinearAxis(RangeAxis):
    """
    A specialized range axis to deal with date time properties.
    """

    is_date: bool = False #: suggests that axis should be formatted as date instead of number
    window: float = None #: Implies that instead of using (begin,end) to specify axis range the range is specified by (end-window,end)
    follow: bool = False #: If true plot 'follows' the data which means it is refreshed when new data arrives and range is automatically changed to show new data
