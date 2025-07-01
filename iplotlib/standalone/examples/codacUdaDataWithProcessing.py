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
Demonstrate usage of iplotlib by plotting data obtained from a CODAC-UDA server and processing it with iplotProcessing.
"""

import os
from iplotlib.core.axis import LinearAxis
from iplotlib.core import Canvas, PlotXY, SignalXY


def get_canvas():
    s1 = SignalXY(data_source='codacuda',
                  name='UTIL-SYSM-COM-4503-UT:SRV3602-NRBPS',
                  alias='36nrp',
                  ts_start='2021-10-01T01:00:00',
                  ts_end='2021-10-05T08:00:00',
                  plot_type="PlotXY")
    s2 = SignalXY(data_source='codacuda',
                  name='UTIL-SYSM-COM-4503-UT:SRV6102-NRBPS',
                  alias='61nrp',
                  ts_start='2021-10-01T01:00:00',
                  ts_end='2021-10-05T08:00:00',
                  plot_type="PlotXY")
    s3 = SignalXY(data_source='codacuda',
                  name='UTIL-SYSM-COM-4503-UT:SRV3302-NRBPS',
                  alias='33nrp',
                  ts_start='2021-10-01T01:00:00',
                  ts_end='2021-10-05T08:00:00',
                  plot_type="PlotXY")
    s4 = SignalXY(name='${36nrp}+${61nrp}+${33nrp}', plot_type="PlotXY")

    # Setup the graphics objects for plotting.
    c = Canvas(rows=4, title=os.path.basename(__file__).replace('.py', ''))

    p1 = PlotXY(axes=[LinearAxis(is_date=True), [LinearAxis(autoscale=True)]])
    p1.add_signal(s1)
    c.add_plot(p1)

    p2 = PlotXY(axes=[LinearAxis(is_date=True), [LinearAxis(autoscale=True)]])
    p2.add_signal(s2)
    c.add_plot(p2)

    p3 = PlotXY(axes=[LinearAxis(is_date=True), [LinearAxis(autoscale=True)]])
    p3.add_signal(s3)
    c.add_plot(p3)

    p4 = PlotXY(axes=[LinearAxis(is_date=True), [LinearAxis(autoscale=True)]])
    p4.add_signal(s4)
    c.add_plot(p4)
    s4.get_data()

    return c
