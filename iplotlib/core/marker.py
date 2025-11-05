""" Represents a spatial marker used to identify and compare specific points on a plotted SignalXY.

Each marker stores a pair of (x, y) coordinates, along with a name, visibility state, and color.
Markers can be placed on data plots to mark points of interest and to compute distance between two marked positions.
"""

from dataclasses import dataclass
from typing import Tuple


@dataclass
class Marker:
    name: str = None
    xy: Tuple[float, float] = None
    color: str = "#FFFFFF"
    visible: bool = False
    _type: str = None

    def __post_init__(self):
        self._type = self.__class__.__module__ + '.' + self.__class__.__qualname__
