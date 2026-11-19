"""The Y range a plot fits leaves out the signals hidden from its legend, and, with autoscale on, follows them as they
are hidden and shown."""

import os
import unittest

import numpy as np

from iplotlib.core.canvas import Canvas
from iplotlib.core.plot import PlotXY
from iplotlib.core.signal import SignalXY
from iplotlib.qt.gui.iplotQtCanvasFactory import IplotQtCanvasFactory
from iplotlib.qt.testing import ensure_qapp

BACKENDS = ('matplotlib', 'pyqt')

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')


class AutoscaleHiddenSignalsTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.app = ensure_qapp()

    def _draw(self, backend, autoscale):
        """A plot with a small signal, from 0 to 1, and a big one, from 0 to 100."""
        canvas = Canvas(1, 1, title='hidden signals', autoscale=autoscale)
        plot = PlotXY()
        signals = []
        for label, top in (('small', 1.0), ('big', 100.0)):
            signal = SignalXY(label=label)
            signal.data_access_enabled = False
            signal.set_data([np.arange(11, dtype=float), np.linspace(0.0, top, 11)])
            plot.add_signal(signal)
            signals.append(signal)
        canvas.add_plot(plot, 0)
        qt_canvas = IplotQtCanvasFactory.new(backend, canvas=canvas)
        self.addCleanup(qt_canvas.deleteLater)
        qt_canvas.set_canvas(canvas)
        qt_canvas.resize(400, 300)
        self.app.processEvents()
        impl_plot = qt_canvas._parser._signal_impl_plot_lut[qt_canvas._parser.signal_lut_key(signals[0])]
        return qt_canvas, impl_plot, signals

    @staticmethod
    def _click_legend(qt_canvas, impl_plot, signal):
        """Hide or show `signal` as a click on its legend entry does."""
        parser = qt_canvas._parser
        if hasattr(impl_plot, 'get_ylim'):
            entry = next(entry for entry, s in parser._legend_signal_lut.items() if s is signal)
            qt_canvas._toggle_legend_line(entry, parser.map_legend_to_ax[entry])
        else:
            item = next(item for item in impl_plot.listDataItems() if parser._legend_signal_lut.get(id(item)) is signal)
            item.setVisible(not item.isVisible())
            impl_plot.legend.sigSampleClicked.emit(item)

    @staticmethod
    def _top(impl_plot):
        return impl_plot.get_ylim()[1] if hasattr(impl_plot, 'get_ylim') else impl_plot.getViewBox().viewRange()[1][1]

    def test_with_autoscale_on_the_plot_fits_the_signals_shown_as_they_are_hidden_and_shown(self):
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                qt_canvas, impl_plot, (small, big) = self._draw(backend, autoscale=True)

                self._click_legend(qt_canvas, impl_plot, big)
                hidden = self._top(impl_plot)
                self._click_legend(qt_canvas, impl_plot, big)

                self.assertLess(hidden, 2)
                self.assertGreater(self._top(impl_plot), 100)

    def test_with_autoscale_off_hiding_keeps_the_range_and_the_autoscale_action_fits_the_signals_shown(self):
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                qt_canvas, impl_plot, (small, big) = self._draw(backend, autoscale=False)

                self._click_legend(qt_canvas, impl_plot, big)
                kept = self._top(impl_plot)
                qt_canvas.autoscale_y(impl_plot)

                self.assertGreater(kept, 100)
                self.assertLess(self._top(impl_plot), 2)

    def test_with_every_signal_hidden_the_plot_keeps_the_range_of_them_all(self):
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                qt_canvas, impl_plot, (small, big) = self._draw(backend, autoscale=True)

                self._click_legend(qt_canvas, impl_plot, small)
                self._click_legend(qt_canvas, impl_plot, big)

                self.assertGreater(self._top(impl_plot), 100)


if __name__ == '__main__':
    unittest.main()
