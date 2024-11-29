"""
The concrete GUI forms for setting the attribute values of iplotlib objects.
"""
from .axisForm import AxisForm
from .canvasForm import CanvasForm
from .plotForm import PlotXYForm
from .plotForm import PlotContourForm
from .signalForm import SignalXYForm
from .signalForm import SignalContourForm

__all__ = ['AxisForm', 'CanvasForm', 'PlotXYForm', 'PlotContourForm', 'SignalXYForm', 'SignalContourForm']