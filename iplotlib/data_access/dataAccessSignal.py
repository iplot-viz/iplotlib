import os
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
import numpy as np
from iplotlib.core.signal import ArraySignal
from proc.data import hash_code


import log.setupLogger as ls

logger = ls.get_logger(__name__)

@dataclass
class DataAccessSignal(ArraySignal):
    varname: str = None
    pulsenb: int = None
    ts_start: int = None
    ts_end: int = None
    dec_samples: int = None
    ts_relative: bool = False
    datasource: str = None
    envelope: bool = False

    def __post_init__(self):
        super().__post_init__()
        self.units = []
        self.data = []
        if self.ts_start is not None:
            self.ts_start = np.datetime64(self.ts_start, 'ns').astype('int').item() if isinstance(self.ts_start, str) else self.ts_start

        if self.ts_end is not None:
            self.ts_end = np.datetime64(self.ts_end, 'ns').astype('int').item() if isinstance(self.ts_end, str) else self.ts_end

        if self.title is None:
            self.title = self.varname or ''

        if self.pulsenb is not None:
            self.title += ':' + str(self.pulsenb)

        self.data_hash = None
        self.data = None

    def __str__(self):
        return "{}({}{}{}{}{})".format(self.__class__.__name__, self.varname, ', pulsenb=' + str(self.pulsenb) if self.pulsenb is not None else "",
                                       ', ts_start=' + str(np.datetime64(self.ts_start, 'ns')) if not (self.ts_start is None or self.ts_relative) else "",
                                       ', ts_end=' + str(np.datetime64(self.ts_end, 'ns')) if not (self.ts_end is None or self.ts_relative) else "", ', dec_samples=' + str(self.dec_samples))

    def get_data(self):
        cur_hash = self.calculate_data_hash()
        if self.data_hash != cur_hash:
            self.data_hash = cur_hash
            uda_record = CachingAccessHelper.get().get_data(self)
            self.units = uda_record[1]
            self.data = uda_record[0]

        return self.data

    def calculate_data_hash(self):
        # This hashcode is used to determine if we should perform new UDA request or not
        return hash_code(self, ["ts_start", "ts_end", "dec_samples", "pulsenb"])

    def get_ranges(self):
        return [[self.ts_start, self.ts_end]]

    def set_ranges(self, ranges):
        self.ts_start = ranges[0][0].astype('int').item() if isinstance(ranges[0][0], np.generic) else ranges[0][0]
        self.ts_end = ranges[0][1].astype('int').item() if isinstance(ranges[0][0], np.generic) else ranges[0][1]


class AccessHelper:
    """
    A simple wrapper providing UDA data cache.
    For now we should only assume that data ranges are given by timestamps
    """

    async_enabled = False

    da = None
    query_no = 0
    use_cache = False
    zoom_support = True
    num_samples = 1000
    key_params = []  # only this param keys will be used when creating cache key
    cache = {}

    pool = ProcessPoolExecutor()  # Multiprocess uses separate GIL for every forked process

    # pool = ThreadPoolExecutor()

    # Formats values as relative/absolute timestapms for UDA request or pretty print string

    def uda_ts(self, signal, value):
        return value  # return str(np.datetime64(value, 'ns')) if not (signal.ts_relative or value is None) else value

    def str_ts(self, signal, value):
        if value is not None and value > 10**15:
            return np.datetime64(value, 'ns')
        return value

    @staticmethod
    def get():
        return AccessHelper()

    def get_data(self, signal):
        logger.info("[UDA {}] Get data: {} ts_start={} ts_end={} pulsenb={} nbsamples={}".format(self.query_no, signal.varname, self.str_ts(signal, signal.ts_start), self.str_ts(signal, signal.ts_end),
                                                                                           signal.pulsenb, signal.dec_samples or self.num_samples))
        # logger.info(F"[UDA2: {float(signal.ts_start):.20f}")
        self.query_no += 1

        if self.async_enabled:
            return self.pool.submit(self._fetch_data, signal)
        else:
            return self._fetch_data(signal)

    def _fetch_data(self, signal):
        common_params = dict(dataSName=signal.datasource, varname=signal.varname, nbp=signal.dec_samples or AccessHelper.num_samples)

        def np_nvl(arr):
            return np.empty(0) if arr is None else np.array(arr)

        if (signal.ts_start is not None and signal.ts_end is not None) or signal.pulsenb is not None:
            data_params = dict(pulse=signal.pulsenb, tsS=self.uda_ts(signal, signal.ts_start), tsE=self.uda_ts(signal, signal.ts_end), tsFormat="relative" if signal.ts_relative else "absolute")

            if signal.envelope:
                (d_min, d_max) = AccessHelper.da.getEnvelope(**common_params, **data_params)

                xdata = np_nvl(d_min.xdata if d_min else None) if signal.ts_relative else np_nvl(d_min.xdata if d_min else None)

                return [np_nvl(xdata), np_nvl(d_min.ydata if d_min else None), np_nvl(d_max.ydata if d_max else None)], [d_min.xunit if d_min else None, d_min.yunit if d_min else None]
            else:
                raw = AccessHelper.da.getData(**common_params, **data_params)

                xdata = np_nvl(raw.xdata) if signal.ts_relative else np_nvl(raw.xdata).astype('int')
                logger.info(F"\tUDA samples: {len(xdata)} params={data_params}")
                if len(xdata) > 0:
                    logger.info(F"\tX range: d_min={xdata[0]} d_max={xdata[-1]} delta={xdata[-1]-xdata[0]} type={xdata.dtype}")
                    # logger.info(xdata)
                return [xdata, np_nvl(raw.ydata)], [raw.xunit, raw.yunit]
        else:
            # logger.info("RETURNING EMPTY DATA SET", type(np.empty(1)), type(np.empty(1).astype('datetime64[ns]')))
            return [np.empty(0) if signal.ts_relative else np.empty(0).astype('int'), np.empty(0).astype('double')], []


class CachingAccessHelper(AccessHelper):
    KEY_PROP_NAMES = ["varname", "ts_start", "ts_end", "pulsenb", "dec_samples", "datasource", "envelope", "ts_relative"]
    CACHE_PREFIX = "/tmp/cache_"

    def __init__(self, enable_cache=False):
        self.enable_cache = enable_cache

    @staticmethod
    def get():
        return CachingAccessHelper()

    def _fetch_data(self, signal):

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

    def _cache_filename(self, signal):
        return "{}{}.npy".format(self.CACHE_PREFIX, hash_code(signal, self.KEY_PROP_NAMES))

    def _cache_fetch(self, signal):
        filename = self._cache_filename(signal)
        return np.load(filename, allow_pickle=True) if os.path.isfile(filename) else None

    def _cache_put(self, signal, data):
        filename = self._cache_filename(signal)
        np.save(filename, data, allow_pickle=True)
        return data
