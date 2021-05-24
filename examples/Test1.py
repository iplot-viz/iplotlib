import sys

import pandas

from iplotlib.core.axis import LinearAxis
from access.dataAccess import DataAccess
from iplotlib.data_access.dataAccessSignal import AccessHelper, DataAccessSignal
from iplotlib.core.canvas import Canvas
from iplotlib.core.plot import PlotXY
from iplotlib.core.signal import ArraySignal
from iplotlib.qt.qtStandalonePlotCanvas import QStandaloneCanvas

da = DataAccess()

AccessHelper.da = da

# we load the data source conf files
listDS = da.loadConfig()
defDS = da.getDefaultDSName()
if len(listDS) < 1:
    print("no data sources found, exiting")
    sys.exit(-1)

signal1 = None
signal2 = None
signal3 = None
# IC-ICH1-DSRF:FWD - nanosecond data
# Example with delta = 600ns
signal1 = DataAccessSignal(datasource="codacuda", varname="IC-ICH1-DSRF:FWD", ts_start=1536852149738895586, ts_end=1536852149738896186)
# Example with delta = 600 ns
# signal1 = DataAccessSignal(datasource="codacuda", varname="IC-ICH1-DSRF:FWD", ts_start=1536852149738095586, ts_end=1536852149738999186)
# Example with delta = 171099992736 ns
# signal1 = DataAccessSignal(datasource="codacuda", varname="IC-ICH1-DSRF:FWD", ts_start=1536852149738895586, ts_end=1536853149738899586)

#
# signal1 = DataAccessSignal(datasource="codacuda", varname="IC-ICH1-DSRF:FWD", pulsenb=123456, ts_relative=True)


# signal1 = DataAccessSignal(datasource="codacuda", varname="D2-Q0-Q100:DQADRDPTP1-MROV4", pulsenb=12522)
# signal2 = DataAccessSignal(datasource="codacuda", varname="D2-Q0-Q100:DQADRDPTP2-MROV4", pulsenb=12522, color="red")
#
# signal3 = ArraySignal(color="blue")
# signal3.set_data([[1600327627340000000, 1600328627340000000, 1600329627340000000], [2550, 2600, 2580]])




# signal1 = DataAccessSignal(datasource="codacuda", varname="IC-ICH1-DSRF:FWD", pulsenb=123456, ts_relative=True)
plot1 = PlotXY(grid=True, axes=[LinearAxis(is_date=True), LinearAxis()])

plot1.add_signal(signal1)
plot1.add_signal(signal3)

plot2 = PlotXY()
plot2.add_signal(signal2)

canvas = Canvas(rows=2)
canvas.add_plot(plot1)
canvas.add_plot(plot2)

canvas.set_mouse_mode(Canvas.MOUSE_MODE_PAN)

# One liner, but no possibility to change mpl objects
# QStandaloneCanvas(impl_name="MATPLOTLIB", canvas=canvas).run()

# Less brief invocation that allows to access and modify qt/matplotlib objects before shown
c = QStandaloneCanvas(impl_name="MATPLOTLIB", canvas=canvas)
c.prepare()
print(F"Processed matplotlib figure: {c.impl.figure_canvas.figure}")
c.show()


