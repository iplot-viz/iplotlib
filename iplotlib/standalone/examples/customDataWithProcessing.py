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
Demonstrate usage of iplotlib by plotting simple user-defined data combined with data processing.
"""

import numpy as np
import os
from iplotlib.core import Canvas, PlotXY, SignalXY


def func(x):
    return np.sin(10 * np.arcsin(1.) * x) * np.linspace(np.min(x), np.max(x), x.size)


def get_canvas():
    x = np.linspace(-1, 1, 1000)

    # Basic processing of signals with similar data dimensions and data bounds
    # 1. s1.x.shape == s1.y.shape == s2.x.shape == s2.y.shape == s3.x.shape == s3.y.shape
    # 2. min(s1.x) == min(s2.x) && min(s3.x)
    # 3. max(s1.x) == max(s2.x) && max(s3.x)
    s1 = SignalXY(name='s1',
                  alias='s1a',
                  data_access_enabled=False,
                  plot_type="PlotXY")
    s1.set_data([x, func(x)])

    s2 = SignalXY(name='s2',
                  alias='s2a',
                  data_access_enabled=False,
                  plot_type="PlotXY")
    s2.set_data([x, func(x) + 100])

    s3 = SignalXY(name='s3', alias='s3a',
                  data_access_enabled=False,
                  plot_type="PlotXY")
    s3.set_data([x, func(x) + 200])

    s4 = SignalXY(name='${s1a} + ${s2a} + ${s3a}',
                  data_access_enabled=False,
                  plot_type="PlotXY")

    s5 = SignalXY(name='np.sin(${s1a} + ${s2a} + ${s3a})',
                  data_access_enabled=False,
                  plot_type="PlotXY")

    # A little advanced usage of the signal object in the x, y, .. fields
    s6 = SignalXY(name='s6: x=x-10, y=np.sin(y * np.linspace(0, 1, np.size(y))',
                  x_expr='${self}.time - 10',
                  y_expr='np.sin(${self}.data * np.linspace(0, 1, np.size(${self}.data)))',
                  data_access_enabled=False,
                  plot_type="PlotXY")
    s6.set_data([x, func(x)])

    # Setup the graphics objects for plotting.
    c = Canvas(rows=2, cols=2, title=os.path.basename(__file__).replace('.py', ''))
    p1 = PlotXY()
    p1.add_signal(s1)
    p1.add_signal(s2)
    p1.add_signal(s3)
    c.add_plot(p1)

    p3 = PlotXY()
    p3.add_signal(s6)
    c.add_plot(p3)

    p2 = PlotXY(row_span=2)
    p2.add_signal(s4)
    p2.add_signal(s5)
    c.add_plot(p2, col=1)

    return c
