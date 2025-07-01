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
