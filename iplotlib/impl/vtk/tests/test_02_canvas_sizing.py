import unittest
from iplotlib.core.canvas import Canvas
from iplotlib.impl.vtk.vtkCanvas import VTKParser


class VTKParserTesting(unittest.TestCase):

    def setUp(self) -> None:

        self.vtk_canvas = VTKParser()
        return super().setUp()

    def test_02_canvas_sizing_refresh(self):
        
        canvas = Canvas(2, 2)
        self.vtk_canvas.process_ipl_canvas(canvas)

        size = self.vtk_canvas.matrix.GetSize()

        self.assertEqual(size[0], 2)
        self.assertEqual(size[1], 2)


if __name__ == "__main__":
    unittest.main()
