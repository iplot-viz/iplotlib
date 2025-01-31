import unittest
from iplotlib.core.canvas import Canvas
from iplotlib.impl.matplotlib.matplotlibCanvas import MatplotlibParser
from iplotlib.impl.vtk.vtkCanvas import VTKParser


class VTKParserTesting(unittest.TestCase):

    def setUp(self) -> None:
        super().setUp()
        self.canvas = Canvas(2, 2)

    def test_02_canvas_sizing_refresh_vtk(self):
        self.parser = VTKParser()
        self.parser.process_ipl_canvas(self.canvas)

        size = self.parser.matrix.GetSize()

        self.assertEqual(size[0], 2)
        self.assertEqual(size[1], 2)

    def test_02_canvas_sizing_refresh_matplotlib(self):
        self.parser = MatplotlibParser()
        self.parser.process_ipl_canvas(self.canvas)
        size = self.parser._layout
        self.assertEqual(size.nrows, 2)
        self.assertEqual(size.ncols, 2)


if __name__ == "__main__":
    unittest.main()
