""" A ruler placed on a plot to measure (x, y) values and distances.

A ruler is a frozen crosshair (vertical + horizontal line) anchored at a fixed
(x, y) position. Rulers belong to the plot where they were placed and can be
combined to compute deltas between pairs.
"""

from dataclasses import dataclass
from typing import Tuple


@dataclass
class Ruler:
    name: str = None
    xy: Tuple[float, float] = None
    color: str = "#FFFFFF"
    visible: bool = True
    _type: str = None

    def __post_init__(self):
        self._type = self.__class__.__module__ + '.' + self.__class__.__qualname__
