import unittest
from iplotlib.core.canvas import Canvas
from iplotlib.core.plot import Plot
from iplotlib.impl.vtk.vtkCanvas import VTKParser


class VTKParserTesting(unittest.TestCase):

    def setUp(self) -> None:

        canvas = Canvas(6, 5)
        self.vtk_parser = VTKParser()

        for c in range(canvas.cols):
            for _ in range(canvas.rows):
                plot = Plot()
                canvas.add_plot(plot, c)

        self.vtk_parser.process_ipl_canvas(canvas)

        return super().setUp()

    def test_03_row_inversion_simple(self):
        
        valid_internal_row_ids = [5, 4, 3, 2, 1, 0]

        for c, column in enumerate(self.vtk_parser.canvas.plots):
            r = 0
            test_internal_row_ids = []
            
            for plot in column:
                test_internal_row_ids.append(self.vtk_parser.get_internal_row_id(r, plot))
                r += plot.row_span

            self.assertListEqual(test_internal_row_ids, valid_internal_row_ids)

if __name__ == "__main__":
    unittest.main()
