"""Unit coverage for the automatic X axis label made from the signal unit."""

import types
import unittest
import weakref

import numpy as np

from iplotProcessing.core import BufferObject

from iplotlib.core.axis import LinearAxis
from iplotlib.core.impl_base import BackendParserBase
from iplotlib.core.plot import PlotXY
from iplotlib.core.signal import SignalXY


class _LabelParser:
    """Stand-in exposing only what update_axis_labels_with_units touches."""

    def __init__(self, plot, signals):
        item = types.SimpleNamespace(plot=weakref.ref(plot),
                                     signals=[weakref.ref(s) for s in signals])
        self._impl_plot_cache_table = types.SimpleNamespace(get_cache_item=lambda impl: item)
        self._plot_impl_plot_lut = {}
        self.x_label = None
        self.y_label = None

    def set_impl_x_axis_label_text(self, impl_plot, text):
        self.x_label = text

    def set_impl_y_axis_label_text(self, impl_plot, text):
        self.y_label = text

    update_axis_labels_with_units = BackendParserBase.update_axis_labels_with_units


def _x_label_for(unit, is_date=False):
    signal = SignalXY(label="s")
    signal.x_data = BufferObject(np.arange(3.0), unit=unit)
    plot = PlotXY(axes=[LinearAxis(is_date=is_date), [LinearAxis()]])
    parser = _LabelParser(plot, [signal])
    parser.update_axis_labels_with_units(object(), signal)
    return parser.x_label


class XAxisUnitLabelTest(unittest.TestCase):
    def test_time_vector_label_is_not_bracketed(self):
        # The data access reports the time vector's unit as 'Time', which names
        # the quantity rather than measuring it.
        self.assertEqual(_x_label_for('Time'), 'Time')

    def test_real_unit_keeps_brackets(self):
        self.assertEqual(_x_label_for('A'), '[A]')

    def test_missing_unit_falls_back_to_placeholder(self):
        self.assertEqual(_x_label_for(''), '[? ]')

    def test_date_axis_gets_no_automatic_label(self):
        self.assertEqual(_x_label_for('Time', is_date=True), '')


if __name__ == '__main__':
    unittest.main()
