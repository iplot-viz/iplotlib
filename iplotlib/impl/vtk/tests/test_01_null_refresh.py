import unittest
from iplotlib.core.plot import Plot
from iplotlib.impl.vtk.vtkCanvas import VTKCanvas

class VTKCanvasTesting(unittest.TestCase):
    def setUp(self) -> None:
        super().setUp()

    def test_null_refresh(self):
        self.vtk_canvas = VTKCanvas(0, 0)
        self.vtk_canvas.refresh()

if __name__ == "__main__":
    unittest.main()