"""Frozen crosshair artist for the Matplotlib backend.

A frozen crosshair draws the same vertical/horizontal line pair, name, axis and
per-signal value labels as :class:`~iplotlib.impl.matplotlib.iplotMplRuler.iplotMplRuler`,
so it reuses that artist wholesale. The only visual difference is the line
style: crosshairs use solid lines while rulers use dashed ones, which lets the
user tell the two features apart on the plot.

The lines keep the ruler's ``_RulerLine`` label, so the signal-line filters that
already exclude ruler helpers also exclude crosshair helpers from legend and
signal-index bookkeeping without any further change.
"""

from iplotlib.impl.matplotlib.iplotMplRuler import iplotMplRuler


class iplotMplCrosshair(iplotMplRuler):
    """A frozen crosshair rendered with solid lines instead of dashed ones."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault('linestyle', '-')
        super().__init__(*args, **kwargs)
