import unittest
from iplotlib.core.canvas import Canvas
from iplotlib.impl.vtk.vtkCanvas import VTKParser

@unittest.skip("VTKParser tests skipped: VTK integration not in use.")
class VTKParserTesting(unittest.TestCase):
    def setUp(self) -> None:
        super().setUp()

    def test_01_null_refresh(self):
        canvas = Canvas(0, 0)
        self.vtk_parser = VTKParser()
        self.vtk_parser.process_ipl_canvas(canvas)

        size = self.vtk_parser.matrix.GetSize()
        self.assertEqual(size[0], 0)
        self.assertEqual(size[1], 0)


if __name__ == "__main__":
    unittest.main()
