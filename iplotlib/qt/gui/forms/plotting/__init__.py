"""
The concrete GUI forms for setting the attribute values of iplotlib objects.
"""
from .axisForm import AxisForm
from .canvasForm import CanvasForm
from .plotForm import PlotXYForm
from .plotForm import PlotContourForm
from .rulerForm import RulerForm
from .signalForm import SignalXYForm
from .signalForm import SignalContourForm

__all__ = ['AxisForm', 'CanvasForm', 'PlotXYForm', 'PlotContourForm', 'RulerForm',
           'SignalXYForm', 'SignalContourForm']
