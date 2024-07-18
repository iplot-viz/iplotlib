"""
Demonstrate usage of iplotlib by plotting data obtained from a CODAC-UDA server and processing it with iplotProcessing.
"""

import os
from iplotlib.core.axis import LinearAxis
from iplotlib.interface import IplotSignalAdapter
from iplotlib.core import Canvas, PlotXY


def get_canvas():
    s1 = IplotSignalAdapter(data_source='codacuda',
                            name='UTIL-SYSM-COM-4503-UT:SRV3602-NRBPS',
                            alias='36nrp',
                            ts_start='2021-10-01T01:00:00',
                            ts_end='2021-10-05T08:00:00',
                            plot_type="PlotXY")
    s2 = IplotSignalAdapter(data_source='codacuda',
                            name='UTIL-SYSM-COM-4503-UT:SRV6102-NRBPS',
                            alias='61nrp',
                            ts_start='2021-10-01T01:00:00',
                            ts_end='2021-10-05T08:00:00',
                            plot_type="PlotXY")
    s3 = IplotSignalAdapter(data_source='codacuda',
                            name='UTIL-SYSM-COM-4503-UT:SRV3302-NRBPS',
                            alias='33nrp',
                            ts_start='2021-10-01T01:00:00',
                            ts_end='2021-10-05T08:00:00',
                            plot_type="PlotXY")
    s4 = IplotSignalAdapter(name='${36nrp}+${61nrp}+${33nrp}', plot_type="PlotXY")

    # Setup the graphics objects for plotting.
    c = Canvas(rows=4, title=os.path.basename(__file__).replace('.py', ''))

    p1 = PlotXY(axes=[LinearAxis(is_date=True), LinearAxis()])
    p1.add_signal(s1)
    c.add_plot(p1)

    p2 = PlotXY(axes=[LinearAxis(is_date=True), LinearAxis()])
    p2.add_signal(s2)
    c.add_plot(p2)

    p3 = PlotXY(axes=[LinearAxis(is_date=True), LinearAxis()])
    p3.add_signal(s3)
    c.add_plot(p3)

    p4 = PlotXY(axes=[LinearAxis(is_date=True), LinearAxis()])
    p4.add_signal(s4)
    c.add_plot(p4)
    s4.get_data()

    return c
