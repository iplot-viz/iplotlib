"""
Demonstrate usage of iplotlib by plotting data obtained from a CODAC-UDA server.
"""

import os
import tempfile

from iplotDataAccess.dataAccess import DataAccess

from iplotlib.core import Canvas, PlotXY
from iplotlib.core.axis import LinearAxis
from iplotlib.interface import AccessHelper, IplotSignalAdapter

dscfg = """[codacuda]
conninfo=host=io-ls-udafe01.iter.org,port=3090
varprefix=
rturl=http://io-ls-udaweb1.iter.org/dashboard/backend/sse
rtheaders=REMOTE_USER:$USERNAME,User-Agent:python_client
rtauth=None
"""

def plot():
    da = DataAccess()
    start_time = "2020-11-01T17:42:24"
    end_time = "2020-11-12T17:42:24"

    with tempfile.NamedTemporaryFile(mode='w+') as fp:
        fp.write(dscfg)
        fp.seek(0)
        os.environ.update({'DATASOURCESCONF': os.path.abspath(fp.name)})
        if len(da.loadConfig()) < 1:
            print("Invalid data source")
            return None

    AccessHelper.da = da
    s = IplotSignalAdapter(
        data_source='codacuda', 
        name='UTIL-HV-S22-BUS1:TOTAL_POWER', 
        ts_start=start_time,
        ts_end=end_time,
        processing_enabled=False
    )

    # Setup the graphics objects for plotting.
    c = Canvas(rows=3, title=os.path.basename(__file__).replace('.py', ''))
    p = PlotXY(axes = [LinearAxis(is_date=True), LinearAxis()])
    p.add_signal(s)
    c.add_plot(p)

    return c
