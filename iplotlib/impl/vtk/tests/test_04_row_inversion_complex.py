import unittest
from iplotlib.core.plot import Plot
from iplotlib.impl.vtk.vtkCanvas import VTKCanvas


class VTKCanvasTesting(unittest.TestCase):

    def setUp(self) -> None:

        self.vtk_canvas = VTKCanvas(6, 5)

        for c in range(self.vtk_canvas.cols):
            for _ in range(0, self.vtk_canvas.rows, 2):
                plot = Plot(row_span=2)
                self.vtk_canvas.add_plot(plot, c)

        return super().setUp()

    def test_internal_row_id(self):
        
        valid_internal_row_ids = [4, 2, 0]

        for c, column in enumerate(self.vtk_canvas.plots):
            r = 0
            test_internal_row_ids = []
            
            for plot in column:
                test_internal_row_ids.append(self.vtk_canvas.get_internal_row_id(r, plot))
                r += plot.row_span

            self.assertListEqual(test_internal_row_ids, valid_internal_row_ids)

if __name__ == "__main__":
    unittest.main()
