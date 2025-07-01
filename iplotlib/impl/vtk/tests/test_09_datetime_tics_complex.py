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


import numpy as np
import os
import unittest
from iplotlib.core.canvas import Canvas
from iplotlib.core.axis import LinearAxis
from iplotlib.core.plot import PlotXY
from iplotlib.core.signal import SignalXY
from iplotlib.impl.vtk.utils import regression_test
from iplotlib.impl.vtk.tests.qVTKAppTestAdapter import QVTKAppTestAdapter
from iplotlib.impl.vtk.tests.vtk_hints import vtk_is_headless


class VTKCanvasTesting(QVTKAppTestAdapter):

    def setUp(self) -> None:
        ts = 1641400277844680508
        te = ts + 8 * 32
        xs = np.arange(ts, te, 8, dtype=np.uint64)
        ys = np.sin(np.linspace(-1, 1, len(xs)))
        # A 2col x 2row canvas
        self.core_canvas = Canvas(2, 2, title=os.path.basename(__file__))

        # A plot in top-left with 1 signal.
        signal11 = SignalXY(label="Signal1.1", hi_precision_data=True)
        signal11.set_data([xs, ys])
        plot11 = PlotXY(plot_title="DateTime=True, HiPrecision=True")
        plot11.axes[0].is_date = True
        plot11.add_signal(signal11)
        self.core_canvas.add_plot(plot11, 0)

        # A plot in bottom-left with 2 stacked signal.
        signal121 = SignalXY(label="Signal1.2.1")
        signal121.set_data([xs, ys])
        plot12 = PlotXY(plot_title="DateTime=True, HiPrecision=True",
                        axes=[LinearAxis(), [LinearAxis(), LinearAxis()]])
        plot12.axes[0].is_date = True
        plot12.add_signal(signal121)
        signal122 = SignalXY(label="Signal1.2.2")
        signal122.set_data([xs, -ys])
        plot12.add_signal(signal122, 2)
        self.core_canvas.add_plot(plot12, 0)

        # A plot in top-right with 1 signal.
        plot12.axes[1] = [LinearAxis(), LinearAxis()]
        signal21 = SignalXY(label="Signal2.1", hi_precision_data=True)
        signal21.set_data([xs, ys])
        plot21 = PlotXY(plot_title="DateTime=True, HiPrecision=True")
        plot21.axes[0].is_date = True
        plot21.add_signal(signal21)
        self.core_canvas.add_plot(plot21, 1)

        # A plot in bottom-right with 1 signal.
        signal22 = SignalXY(label="Signal2.2")
        signal22.set_data([xs, ys])
        plot22 = PlotXY(plot_title="DateTime=False, HiPrecision=True")
        plot22.add_signal(signal22)
        self.core_canvas.add_plot(plot22, 1)

        return super().setUp()

    def tearDown(self):
        return super().tearDown()

    @unittest.skipIf(vtk_is_headless(), "VTK was built in headless mode.")
    def test_09_datetime_tics_complex_refresh(self):
        self.canvas.set_canvas(self.core_canvas)

    @unittest.skipIf(vtk_is_headless(), "VTK was built in headless mode.")
    def test_09_datetime_tics_complex_visuals(self):
        self.canvas.set_canvas(self.core_canvas)
        self.canvas.update()
        self.canvas.show()
        self.canvas.get_vtk_renderer().Initialize()
        self.canvas.get_vtk_renderer().Render()

        renWin = self.canvas.get_vtk_renderer().GetRenderWindow()
        valid_image_name = os.path.basename(__file__).replace("test", "valid").replace(".py", ".png")
        valid_image_path = os.path.join(os.path.join(os.path.dirname(__file__), "baseline"), valid_image_name)
        self.assertTrue(regression_test(valid_image_path, renWin))


if __name__ == "__main__":
    unittest.main()
