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
Demonstrate usage of iplotlib by plotting data obtained from a CODAC-UDA server.
"""

import os
import tempfile

from iplotDataAccess.dataAccess import DataAccess

from iplotlib.core import Canvas, PlotXY, SignalXY
from iplotlib.core.axis import LinearAxis
from iplotlib.interface import AccessHelper

dscfg = """[codacuda]
conninfo=host=io-ls-udasrv1.iter.org,port=3090
varprefix=
rturl=http://io-ls-udaweb1.iter.org/dashboard/backend/sse
rtheaders=REMOTE_USER:$USERNAME,User-Agent:python_client
rtauth=None
default=true
"""


def get_canvas():
    da = DataAccess()
    start_time = "2024-03-19T17:42:24"
    end_time = "2024-03-26T17:42:24"

    with tempfile.NamedTemporaryFile(mode='w+') as fp:
        fp.write(dscfg)
        fp.seek(0)
        os.environ.update({'IPLOT_SOURCES_CONFIG': os.path.abspath(fp.name)})
        if da.load_config(fp.name):
            AccessHelper.da = da
            s = SignalXY(
                data_source='codacuda',
                name='UTIL-HV-S22-BUS1:TOTAL_POWER',
                ts_start=start_time,
                ts_end=end_time,
                processing_enabled=False
            )

            # Setup the graphics objects for plotting.
            c = Canvas(rows=3, title=os.path.basename(__file__).replace('.py', ''))
            p = PlotXY(axes=[LinearAxis(is_date=True), [LinearAxis(autoscale=True)]])
            p.add_signal(s)
            c.add_plot(p)

            return c
        else:
            print("Invalid data source")
            return None
