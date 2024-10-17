"""
This module contains definitions of various kinds of Axis
one might want to use when plotting data.

The base class :data:`~iplotlib.core.axis.Axis` exposes the basic properties
to adjust font size and color.

:data:`~iplotlib.core.axis.RangeAxis` and :data:`~iplotlib.core.axis.LinearAxis` are specialized concrete
implementations for description of ranges and datetime properties.

"""

from dataclasses import dataclass


@dataclass
class Axis:
    """
    Main abstraction of an axis
    """

    label: str = None  #: a text to be shown next to an axis.
    font_size: int = None  # font size applies both for axis label and axis tick labels.
    font_color: str = '#000000'  # color applies to an axis label and axis tick labels.
    tick_number: int = None  #: number of ticks and labels to be shown in a XAxis
    autoscale: bool = False

    _type: str = None

    def __post_init__(self):
        self._type = self.__class__.__module__ + '.' + self.__class__.__qualname__

    @staticmethod
    def ticks():
        return []

    def reset_preferences(self):
        """
        Reset font size and font color
        """
        self.label = Axis.label
        self.font_size = Axis.font_size
        self.font_color = Axis.font_color
        self.tick_number = Axis.tick_number
        self.autoscale = Axis.autoscale

    def merge(self, old_axis: 'Axis'):
        self.label = old_axis.label
        self.font_size = old_axis.font_size
        self.font_color = old_axis.font_color
        self.tick_number = old_axis.tick_number
        self.autoscale = old_axis.autoscale


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
        elif which == 'original':
            return self.original_begin, self.original_end
        else:
            return None, None

    def set_limits(self, begin, end, which: str = 'current'):
        if which == 'current':
            self.begin = begin
            self.end = end
        elif which == 'original':
            self.original_begin = begin
            self.original_end = end

    def reset_preferences(self):
        """
        Reset begin and end.
        """
        self.begin = RangeAxis.begin
        self.end = RangeAxis.end
        super().reset_preferences()


@dataclass
class LinearAxis(RangeAxis):
    """
    A specialized range axis to deal with date time properties.
    """

    is_date: bool = False  #: suggests that axis should be formatted as date instead of number
    window: float = None  #: Implies that instead of using (begin,end) to specify axis range the range is specified by
    # (end-window,end)
    follow: bool = False  #: If true plot 'follows' the data which means it is refreshed when new data arrives and range
    # is automatically changed to show new data
