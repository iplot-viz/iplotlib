"""The assembly of canvases keeps a row of its model for each canvas, and no item that Qt deletes with the model."""

import unittest

import shiboken6
from PySide6.QtCore import Qt
from PySide6.QtGui import QStandardItem

from iplotlib.core import Canvas
from iplotlib.impl.matplotlib.tests.QAppOffscreenTestAdapter import QAppOffscreenTestAdapter
from iplotlib.qt.gui.iplotQtCanvasAssembly import IplotQtCanvasAssembly
from iplotlib.qt.gui.iplotQtCanvasFactory import IplotQtCanvasFactory


class CanvasAssemblyTest(QAppOffscreenTestAdapter):

    def test_each_canvas_has_its_row(self):
        assembly = IplotQtCanvasAssembly()
        self.addCleanup(shiboken6.delete, assembly)
        first, second = Canvas(title='first'), Canvas(title='second')
        assembly.addWidget(IplotQtCanvasFactory.new('matplotlib', canvas=second))
        assembly.insertWidget(0, IplotQtCanvasFactory.new('matplotlib', canvas=first))
        model = assembly.model()
        self.assertEqual([model.item(row, 0).data(Qt.ItemDataRole.UserRole) for row in range(model.rowCount())],
                         [first, second])

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
