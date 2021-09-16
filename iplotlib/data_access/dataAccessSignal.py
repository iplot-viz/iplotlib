from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
import os
import numpy as np

from iplotlib.core.signal import ArraySignal
from iplotProcessing.core import Context as ProcessingContext
from iplotProcessing.core import BufferObject as ProcessingBufferObject
from iplotProcessing.core import Signal as ProcessingSignal
from iplotProcessing.tools import hash_code

import iplotLogging.setupLogger as sl

logger = sl.get_logger(__name__, level="DEBUG")

@dataclass
class DataAccessSignal(ArraySignal, ProcessingSignal):
    pulse_nb: int = None
    ts_start: int = None
    ts_end: int = None
    dec_samples: int = None
    ts_relative: bool = False
    envelope: bool = False
    x_expr: str = ''
    y_expr: str = ''
    z_expr: str = ''

    def __post_init__(self):
        ProcessingSignal.__post_init__(self)
        ArraySignal.__post_init__(self)
    
        if self.ts_start is not None:
            self.ts_start = np.datetime64(self.ts_start, 'ns').astype('int64').item() if isinstance(self.ts_start, str) else self.ts_start

        if self.ts_end is not None:
            self.ts_end = np.datetime64(self.ts_end, 'ns').astype('int64').item() if isinstance(self.ts_end, str) else self.ts_end

        if self.title is None:
            self.title = self.name if self.name != 'noname' else ''

        if self.pulse_nb is not None:
            self.title += ':' + str(self.pulse_nb)

        self.data_hash = None
        self.data_xrange = None, None

    @property
    def data(self):
        return self._data_store[0]

    @data.setter
    def data(self, val):
        self._data_store[0] = ProcessingBufferObject(input_arr=val)

    def fetch_data(self):
        if self.needs_refresh():
            CachingAccessHelper.get().fetch_data(self)

    def get_data(self):
        self_hash = hash_code(self, ["data_source", "name"])
        x_data = CachingAccessHelper.get().ctx.evaluate_expr(self.x_expr, self_hash, data_source=self.data_source)
        y_data = CachingAccessHelper.get().ctx.evaluate_expr(self.y_expr, self_hash, data_source=self.data_source)
        z_data = CachingAccessHelper.get().ctx.evaluate_expr(self.z_expr, self_hash, data_source=self.data_source)

        if len(x_data) > 1:
            self.data_xrange = self.time[0], self.time[-1]

        logger.debug(f"x_expr: {self.x_expr}, x.size: {len(x_data)}")
        logger.debug(f"y_expr: {self.y_expr}, x.size: {len(y_data)}")
        logger.debug(f"z_expr: {self.z_expr}, x.size: {len(z_data)}")

        return [x_data, y_data, z_data]

    def get_ranges(self):
        return [[self.ts_start, self.ts_end]]

    def set_ranges(self, ranges):
        def np_convert(value):
            if isinstance(value, np.generic):
                if isinstance(value, np.float64):
                    return value.astype('float').item()
                else:
                    return value.astype('int').item()
            else:
                return value

        self.ts_start = np_convert(ranges[0][0])
        self.ts_end = np_convert(ranges[0][1])

        # self.ts_start = ranges[0][0].astype(target_type).item() if isinstance(ranges[0][0], np.generic) else ranges[0][0]
        # self.ts_end = ranges[0][1].astype(target_type).item() if isinstance(ranges[0][0], np.generic) else ranges[0][1]

    def needs_refresh(self) -> bool:
        cur_hash = hash_code(self, ["ts_start", "ts_end", "dec_samples", "pulse_nb"])
        if self.data_hash != cur_hash:
            self.data_hash = cur_hash
            if self.dec_samples == -1 and self._check_if_zoomed_in():
                return False
            else:
                return True
        return False

    def _check_if_zoomed_in(self):
        """If dec_samples==-1 and we are zooming in there is no need to refresh data"""
        if all(e is not None for e in [self.data_xrange[0], self.data_xrange[1], self.ts_start, self.ts_end]):
            if self.data_xrange[0] < self.ts_start < self.data_xrange[1] and self.data_xrange[0] < self.ts_end < self.data_xrange[1]:
                return True
        return False

