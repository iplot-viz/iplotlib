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
