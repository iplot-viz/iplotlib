"""The assembly of canvases keeps a row of its model for each canvas, takes it away with its canvas, and keeps no item
that Qt deletes with the model."""

import unittest

import shiboken6
from PySide6.QtCore import Qt
from PySide6.QtGui import QStandardItem

from iplotlib.core import Canvas
from iplotlib.impl.matplotlib.tests.QAppOffscreenTestAdapter import QAppOffscreenTestAdapter
from iplotlib.qt.gui.iplotQtCanvasAssembly import IplotQtCanvasAssembly
from iplotlib.qt.gui.iplotQtCanvasFactory import IplotQtCanvasFactory


def _held(assembly: IplotQtCanvasAssembly) -> list:
    """The canvas each row of the model of the assembly holds."""
    model = assembly.model()
    return [model.item(row, 0).data(Qt.ItemDataRole.UserRole) for row in range(model.rowCount())]


class CanvasAssemblyTest(QAppOffscreenTestAdapter):

    def test_each_canvas_has_its_row(self):
        assembly = IplotQtCanvasAssembly()
        self.addCleanup(shiboken6.delete, assembly)
        first, second = Canvas(title='first'), Canvas(title='second')
        assembly.addWidget(IplotQtCanvasFactory.new('matplotlib', canvas=second))
        assembly.insertWidget(0, IplotQtCanvasFactory.new('matplotlib', canvas=first))
        self.assertEqual(_held(assembly), [first, second])

    def test_a_canvas_removed_takes_its_row_with_it(self):
        assembly = IplotQtCanvasAssembly()
        self.addCleanup(shiboken6.delete, assembly)
        first, second = Canvas(title='first'), Canvas(title='second')
        widget = IplotQtCanvasFactory.new('matplotlib', canvas=first)
        assembly.addWidget(widget)
        assembly.addWidget(IplotQtCanvasFactory.new('matplotlib', canvas=second))
        removed = []
        assembly.canvasRemoved.connect(lambda idx, canvas: removed.append((idx, canvas)))

        assembly.removeWidget(widget)

        self.assertEqual(_held(assembly), [second])
        self.assertEqual(assembly.count(), 1)
        self.assertEqual(removed, [(0, widget)])

    def test_keeps_no_item_that_qt_deletes_with_its_model(self):
        # Its window can outlive its widgets, as one caught in a cycle until Python collects it. shiboken can't know
        # that an item Qt made is deleted, and would hand its wrapper back for another object made at the same address.
        assembly = IplotQtCanvasAssembly()
        shiboken6.delete(assembly)
        kept = [value for value in vars(assembly).values()
                if isinstance(value, QStandardItem) and not shiboken6.createdByPython(value)]
        self.assertEqual(kept, [])


if __name__ == '__main__':
    unittest.main()