class AccessHelper:
    """
    A simple wrapper providing UDA data cache.
    For now we should only assume that data ranges are given by timestamps
    """

    async_enabled = False
    ctx = None # type: ProcessingContext
    da = None
    query_no = 0
    use_cache = False
    zoom_support = True
    num_samples = 1000
    key_params = []  # only this param keys will be used when creating cache key
    cache = {}

    pool = ProcessPoolExecutor()  # Multiprocess uses separate GIL for every forked process

    # Formats values as relative/absolute timestapms for UDA request or pretty print string

    def uda_ts(self, signal: DataAccessSignal, value):
        return value  # return str(np.datetime64(value, 'ns')) if not (signal.ts_relative or value is None) else value

    def str_ts(self, signal: DataAccessSignal, value):
        try:
            if value is not None:
                if type(value) == np.datetime64:
                    return value
                if (type(value) == int or type(value) == float) and value > 10**15:
                    return np.datetime64(value, 'ns')
        except:
            logger.error(f"Unable to convert value {value} to string timestamp")

        return value

    @staticmethod
    def get():
        return AccessHelper()

    def fetch_data(self, signal: DataAccessSignal):
        if not isinstance(signal, DataAccessSignal):
            logger.warning(f"{signal} is not an object of {type(DataAccessSignal)}")
            return

        # Evaluate self
        if signal.is_expression:
            sig_params = dict()
            for k in ["ts_start", "ts_end", "pulse_nb", "dec_samples", "envelope"]:
                sig_params.update({k: getattr(signal, k)})

            self.ctx.evaluate_signal(signal, lambda h, sig: print(h, sig), fetch_on_demand=True, **sig_params)
        else:
            self.fetch_data_submit(signal)

    def fetch_data_submit(self, signal: DataAccessSignal):
        logger.debug("[UDA {}] Get data: {} ts_start={} ts_end={} pulse_nb={} nbsamples={} relative={}".format(self.query_no, signal.name, self.str_ts(signal, signal.ts_start), self.str_ts(signal, signal.ts_end),
                                                                                           signal.pulse_nb, signal.dec_samples or self.num_samples, signal.ts_relative))
        self.query_no += 1

        if self.async_enabled:
            return self.pool.submit(self._fetch_data, signal)
        else:
            return self._fetch_data(signal)

    def _fetch_data(self, signal: DataAccessSignal):
        common_params = dict(dataSName=signal.data_source, varname=signal.name, nbp=signal.dec_samples or AccessHelper.num_samples)

        def np_nvl(arr):
            return np.empty(0) if arr is None else np.array(arr)

        if (signal.ts_start is not None and signal.ts_end is not None) or signal.pulse_nb is not None:
            data_params = dict(pulse=signal.pulse_nb, tsS=self.uda_ts(signal, signal.ts_start), tsE=self.uda_ts(signal, signal.ts_end), tsFormat="relative" if signal.ts_relative else "absolute")

            if signal.envelope:
                (d_min, d_max) = AccessHelper.da.getEnvelope(**common_params, **data_params)

                xdata = np_nvl(d_min.xdata if d_min else None) if signal.ts_relative else np_nvl(d_min.xdata if d_min else None)

                signal.time = np_nvl(xdata)
                signal.data_primary = np_nvl(d_min.ydata if d_min else None)
                signal.data_secondary = np_nvl(d_max.ydata if d_max else None)
                signal.time_unit = d_min.xunit if d_min else ''
                signal.data_primary_unit = d_min.yunit if d_min else ''
                signal.data_secondary_unit = d_max.yunit if d_min else ''
    
            else:
                raw = AccessHelper.da.getData(**common_params, **data_params)

                xdata = np_nvl(raw.xdata) if signal.ts_relative else np_nvl(raw.xdata).astype('int')

                if len(xdata) > 0:
                    logger.debug(F"\tUDA samples: {len(xdata)} params={data_params}")
                    logger.debug(F"\tX range: d_min={xdata[0]} d_max={xdata[-1]} delta={xdata[-1]-xdata[0]} type={xdata.dtype}")
                else:
                    logger.info(F"\tUDA samples: {len(xdata)} params={data_params}")
                
                signal.time = xdata
                signal.data_primary = np_nvl(raw.ydata)
                signal.data_secondary = np.empty(0).astype('double')
                signal.time_unit = raw.xunit
                signal.data_primary_unit = raw.yunit
                signal.data_secondary_unit = ''
        else:
            signal.time = np.empty(0) if signal.ts_relative else np.empty(0).astype('int')
            signal.data_primary =  np.empty(0).astype('double')
            signal.data_secondary =  np.empty(0).astype('double')
            signal.time_unit = ''
            signal.data_primary_unit = ''
            signal.data_secondary_unit = ''
        
        logger.debug(f"signal.time: {signal.time.size}")
        logger.debug(f"signal.data_primary: {signal.data_primary.size}")
        logger.debug(f"signal.data_secondary: {signal.data_secondary}")


class CachingAccessHelper(AccessHelper):
    KEY_PROP_NAMES = ["var_name", "ts_start", "ts_end", "pulse_nb", "dec_samples", "data_source", "envelope", "ts_relative"]
    CACHE_PREFIX = "/tmp/cache_"

    def __init__(self, enable_cache=False):
        self.enable_cache = enable_cache

    @staticmethod
    def get():
        return CachingAccessHelper()

    def _fetch_data(self, signal: DataAccessSignal):

        if self.enable_cache:
            cached = self._cache_fetch(signal)
            if cached is not None:
                logger.info(F"HIT: {self._cache_filename(signal)}")
                return cached
            else:
                logger.info(F"MISS: {self._cache_filename(signal)}")
                return self._cache_put(signal, super()._fetch_data(signal))
        else:
            return super()._fetch_data(signal)

    def _cache_filename(self, signal: DataAccessSignal):
        return "{}{}.npy".format(self.CACHE_PREFIX, hash_code(signal, self.KEY_PROP_NAMES))

    def _cache_fetch(self, signal: DataAccessSignal):
        filename = self._cache_filename(signal)
        return np.load(filename, allow_pickle=True) if os.path.isfile(filename) else None

    def _cache_put(self, signal: DataAccessSignal, data):
        filename = self._cache_filename(signal)
        np.save(filename, data, allow_pickle=True)
        return data
