"""
Demonstrate usage of iplotlib by plotting simple user-defined data.
"""

import os
import numpy as np
from iplotlib.core import SimpleSignal, Canvas, PlotXY


def get_canvas():
    # 1-D plot of Rosenbrock function @ y=2
    x = np.linspace(-1, 1, 1000)
    y = (1 - x ** 2) + 100 * (2 - x ** 2) ** 2
    s = SimpleSignal(label='signal_1', x_data=x, y_data=y)

    # Setup the graphics objects for plotting.
    c = Canvas(rows=3, title=os.path.basename(__file__).replace('.py', ''))
    p = PlotXY()
    p.add_signal(s)
    c.add_plot(p)

    return c
