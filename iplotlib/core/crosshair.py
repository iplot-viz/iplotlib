""" A frozen crosshair placed on a plot.

A frozen crosshair is a crosshair (vertical + horizontal line) anchored at a
fixed (x, y) position, created by clicking while the crosshair mouse mode is
active. It shares the data model, artists and table plumbing with
:class:`~iplotlib.core.ruler.Ruler`, but is a distinct, separately-toggled
feature: the crosshair table additionally exposes one value column per signal.
"""

from dataclasses import dataclass

from iplotlib.core.ruler import Ruler


@dataclass
class Crosshair(Ruler):
    # No extra state: a frozen crosshair is a Ruler with its own ``_type`` (set
    # by Ruler.__post_init__ from the concrete class), which is what the generic
    # JSON (de)serializer keys on to round-trip it independently of rulers.
    pass
