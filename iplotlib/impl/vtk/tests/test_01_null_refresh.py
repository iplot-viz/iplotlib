import unittest
from iplotlib.core.plot import Plot
from iplotlib.impl.vtk.vtkCanvas import VTKCanvas

class VTKCanvasTesting(unittest.TestCase):
    def setUp(self) -> None:
        super().setUp()

    def test_01_null_refresh(self):
        self.vtk_canvas = VTKCanvas(0, 0)
        self.vtk_canvas.refresh()

        size = self.vtk_canvas.matrix.GetSize()
        self.assertEqual(size[0], 0)
        self.assertEqual(size[1], 0)

if __name__ == "__main__":
    unittest.main()