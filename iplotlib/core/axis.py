# Copyright (c) 2020-2025 ITER Organization,
#               CS 90046
#               13067 St Paul Lez Durance Cedex
#               France
# Author IO
#
# This file is part of iplotlib module.
# iplotlib python module is free software: you can redistribute it and/or modify it under
# the terms of the MIT license.
#
# This file is part of ITER CODAC software.
# For the terms and conditions of redistribution or use of this software
# refer to the file LICENSE located in the top level directory
# of the distribution package
#


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

    Attributes
    ----------
    _type : str
        type of the axis
    label : str
        a text to be shown next to an axis
    font_size : int
        font size applies both for axis label and axis tick labels
    font_color : str
        color applies to an axis label and axis tick labels
    tick_number : int
        number of ticks and labels to be shown in the axis
    """

    _type: str = None
    label: str = None
    font_size: int = None
    font_color: str = None
    tick_number: int = None
    parent = None

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

    def merge(self, old_axis: 'Axis'):
        self.label = old_axis.label
        self.font_size = old_axis.font_size
        self.font_color = old_axis.font_color
        self.tick_number = old_axis.tick_number


@dataclass
class RangeAxis(Axis):
    """
    Expose `begin`, `end` properties of an axis.

    Attributes
    ----------
    original_begin : any
        The initial starting value of the axis range
    original_end : any
        The initial ending value of the axis range
    begin : any
        The current starting value of the axis range, can be adjusted dynamically if the axis is not autoscaled
    end : any
        The current ending value of the axis range, can be adjusted dynamically if the axis is not autoscaled
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
        super().reset_preferences()


@dataclass
class LinearAxis(RangeAxis):
    """
    A specialized range axis to deal with date time properties

    Attributes
    ----------
    is_date : bool
        suggests that axis should be formatted as date instead of number
    window : float
        Implies that instead of using (begin,end) to specify axis range the range is specified by (end-window,end)
    follow : bool
        If true plot 'follows' the data which means it is refreshed when new data arrives and range is automatically
        changed to show new data
    """

    is_date: bool = False
    window: float = None
    follow: bool = False

    def __post_init__(self):
        super().__post_init__()
        self.parent = None
