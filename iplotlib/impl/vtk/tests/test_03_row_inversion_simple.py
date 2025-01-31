import unittest
from iplotlib.core.canvas import Canvas
from iplotlib.core.plot import Plot
from iplotlib.impl.vtk.vtkCanvas import VTKParser


class VTKParserTesting(unittest.TestCase):

    def setUp(self) -> None:
        super().setUp()
        self.canvas = Canvas(6, 5)

        for c in range(self.canvas.cols):
            for _ in range(self.canvas.rows):
                plot = Plot()
                self.canvas.add_plot(plot, c)

        self.parser = VTKParser()

        self.parser.process_ipl_canvas(self.canvas)

    def tst_03_row_inversion_simple_vtk(self):

        valid_internal_row_ids = [5, 4, 3, 2, 1, 0]

        for c, column in enumerate(self.parser.canvas.plots):
            r = 0
            test_internal_row_ids = []

            for plot in column:
                test_internal_row_ids.append(self.parser.get_internal_row_id(r, plot))
                r += plot.row_span

            self.assertListEqual(test_internal_row_ids, valid_internal_row_ids)


if __name__ == "__main__":
    unittest.main()
