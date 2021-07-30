import unittest
from iplotlib.impl.vtk.vtkCanvas import VTKCanvas


class VTKCanvasTesting(unittest.TestCase):

    def setUp(self) -> None:

        self.vtk_canvas = VTKCanvas(2, 2)
        return super().setUp()

    def test_refresh(self):

        self.assertEqual(self.vtk_canvas.cols, 2)
        self.assertEqual(self.vtk_canvas.rows, 2)

        self.vtk_canvas.refresh()

        size = self.vtk_canvas.matrix.GetSize()

        self.assertEqual(size[0], 2)
        self.assertEqual(size[1], 2)


if __name__ == "__main__":
    unittest.main()
