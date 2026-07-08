"""Frozen crosshair artist for the PyQtGraph backend (issue #130).

A frozen crosshair is a *time cursor*: it reports the value of every signal at a
fixed time. It shares all rendering with :class:`~iplotlib.impl.pyqtgraph.pyQtRuler.pyQtRuler`
but is drawn with solid lines so it reads as distinct from the dashed
measurement ruler.
"""

from pyqtgraph.Qt import QtCore

from iplotlib.impl.pyqtgraph.pyQtRuler import pyQtRuler


class pyQtCrosshairFrozen(pyQtRuler):
    """A :class:`pyQtRuler` rendered with solid lines to mark a frozen time."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault('line_style', QtCore.Qt.PenStyle.SolidLine)
        super().__init__(*args, **kwargs)
