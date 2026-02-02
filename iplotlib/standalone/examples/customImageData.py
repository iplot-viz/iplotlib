"""
Demonstrate usage of iplotlib by plotting simple user-defined data.
"""

import os
import numpy as np
from docutils.nodes import title

from iplotlib.core import SignalXY, Canvas, PlotXY, PlotImage


def get_canvas():
    # Seed
    np.random.seed(19680801)

    # Data
    delta = 0.025
    x = y = np.arange(-3.0, 3.0, delta)
    X, Y = np.meshgrid(x, y)
    Z1 = np.exp(-X ** 2 - Y ** 2)
    Z2 = np.exp(-(X - 1) ** 2 - (Y - 1) ** 2)
    Z = (Z1 - Z2) * 2

    A = np.random.rand(5, 5)

    # Setup the graphics objects for plotting.
    c = Canvas(rows=1, cols=2, title=os.path.basename(__file__).replace('.py', ''))

    s = SignalXY(label='signal_img')
    s.set_data([A])
    p1 = PlotImage(plot_title='origin = upper')
    p1.add_signal(s)
    c.add_plot(p1, 0)

    # Data signal 2
    s2 = SignalXY(label='signal_img_2')
    s2.set_data([A])
    p2 = PlotImage(plot_title='origin = lower', origin='lower')
    p2.add_signal(s2)
    c.add_plot(p2, 1)

    return c
