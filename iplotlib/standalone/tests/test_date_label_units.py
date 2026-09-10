"""Date-axis tick labels carry a unit when they shrink to a bare number.

Zoomed inside one minute the ticks used to read "06 08 10", inside one hour
"20 30 40": nothing on the axis said whether those were seconds, minutes or
milliseconds. Both backends now suffix such labels with the pulse-style unit
of their last digit, while clock-formatted labels ("09:00") stay as they are.
"""

import unittest

import numpy as np

from iplotlib.core.canvas import Canvas
from iplotlib.core.plot import PlotXY
from iplotlib.core.signal import SignalXY
from iplotlib.qt.gui.iplotQtCanvasFactory import IplotQtCanvasFactory
from iplotlib.qt.testing import ensure_qapp

_SEC = 1_000_000_000
_MIN = 60 * _SEC
_HOUR = 60 * _MIN
# 2026-08-13T05:52:00Z, the minute of the screenshot in the report.
T_MINUTE = 1_786_600_320_000_000_000


def _make_canvas(lo, hi, tick_number=7):
    core = Canvas(1, 1, title="date-label-units")
    core.tick_number = tick_number
    x = np.linspace(lo, hi, 500).astype(np.int64)
    plot = PlotXY()
    signal = SignalXY(label="s")
    signal.set_data([x, np.sin(np.linspace(0.0, 6.0, x.size))])
    plot.add_signal(signal)
    plot.axes[0].is_date = True
    core.add_plot(plot, 0)
    return core


class DateLabelUnitsTest(unittest.TestCase):
    def setUp(self) -> None:
        super().setUp()
        self.app = ensure_qapp()

    def _labels(self, backend, lo, hi, tick_number=7):
        core = _make_canvas(lo, hi, tick_number)
        qt_canvas = IplotQtCanvasFactory.new(backend, canvas=core)
        qt_canvas.set_canvas(core)
        qt_canvas.resize(1200, 700)
        self.app.processEvents()
        self.assertFalse(qt_canvas.grab().isNull())
        impl = qt_canvas._parser._plot_impl_plot_lut.get(id(core.plots[0][0]))[0]
        if backend == 'pyqt':
            axis = impl.getAxis('bottom')
            (xmin, xmax), _ = impl.getViewBox().viewRange()
            spacing, values = axis.tickValues(xmin, xmax, axis.geometry().width())[0]
            labels = axis.tickStrings(values, 1.0, spacing)
        else:
            xaxis = impl.xaxis
            formatter = xaxis.get_major_formatter()
            locs = xaxis.get_major_locator()()
            formatter.set_locs(locs)
            labels = [formatter(loc) for loc in locs]
        qt_canvas.deleteLater()
        return [label for label in labels if label]

    def test_seconds_inside_one_minute_are_labelled_in_seconds(self):
        for backend in ('pyqt', 'matplotlib'):
            labels = self._labels(backend, T_MINUTE + 4 * _SEC, T_MINUTE + 16 * _SEC)
            self.assertGreaterEqual(len(labels), 5, backend)
            for label in labels:
                self.assertRegex(label, r'^\d{2}s$', backend)

    def test_minutes_inside_one_hour_are_labelled_in_minutes(self):
        for backend in ('pyqt', 'matplotlib'):
            labels = self._labels(backend, T_MINUTE - 37 * _MIN, T_MINUTE - 7 * _MIN, 4)
            self.assertGreaterEqual(len(labels), 3, backend)
            for label in labels:
                self.assertRegex(label, r'^\d{2}min$', backend)

    def test_clock_labels_across_hours_keep_their_format(self):
        for backend in ('pyqt', 'matplotlib'):
            labels = self._labels(backend, T_MINUTE - 3 * _HOUR, T_MINUTE + 3 * _HOUR)
            self.assertGreaterEqual(len(labels), 5, backend)
            for label in labels:
                self.assertRegex(label, r'^\d{2}:\d{2}$', backend)


if __name__ == "__main__":
    unittest.main()
