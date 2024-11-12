"""
The GUI forms for setting the attribute values of iplotlib objects.
"""
from .iplotPreferencesForm import IplotPreferencesForm
from .plotting import AxisForm, CanvasForm, PlotForm, SignalXYForm, SignalContourForm

__all__ = ['IplotPreferencesForm', 'AxisForm',
           'CanvasForm', 'PlotForm', 'SignalXYForm', 'SignalContourForm']
