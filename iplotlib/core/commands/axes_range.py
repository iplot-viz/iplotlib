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
This module defines a command to set or 
restore the axes ranges for all plots.
"""
# Author: Jaswant Sai Panchumarti

from typing import List, Optional
from iplotlib.core.command import IplotCommand
from iplotlib.core.impl_base import BackendParserBase
from iplotlib.core.limits import IplPlotViewLimits


class IplotAxesRangeCmd(IplotCommand):
    """
    A command to set the plot view limits.
    """

    def __init__(self, name: str, old_limits: List[IplPlotViewLimits],
                 new_limits: Optional[List[IplPlotViewLimits]] = None,
                 parser: BackendParserBase = None) -> None:
        super().__init__(name)
        self.old_lim = old_limits
        self.new_lim = new_limits if new_limits is not None else []
        self._parser = parser

    def __call__(self):
        """
        Redo the command. All plots are restored to their new limits.
        """
        super().__call__()
        self._parser.canvas.undo_redo = True
        for limits in self.new_lim:
            self._parser.set_plot_limits(limits)

        self._parser.canvas.undo_redo = False

    def undo(self):
        """
        Undo the command. All plots are restored to their old limits.
        """
        super().undo()
        self._parser.canvas.undo_redo = True
        for limits in self.old_lim:
            self._parser.set_plot_limits(limits)
        self._parser.canvas.undo_redo = False

    def __str__(self):
        """
        Convenient to see the name of the command with print(cmd)

        :return: The name of the command with its id.
        :rtype: str
        """
        return f"{self.__class__.__name__}({hex(id(self))}) {self.name}"
