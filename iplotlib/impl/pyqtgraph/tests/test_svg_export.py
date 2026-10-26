"""Saving pyqtgraph plots as SVG, with a Qt that ends closed paths in Z."""

import importlib
import os
import tempfile
import unittest
from xml.dom import minidom

import numpy as np
import shiboken6

from iplotlib.core.canvas import Canvas
from iplotlib.core.plot import PlotXY
from iplotlib.core.signal import SignalXY
from iplotlib.impl.pyqtgraph.pyQtGraphCanvas import PyQtGraphParser
from iplotlib.qt.testing import ensure_qapp

# pyqtgraph.exporters re-exports the class under the module's name.
SVG_EXPORTER = importlib.import_module('pyqtgraph.exporters.SVGExporter')


class SvgExportTest(unittest.TestCase):
    def setUp(self) -> None:
        super().setUp()
        self.app = ensure_qapp()

    def test_closed_paths_are_moved_and_keep_their_z(self):
        node = minidom.parseString('<g><g transform="matrix(2,0,0,2,10,20)">'
                                   '<path d="M0,0 L5,0 L5,5 Z M1,1 L2,1 Z"/></g></g>').documentElement

        SVG_EXPORTER.correctCoordinates(node, [], None, {})

        self.assertEqual(node.getElementsByTagName('path')[0].getAttribute('d'),
                         'M10.0,20.0 L20.0,20.0 L20.0,30.0 Z M12.0,22.0 L14.0,22.0 Z')

    def test_the_command_line_export_writes_svg(self):
        canvas = Canvas(1, 1)
        plot = PlotXY()
        signal = SignalXY(label='s')
        x = np.linspace(0, 10, 100)
        signal.set_data([x, np.sin(x)])
        plot.add_signal(signal)
        canvas.add_plot(plot, 0)
        parser = PyQtGraphParser()
        # Deleted here rather than at exit, when Python has already torn down its items.
        self.addCleanup(shiboken6.delete, parser.figure)
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        path = os.path.join(folder.name, 'canvas.svg')

        parser.export_image(path, canvas=canvas)

        self.assertEqual(minidom.parse(path).documentElement.tagName, 'svg')


if __name__ == '__main__':
    unittest.main()
