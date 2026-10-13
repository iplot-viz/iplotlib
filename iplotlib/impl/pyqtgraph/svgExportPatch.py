"""SVG export with pyqtgraph 0.14.0 and Qt 6.12, whose closed paths end in Z (pyqtgraph#3495)."""
import importlib

import pyqtgraph as pg


def patch_closed_paths():
    """Make pyqtgraph 0.14.0 transform the paths of an SVG around their Z, as later versions do."""
    if pg.__version__ != '0.14.0':
        return
    # pyqtgraph.exporters re-exports the class under the module's name.
    svg = importlib.import_module('pyqtgraph.exporters.SVGExporter')
    correct_coordinates = svg.correctCoordinates

    def correct_coordinates_around_z(node, defs, item, options):
        closes = []
        for path in node.getElementsByTagName('path'):
            words = path.getAttribute('d').split()
            marks = [(i, word) for i, word in enumerate(words) if ',' not in word]
            if marks:
                closes.append((path, marks))
                path.setAttribute('d', ' '.join(word for word in words if ',' in word))
        correct_coordinates(node, defs, item, options)
        for path, marks in closes:
            words = path.getAttribute('d').split()
            for i, word in marks:
                words.insert(i, word)
            path.setAttribute('d', ' '.join(words))

    svg.correctCoordinates = correct_coordinates_around_z
