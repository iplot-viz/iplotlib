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
Demonstrate usage of iplotlib by plotting simple user-defined data.
"""

import os
import numpy as np
from iplotlib.core import SignalXY, Canvas, PlotXY


def get_canvas():
    # 1-D plot of Rosenbrock function @ y=2
    x = np.linspace(-1, 1, 1000)
    y = (1 - x ** 2) + 100 * (2 - x ** 2) ** 2
    s = SignalXY(label='signal_1')
    s.set_data([x, y])

    # Setup the graphics objects for plotting.
    c = Canvas(rows=3, title=os.path.basename(__file__).replace('.py', ''))
    p = PlotXY()
    p.add_signal(s)
    c.add_plot(p)

    return c
