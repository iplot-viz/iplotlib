import unittest
from iplotlib.core.canvas import Canvas
from iplotlib.impl.vtk.vtkCanvas import VTKParser


class VTKParserTesting(unittest.TestCase):

    def test_01_null_refresh_vtk(self):
        canvas = Canvas(0, 0)
        self.vtk_parser = VTKParser()
        self.vtk_parser.process_ipl_canvas(canvas)

        size = self.vtk_parser.matrix.GetSize()
        self.assertEqual(size[0], 0)
        self.assertEqual(size[1], 0)

if __name__ == "__main__":
    unittest.main()
