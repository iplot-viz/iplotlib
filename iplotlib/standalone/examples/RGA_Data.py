##################################################
#
# RGA Data viewer to operate within Mint.
#
# Author : P.J. L. Heesterman (Epsyl-Alcen)
#
##################################################


import os
import numpy as np
from iplotlib.core import SignalXY, SignalContour, Canvas, PlotXY, PlotContour
from iplotlib.data_access import CanvasStreamer
import epics
from threading import Thread, Event, Lock
from datetime import datetime
import logging
import copy
from enum import Enum

logging.basicConfig(level=logging.INFO, filename='RGA_Data_view.log',
                    format='%(asctime)s [%(levelname)5s] %(name)s: %(message)s', filemode="w")
logger = logging.getLogger('RGA_Data')

class DataType(Enum):
    DA_TYPE_FLOAT = 1
    DA_TYPE_DOUBLE = 2
    DA_TYPE_STRING = 3
    DA_TYPE_LONG = 4
    DA_TYPE_ULONG = 5
    DA_TYPE_CHAR = 6
    DA_TYPE_UCHAR = 7
    DA_TYPE_INT = 8
    DA_TYPE_UINT = 9
    DA_TYPE_SHORT = 10
    DA_TYPE_USHORT = 11

class DataCore:

    def __init__(self):
        self.xtype = None
        self.ytype = None
        self.ztype = None
        self.xlabel = ""
        self.ylabel = ""
        self.zlabel = ""
        self.xunit = ""
        self.yunit = ""
        self.zunit = ""
        self.drank = ""
        self.errcode = 0
        self.errdesc = None

    def set_a(self, xtype, ytype, ztype, xlabel, ylabel, zlabel, xunit, yunit, zunit, drank):
        if isinstance(xtype, DataType):
            self.xtype = xtype
        if isinstance(ytype, DataType):
            self.ytype = ytype
        if isinstance(ztype, DataType):
            self.ztype = ztype
        self.xlabel = xlabel
        self.ylabel = ylabel
        self.zlabel = zlabel
        self.xunit = xunit
        self.yunit = yunit
        self.zunit = zunit
        self.drank = drank
        self.errcode = 0
        self.errdesc = ""

    def set_empty(self, mess=None):
        self.errcode = -1
        self.errdesc = mess

    def clear_data(self):
        self.xtype = ""
        self.ytype = ""
        self.xlabel = ""
        self.ylabel = ""
        self.xunit = ""
        self.yunit = ""

        self.drank = ""
        self.errcode = 0
        self.errdesc = ""

    def set_err(self, errc, errd):
        self.errcode = errc
        self.errdesc = errd

    def get_err(self):
        return self.errcode, self.errdesc

class DataObj(DataCore):

    def __init__(self):
        super().__init__()

        self.xdata = []
        self.ydata = []
        self.zdata = []

    def set_data(self, data, dtype):
        if dtype == 1:
            self.xdata = data
        else:
            self.ydata = data

    def set_empty(self, mess=None):
        super().set_empty(mess)
        self.xdata = []
        self.ydata = []
        self.zdata = []

    def clear_data(self):
        super().clear_data()
        self.xdata = None
        self.ydata = None
        self.zdata = None

epics_data = None

