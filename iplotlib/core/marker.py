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
This module contains definitions of various kinds of Signal (s)
one might want to use when plotting data.

TODO: cambiar descripcion de clase
"""
from dataclasses import dataclass
from typing import Tuple


@dataclass
class Marker:
    """
    name : str
        Name of the marker
    xy : tuple
        Coordinates XY
    """

    name: str = None
    xy: Tuple[float, float] = None
    color: str = "#FFFFFF"
    visible: bool = False
    _type: str = None

    def __post_init__(self):
        self._type = self.__class__.__module__ + '.' + self.__class__.__qualname__
