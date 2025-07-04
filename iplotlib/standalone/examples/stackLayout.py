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


"""
Demonstrate layout capabilities with stacking.
"""

import os
from iplotlib.core.axis import LinearAxis
import numpy as np
from iplotlib.core import Canvas, PlotXY, SignalXY
import time


def get_canvas():
    ts = time.time_ns()
    te = ts + 8 * 32
    xs = np.arange(ts, te, 8, dtype=np.int64)
    ys = np.sin(np.linspace(-1, 1, len(xs)))

    # A 2col x 2row canvas
    canvas = Canvas(2, 2, title=os.path.basename(__file__).replace('.py', ''))

    # A plot in top-left with 1 signal.
    signal11 = SignalXY(label="Signal1.1",
                        hi_precision_data=True)
    signal11.set_data([xs, ys])
    plot11 = PlotXY(plot_title="DateTime=True, HiPrecision=True")
    plot11.axes[0].is_date = True
    plot11.add_signal(signal11)
    canvas.add_plot(plot11, 0)

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
    canvas.add_plot(plot12, 0)

    # A plot in top-right with 1 signal.
    signal21 = SignalXY(label="Signal2.1",
                        hi_precision_data=True)
    signal21.set_data([xs, ys])
    plot21 = PlotXY(plot_title="DateTime=True, HiPrecision=True")
    plot21.axes[0].is_date = True
    plot21.add_signal(signal21)
    canvas.add_plot(plot21, 1)

    # A plot in bottom-right with 1 signal.
    signal22 = SignalXY(label="Signal2.2")
    signal22.set_data([xs, ys])
    plot22 = PlotXY(plot_title="DateTime=True, HiPrecision=True")
    plot22.axes[0].is_date = True
    plot22.add_signal(signal22)
    canvas.add_plot(plot22, 1)

    return canvas
