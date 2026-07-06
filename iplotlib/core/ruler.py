""" A ruler placed on a plot to measure (x, y) values and distances.

A ruler is a frozen crosshair (vertical + horizontal line) anchored at a fixed
(x, y) position. Rulers belong to the plot where they were placed and can be
combined to compute deltas between pairs.
"""

from dataclasses import dataclass
from typing import Tuple


def contrast_text_color(rgb) -> str:
    """Readable label colour over an arbitrary background: black on light
    backgrounds, white on dark ones (YIQ perceived luminance).

    rgb: an (r, g, b) triple, each channel 0-255.
    """
    r, g, b = rgb
    return 'black' if (r * 299 + g * 587 + b * 114) / 1000 > 128 else 'white'


@dataclass
class Ruler:
    name: str = None
    xy: Tuple[float, float] = None
    color: str = "#FFFFFF"
    font_color: str = "#FFFFFF"
    visible: bool = True
    show_label: bool = True
    show_val_label: bool = True
    _type: str = None

    def __post_init__(self):
        self._type = self.__class__.__module__ + '.' + self.__class__.__qualname__
