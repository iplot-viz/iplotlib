"""
The property manager returns the appropriate value for an attribute in the hierarchy of core iplotlib classes.
"""

from iplotlib.core.axis import Axis
from iplotlib.core.canvas import Canvas
from iplotlib.core.plot import Plot
from iplotlib.core.signal import Signal


class PropertyManager:
    """ 
    This class provides an API that returns attributes in the iplotlib hierarchy.
    """

    def get_value(self, attr_name: str, canvas: Canvas, plot: Plot = None, axis: Axis = None, signal: Signal = None):
        """ 
        Get the value of the attribute from the given core iplotlib objects respecting the hierarchy constraint.
        """
        if canvas is None:
            return None
        elif plot is None and axis is None and signal is None:
            return self._get_canvas_attr(attr_name, canvas)
        elif axis is None and signal is None:
            return self._get_plot_attr(attr_name, canvas, plot)
        elif signal is None:
            return self._get_axis_attr(attr_name, canvas, plot, axis)
        else:
            return self._get_signal_attr(attr_name, canvas, plot, signal)

    @staticmethod
    def _get_canvas_attr(attr_name: str, canvas: Canvas):
        if getattr(canvas, attr_name) is not None:
            return getattr(canvas, attr_name)
        else:
            return None

    def _get_plot_attr(self, attr_name: str, canvas: Canvas, plot: Plot):
        if getattr(plot, attr_name) is not None:
            return getattr(plot, attr_name)
        else:
            return self._get_canvas_attr(attr_name, canvas)

    def _get_axis_attr(self, attr_name: str, canvas: Canvas, plot: Plot, axis: Axis):
        if getattr(axis, attr_name) is not None:
            return getattr(axis, attr_name)
        else:
            return self._get_plot_attr(attr_name, canvas, plot)

    def _get_signal_attr(self, attr_name: str, canvas: Canvas, plot: Plot, signal: Signal):
        if getattr(signal, attr_name) is not None:
            return getattr(signal, attr_name)
        else:
            return self._get_plot_attr(attr_name, canvas, plot)
