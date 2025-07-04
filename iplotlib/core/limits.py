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
Helper classes to store and transmit the ranges of an axis and the plot view limits.
"""

from dataclasses import dataclass, field
from typing import List, Any
from weakref import ref


@dataclass
class IplSignalLimits:
    """
    A container for a signal and its range.
    """
    begin: Any = None  #: the beginning value.
    end: Any = None  #: the end value.
    signal_ref: ref = None  #: a weak reference to the core iplotlib signal object.

    def get_limits(self):
        return self.begin, self.end

    def set_limits(self, begin, end):
        self.begin = begin
        self.end = end


@dataclass
class IplAxisLimits:
    """
    A container for an axis and its range.
    """
    begin: Any = None  #: the begin value.
    end: Any = None  #: the end value.
    axes_ref: ref = None  #: a weak reference to the core iplotlib axis object.

    def get_limits(self):
        return self.begin, self.end

    def set_limits(self, begin, end):
        self.begin = begin
        self.end = end


@dataclass
class IplSliderLimits:
    """
    A container for a slider and its range.
    """
    begin: Any = None  #: the begin value.
    end: Any = None  #: the end value.

    def get_limits(self):
        return self.begin, self.end

    def set_limits(self, begin, end):
        self.begin = begin
        self.end = end


@dataclass
class IplPlotViewLimits:
    """
    A container for a plot and its view limits.
    The view limits are a collection of all the axis limits for a plot.
    """
    axes_ranges: List[IplAxisLimits] = field(default_factory=list)  #: a list of axis limits for each axis of this plot.
    signals_ranges: List[IplSignalLimits] = field(
        default_factory=list)  #: a list of signal limits for each axis of this plot.
    sliders_ranges: List[IplSliderLimits] = field(
        default_factory=list)  #: a list of slider limits for each axis of this plot.
    plot_ref: ref = None  #: a weak reference to the core iplotlib plot object.
