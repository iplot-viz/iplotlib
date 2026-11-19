"""A canvas with an envelope, drawn on screen, exported to a file as the command line of MINT does: the export draws
its signals again, from the lines they were drawn with."""

import os
import tempfile
import unittest

import numpy as np
import shiboken6
from iplotProcessing.core import BufferObject

from iplotlib.core.canvas import Canvas
from iplotlib.core.plot import PlotXY
from iplotlib.core.signal import SignalXY
from iplotlib.impl.matplotlib.matplotlibCanvas import MatplotlibParser
from iplotlib.impl.pyqtgraph.pyQtGraphCanvas import PyQtGraphParser
from iplotlib.qt.gui.iplotQtCanvasFactory import IplotQtCanvasFactory
from iplotlib.qt.testing import ensure_qapp

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

BACKENDS = (('matplotlib', MatplotlibParser), ('pyqt', PyQtGraphParser))


def _envelope(label, hidden=False) -> SignalXY:
    x = np.linspace(0, 10, 50)
    signal = SignalXY(label=label, envelope=True, hidden=hidden)
    signal.data_access_enabled = False
    # The average is only read with the envelope: its slot follows the minimum and the maximum.
    while len(signal.data_store) < 4:
        signal.data_store.append(BufferObject())
    signal.data_store[3] = BufferObject(np.sin(x))
    signal.set_data([x, np.sin(x) - 1, np.sin(x) + 1])
    return signal


class ExportDrawnEnvelopeTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.app = ensure_qapp()

    def test_a_drawn_envelope_is_exported_and_a_hidden_one_stays_hidden(self):
        for backend, parser_class in BACKENDS:
            with self.subTest(backend=backend):
                canvas = Canvas(1, 1)
                plot = PlotXY()
                shown, hidden = _envelope('shown'), _envelope('hidden', hidden=True)
                plot.add_signal(shown)
                plot.add_signal(hidden)
                canvas.add_plot(plot, 0)
                qt_canvas = IplotQtCanvasFactory.new(backend, canvas=canvas)
                self.addCleanup(qt_canvas.deleteLater)
                self.app.processEvents()
                folder = tempfile.TemporaryDirectory()
                self.addCleanup(folder.cleanup)
                parser = parser_class()
                if backend == 'pyqt':
                    self.addCleanup(shiboken6.delete, parser.figure)
                path = os.path.join(folder.name, 'canvas.png')

                parser.export_image(path, canvas=canvas, dpi=100, width=800, height=600)

                self.assertTrue(os.path.getsize(path) > 0)
                for signal, visible in ((shown, True), (hidden, False)):
                    artists = parser._signal_impl_shape_lut[id(signal)][0]
                    for artist in artists:
                        self.assertEqual(artist.get_visible() if backend == 'matplotlib' else artist.isVisible(),
                                         visible)


if __name__ == '__main__':
    unittest.main()
