"""Legend tests for an envelope signal during streaming.

On Stream the canvas is (re)built before the backfill arrives, so an envelope
signal has no samples yet. Its empty average array is dropped, leaving three
data arrays; the draw path pads the missing average so the empty curves are
still drawn and the signal joins the legend from the start, the way a plain
signal already does. These tests assert the build does not raise and that the
envelope is in the legend both right after build and once its first batch draws,
on both backends.
"""

import unittest

import numpy as np

from iplotProcessing.core import BufferObject
from iplotlib.core.canvas import Canvas
from iplotlib.core.plot import PlotXY
from iplotlib.core.signal import SignalXY
from iplotlib.qt.gui.iplotQtCanvasFactory import IplotQtCanvasFactory
from iplotlib.qt.testing import ensure_qapp

BACKENDS = ('matplotlib', 'pyqt')


class StreamingEnvelopeLegendTest(unittest.TestCase):

    def setUp(self):
        self.app = ensure_qapp()

    def _canvas_with_empty_envelope(self):
        canvas = Canvas(1, 1, legend=True, legend_position="upper right")
        plot = PlotXY()
        raw = SignalXY(label="raw")
        env = SignalXY(label="env", envelope=True)
        while len(env.data_store) < 4:
            env.data_store.append(BufferObject())
        plot.add_signal(raw)
        plot.add_signal(env)
        canvas.add_plot(plot, 0)
        canvas.streaming = True
        for s in (raw, env):
            s.hi_precision_data = True
            s.data_access_enabled = False
            s._streaming_has_live = True
        return canvas, raw, env

    @staticmethod
    def _feed_first_batch(raw, env):
        x = np.linspace(0, 10, 200)
        raw.set_data([x, np.sin(x)])
        env.set_data([x, np.cos(x) - 1, np.cos(x) + 1])
        env.data_store[3] = BufferObject(np.cos(x))

    def _build(self, backend, canvas):
        qt = IplotQtCanvasFactory.new(backend, canvas=canvas)
        qt.set_canvas(canvas)
        self.app.processEvents()
        return qt

    @staticmethod
    def _legend_count(parser, signal):
        impl_plot = parser._signal_impl_plot_lut.get(parser.signal_lut_key(signal))
        if impl_plot is None:
            return None
        if hasattr(impl_plot, 'get_legend'):  # matplotlib Axes
            legend = impl_plot.get_legend()
            return len(legend.get_texts()) if legend else 0
        legend = getattr(impl_plot, 'legend', None)  # pyqtgraph PlotItem
        return len(legend.items) if legend is not None else 0

    def test_build_and_first_batch_do_not_raise(self):
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                canvas, raw, env = self._canvas_with_empty_envelope()
                qt = self._build(backend, canvas)
                self._feed_first_batch(raw, env)
                qt._parser.process_ipl_signal(raw)
                qt._parser.process_ipl_signal(env)
                self.app.processEvents()

    def test_envelope_is_in_legend_from_build_and_stays(self):
        # The empty envelope must appear in the legend already at build (both
        # signals -> two entries) and must not drop out when its first batch
        # draws, on both backends.
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                canvas, raw, env = self._canvas_with_empty_envelope()
                qt = self._build(backend, canvas)

                self.assertEqual(self._legend_count(qt._parser, env), 2)

                self._feed_first_batch(raw, env)
                qt._parser.process_ipl_signal(raw)
                qt._parser.process_ipl_signal(env)
                self.app.processEvents()

                self.assertEqual(self._legend_count(qt._parser, env), 2)


if __name__ == '__main__':
    unittest.main()
