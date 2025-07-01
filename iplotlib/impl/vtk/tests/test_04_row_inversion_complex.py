# Copyright (c) 2020-2025 ITER Organization,
#               CS 90046
#               13067 St Paul Lez Durance Cedex
#               France
# Author IO
#
# This file is part of iplotlib module.
# iplotlib python module is free software: you can redistribute it and/or modify it under
# the terms of the MIT license.
#
# This file is part of ITER CODAC software.
# For the terms and conditions of redistribution or use of this software
# refer to the file LICENSE located in the top level directory
# of the distribution package
#


import unittest
from iplotlib.core.canvas import Canvas
from iplotlib.core.plot import Plot
from iplotlib.impl.vtk.vtkCanvas import VTKParser


class VTKParserTesting(unittest.TestCase):

    def setUp(self) -> None:

        canvas = Canvas(6, 5)
        self.vtk_parser = VTKParser()

        for c in range(canvas.cols):
            for _ in range(0, canvas.rows, 2):
                plot = Plot(row_span=2)
                canvas.add_plot(plot, c)

        self.vtk_parser.process_ipl_canvas(canvas)

        return super().setUp()

    def test_04_row_inversion_complex(self):

        valid_internal_row_ids = [4, 2, 0]

        for c, column in enumerate(self.vtk_parser.canvas.plots):
            r = 0
            test_internal_row_ids = []

            for plot in column:
                test_internal_row_ids.append(self.vtk_parser.get_internal_row_id(r, plot))
                r += plot.row_span

            self.assertListEqual(test_internal_row_ids, valid_internal_row_ids)


if __name__ == "__main__":
    unittest.main()
