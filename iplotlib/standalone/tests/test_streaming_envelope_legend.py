"""Regression tests for the legend of an envelope signal that is still waiting
for its first streaming batch.

On Stream the canvas is (re)built before the backfill arrives, so envelope
signals have no artists yet: their shape lookup is None and ``signal.lines`` is
empty. The legend build used to iterate over that None (crash, legend gone) and
the streaming autoscale used to index the empty ``lines`` (crash). Both backends
had the flaw. These tests build that exact state and assert it no longer raises,
and that the envelope joins the legend once its first batch is drawn.
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

    def test_build_and_first_batch_do_not_raise(self):
        # Both the legend build (was TypeError over None) and the streaming
        # autoscale on the next batch (was IndexError over empty lines).
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                canvas, raw, env = self._canvas_with_empty_envelope()
                qt = self._build(backend, canvas)
                self._feed_first_batch(raw, env)
                qt._parser.process_ipl_signal(raw)
                qt._parser.process_ipl_signal(env)
                self.app.processEvents()

    def test_matplotlib_envelope_enters_legend_after_first_batch(self):
        canvas, raw, env = self._canvas_with_empty_envelope()
        qt = self._build('matplotlib', canvas)
        ax = qt._parser._signal_impl_plot_lut.get(env.uid)

        # The raw signal drew an (empty) line, so the legend exists but omits
        # the not-yet-drawn envelope.
        self.assertIsNotNone(ax.get_legend())
        before = len(ax.get_legend().get_texts())

        self._feed_first_batch(raw, env)
        qt._parser.process_ipl_signal(raw)
        qt._parser.process_ipl_signal(env)
        self.app.processEvents()

        self.assertIsNotNone(ax.get_legend())
        self.assertEqual(len(ax.get_legend().get_texts()), before + 1)

    def test_pyqtgraph_envelope_stays_in_legend_after_first_batch(self):
        # pyqtgraph auto-populates the legend as curves are drawn; the streaming
        # legend refresh must not clear it and drop the envelope entry.
        canvas, raw, env = self._canvas_with_empty_envelope()
        qt = self._build('pyqt', canvas)
        plot = qt._parser._signal_impl_plot_lut.get(env.uid)
        before = len(plot.legend.items)

        self._feed_first_batch(raw, env)
        qt._parser.process_ipl_signal(raw)
        qt._parser.process_ipl_signal(env)
        self.app.processEvents()

        self.assertEqual(len(plot.legend.items), before + 1)


if __name__ == '__main__':
    unittest.main()