class DataStore:
    """
    This class receives RGA data.
    """
    def __init__(self):
        CBS1 = "D2"
        CBS2 = "VLAB"
        CBS3 = "RGA1"
        self.prefix = CBS1+'-'+CBS2+'-'+CBS3+':'
        self._max_traces = 50
        self._trace_count = 0
        self._timestamp_count = 0
        self._y_cursor = 0
        self._x_cursor = None
        self._y_dobj = DataObj()
        self._y_dobj.set_a(1, 1, 0, "Mass", "Signal", None, "AMU", "Amp", None, 1)
        self._ts_start = None
        self._time_dobj = DataObj()
        self._time_dobj.set_a(1, 1, 0, "Time", "Signal", None, "sec", "Amp", None, 1)
        self._time_dobj.ydata = np.zeros(self._max_traces)
        self._time_dobj.xdata = np.zeros(self._max_traces)
        self._image_dobj = DataObj()
        self._image_dobj.set_a(1, 1, 1, "Mass", "Time", "Signal", "AMU", "sec", "Amp", 1)
        self._ydata_image = None
        self._ydata_event = Event()
        self._ydataPV = epics.PV(self.prefix + "Y_DATA0",
                                 connection_callback=DataStore.on_connection_change,
                                 callback=DataStore.on_y_value_change)
        self._xdata_event = Event()
        self._xdataPV = epics.PV(self.prefix + "X_DATA",
                                 connection_callback=DataStore.on_connection_change,
                                 callback=DataStore.on_x_value_change)
        self._timestamp_event = Event()
        self._timestampPV = epics.PV(self.prefix + "TIMESTAMP",
                                 connection_callback=DataStore.on_connection_change,
                                 callback=DataStore.on_timestamp_value_change)

    @staticmethod
    def on_connection_change(pvname=None, conn=None, **kws):
        logger.info('PV connection status changed: %s %s', pvname, repr(conn))
        
    @staticmethod
    def on_y_value_change(pvname=None, value=None, host=None, **kws):
        """
        This callback method is called when the Y_DATA0 value changes.
        """
        cls = epics_data
        if type(value) == float:
            len_value = 1
        else:
            len_value = len(value)
        logger.info('Y PV value changed: %s (%s) size=%d at %d', pvname, host, len_value, cls._trace_count)
        if len_value > 0:
            ydata_event = cls._ydata_event
            if ydata_event.is_set():
                logger.warning('Y PV event was already set')
            if cls._trace_count >= cls._max_traces:
                logger.warning('Y trace count exceeded')
                return
            if cls._ydata_image is None:
                cls._ydata_image = np.zeros((cls._max_traces, len_value))
                cls._image_dobj.zdata = cls._ydata_image
            if len_value == 1:
                cls._ydata_image[cls._trace_count] = np.array([value])
            else:
                cls._ydata_image[cls._trace_count] = copy.deepcopy(value)
            cls._y_dobj.ydata = cls._ydata_image[cls._y_cursor]
            if cls._x_cursor is None:
                cls._x_cursor = np.argmax(cls._ydata_image[cls._trace_count])
            for trace in range(cls._max_traces):
                cls._time_dobj.ydata[trace] = cls._ydata_image[trace][cls._x_cursor]
            cls._trace_count += 1
            cls._y_cursor += 1
            if cls._trace_count >= cls._max_traces:
                logger.info('Removing Y data callback')
                cls._ydataPV.clear_callbacks()
            ydata_event.set()

    @staticmethod
    def on_x_value_change(pvname=None, value=None, host=None, **kws):
        """
        This callback method is called when the X_DATA value changes.
        """
        cls = epics_data
        if type(value) == float:
            len_value = 1
        else:
            len_value = len(value)
        xdata_event = cls._xdata_event
        logger.info('X PV value changed: %s (%s) size=%d at %d' % (pvname, host, len_value, cls._trace_count))
        if len_value > 0:
            if xdata_event.is_set():
                logger.warning('X PV event was already set')
            if cls._trace_count >= cls._max_traces:
                logger.warning('X trace count exceeded')
                cls._xdataPV.clear_callbacks()
                return
            if cls._ydata_image is None:
                cls._ydata_image = np.zeros((cls._max_traces, len_value))
                cls._image_dobj.zdata = cls._ydata_image

            if len_value == 1:
                cls._y_dobj.xdata = np.array([value])
            else:
                cls._y_dobj.xdata  = copy.deepcopy(value)
            cls._image_dobj.xdata = cls._y_dobj.xdata
            if cls._trace_count >= cls._max_traces:
                logger.info('Removing X data callback')
                cls._xdataPV.clear_callbacks()
            xdata_event.set()

    @staticmethod
    def on_timestamp_value_change(pvname=None, value=None, host=None, **kws):
        """
        This callback method is called when the TIMESTAMP value changes.
        """
        cls = epics_data
        timestamp_event = cls._timestamp_event
        if cls._ts_start is None:
            cls._ts_start = value
            logger.info('TS START initialised to ' + str(cls._ts_start))
        timestamp = value - cls._ts_start
        logger.info('TIMESTAMP PV value changed: %s (%s) value=%f timestamp=%f at %d' % (pvname, host, value, timestamp, cls._timestamp_count))
        if timestamp_event.is_set():
            logger.warning('TIMESTAMP PV event was already set')
        if cls._timestamp_count >= cls._max_traces:
            logger.warning('Timestamp trace count exceeded')
            return
            
        cls._time_dobj.xdata[cls._timestamp_count] = timestamp
        cls._image_dobj.ydata = cls._time_dobj.xdata
        cls._timestamp_count += 1
        if cls._timestamp_count >= cls._max_traces:
            logger.info('Removing timestamp callback')
            cls._timestampPV.clear_callbacks()
        timestamp_event.set()
        
    def get_next_data(self, ds, vname):
        """ This method is called by CanvasStreamer to retrieve the next signal data values.
            It can block waiting for new data to be available.
        """
        dobj = None
        logger.info('get_next_data ' + vname + ' ' + str(self._y_cursor) + ' ' + str(self._x_cursor))
        if vname == self.prefix + "MASS":
            self._ydata_event.wait()
            dobj = self._y_dobj
            self._ydata_event.clear()
        elif vname == self.prefix + "TIME":
            self._timestamp_event.wait()
            dobj = self._time_dobj
            self._timestamp_event.clear()
        elif vname == self.prefix + "IMAGE":
            self._xdata_event.wait()
            dobj = self._image_dobj
            self._xdata_event.clear()
        else:
            logger.warning('Unknown PV name ' + vname)
            
        return dobj
    
    def get_timestamp(self):
        # This method reads data timestamps from the timestamp data array.
        if self._timestamp_count <= 1:
            ts_start = self._ts_start
            if self._timestamp_count == 0:
                now = datetime.now()
                ts_end = now.timestamp()
            else:
                ts_end = self._time_dobj.xdata[self._timestamp_count-1] + self._ts_start
        else:
            ts_start = self._time_dobj.xdata[self._timestamp_count-2] + self._ts_start
            ts_end = self._time_dobj.xdata[self._timestamp_count-1] + self._ts_start
        return ts_start, ts_end
    
    @staticmethod
    def stream_callback(signal):
        """ This method is called by CanvasStreamer after calling get_next_data.
            It applies timestamps to the signal.
            If these are updated, the data will be treated as needing refresh.
        """
        cls = epics_data
        ts_start, ts_end = cls.get_timestamp()
        signal.ts_start = ts_start
        signal.ts_end = ts_end
        logger.info('stream_callback ' + signal.name + ' ts_start ' + str(signal.ts_start) + ' ts_end ' +  str(signal.ts_end))
    
    def start_subscription(self, ds, params=None):
        logger.info('start_subscription' + str(params))
        self.wait_for_data()
    def stop_subscription(self):
        logger.info('stop_subscription')
        
    def wait_for_connection(self, timeout=None):
        self._ydataPV.wait_for_connection(timeout)
        self._xdataPV.wait_for_connection(timeout)
        self._timestampPV.wait_for_connection(timeout)
        
    def wait_for_data(self, timeout=None):
        self._ydata_event.wait(timeout)
        self._xdata_event.wait(timeout)
        self._timestamp_event.wait(timeout)
        
    def clear_data_events(self):
        self._ydata_event.clear()
        self._xdata_event.clear()
        self._timestamp_event.clear()
        
