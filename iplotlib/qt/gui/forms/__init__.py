"""
The GUI forms for setting the attribute values of iplotlib objects.
"""
from .iplotPreferencesForm import IplotPreferencesForm
from .plotting import AxisForm, CanvasForm, PlotXYForm, PlotContourForm, SignalXYForm, SignalContourForm

__all__ = ['IplotPreferencesForm', 'AxisForm',
           'CanvasForm', 'PlotXYForm', 'PlotContourForm', 'SignalXYForm', 'SignalContourForm']
