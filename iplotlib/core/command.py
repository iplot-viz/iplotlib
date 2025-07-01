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
The command abstraction. 
In iplotlib, a command encodes a user interactive action.
"""

# Author: Jaswant Sai Panchumarti

from abc import ABC, abstractmethod


class IplotCommand(ABC):
    """
    An IplotCommand object has a name and an undo method.
    The command can be redone by simply calling the object.
    """

    def __init__(self, name: str) -> None:
        super().__init__()
        self.name = name

    @abstractmethod
    def __call__(self):
        """
        Redo the action of this command.
        """
        return

    @abstractmethod
    def undo(self):
        """
        Undo the action of this command.
        """
        return