epics_data = DataStore()

def get_canvas():
    # Setup the graphics objects for plotting.
    epics_data.wait_for_connection()
    for event in range(epics_data._max_traces-1):
        # We block here waiting for completion of the data.
        # This is because view streaming is not available yet.
        # Consequently, it only displays the data on completion.
        epics_data.wait_for_data()
        epics_data.clear_data_events()
    epics_data.wait_for_data()
    
    canvas = Canvas(rows=2, cols=2, title=os.path.basename(__file__).replace('.py', ''))
    canvas.streaming = True
    
    # This is the XY data image, currently as a contour plot.
    # This should be replaced by an actual image that is easier to view.
    signal_image = SignalContour(name=epics_data.prefix+"IMAGE", data_access_enabled=True)
    plot_image = PlotContour()
    plot_image.add_signal(signal_image)
    canvas.add_plot(plot_image, 0)
    # This is the timestamp data as a plot.
    signal_time = SignalXY(name=epics_data.prefix+"TIME", data_access_enabled=True)
    plot_time = PlotXY()
    plot_time.add_signal(signal_time)
    canvas.add_plot(plot_time, 1)
    # This is the mass signal data as a plot.
    signal_mass = SignalXY(name=epics_data.prefix+"MASS", data_access_enabled=True)
    plot_mass = PlotXY()
    plot_mass.add_signal(signal_mass)
    canvas.add_plot(plot_mass, 0)

    streamer = CanvasStreamer(epics_data, False)
    streamer.start(canvas, epics_data.stream_callback)
    logger.info('Canvas is streaming ' + str(canvas.streaming))

    return canvas
