# Description: Extend Data-Access, Data-Processing to self-aware iplotlib.core.Signal
# Author: Abadie Lana
# Changelog:
#   Sept 2021: -Inherit from ArraySignal and ProcessingSignal [Jaswant Sai Panchumarti]
#              -Added attributes for x, y, z expression fields. [Jaswant Sai Panchumarti]
#              -Extract data-access code into fetch_data method. [Jaswant Sai Panchumarti]
#              -Apply processing right after data access in fetch_data [Jaswant Sai Panchumarti]
#              -Teach AccessHelper to explore ProcessingSignal objects. [Jaswant Sai Panchumarti]
#              -Rename AccessHelper.get_data -> AccessHelper._fetch_data (no longer returns data) [Jaswant Sai Panchumarti]
#              -Translate iplotDataAccess.DataObj into ProcessingSignal in AccessHelper._fetch_data [Jaswant Sai Panchumarti]

from concurrent.futures import Future, ProcessPoolExecutor, as_completed, wait
from dataclasses import dataclass, field, fields
from iplotProcessing.common.errors import InvalidExpression

import numpy as np
import os
import typing

from iplotlib.core.signal import ArraySignal
from iplotProcessing.core import BufferObject
from iplotProcessing.core import Signal as ProcessingSignal
from iplotProcessing.tools.parsers import Parser
from iplotProcessing.tools import hash_code

import iplotLogging.setupLogger as sl

logger = sl.get_logger(__name__, level="INFO")

IplotSignalAdapterT = typing.TypeVar(
    'IplotSignalAdapterT', bound='IplotSignalAdapter')



class DataAccessError(Exception):
    pass


class Result:
    BUSY = 'Busy'
    INVALID = 'Invalid'
    FAIL = 'Fail'
    READY = 'Ready'
    SUCCESS = 'Success'


@dataclass
class StatusInfo:
    da_msg: str = ''
    num_points: int = 0
    proc_msg: str = ''
    result: Result = Result.READY
    sep = ' | '

    def reset(self):
        self.da_msg = ''
        self.num_points = 0
        self.proc_msg = ''
        self.result = Result.READY

    def __str__(self) -> str:
        msg = f"{self.result}"
        if self.da_msg:
            msg += self.sep + f"Data access: {self.da_msg}"
        if self.proc_msg:
            msg += self.sep + f"Processing: {self.proc_msg}"
        if self.result not in [Result.READY, Result.BUSY]:
            msg += self.sep + f"{self.num_points} points"

        return msg


@dataclass
class IplotSignalAdapter(ArraySignal, ProcessingSignal):
    """This is an adapter class that is the culmination of two crucial classes in the iplotlib framework. 
        It's purpose is to make ProcessingSignal interface compatible with the ArraySignal interface.

        Warning: Consider this class as a frozen blueprint, i.e, do not expect it to be consistent once
        some of the parameters are modified after initialization. Such parameters are name, alias, 
        data_access_enabled, processing_enabled
    """
    data_source: str = ''
    name: str = ''
    alias: str = ''

    pulse_nb: int = None
    ts_start: int = None
    ts_end: int = None
    ts_relative: bool = False
    envelope: bool = False

    x_expr: str = '${self}.time'
    y_expr: str = '${self}.data'
    z_expr: str = '${self}.data_secondary'

    plot_type: str = ''

    children: typing.List[IplotSignalAdapterT] = field(default_factory=list)

    status_info: StatusInfo = None

    data_access_enabled: bool = True
    processing_enabled: bool = True

    time_out_value: float = 60

    def __post_init__(self):
        super().__post_init__()
        ProcessingSignal.__init__(self)

        # 1. Initialize access parameters
        if isinstance(self.ts_start, str):
            self.ts_start = np.datetime64(
                self.ts_start, 'ns').astype('int64').item()

        if isinstance(self.ts_end, str):
            self.ts_end = np.datetime64(
                self.ts_end, 'ns').astype('int64').item()

        self.ts_relative = self.pulse_nb is not None

        # 2. Post-initialize ArraySignal's properties and our name.
        self._init_title()

        # 3. Help keep track of data access parameters.
        self.access_md5sum = None
        self.data_xrange = None, None

        # 4. Parse name and prepare a hierarchy of objects if needed.
        self.status_info = StatusInfo()
        self.status_info.reset()
        self.status_info.result = Result.BUSY
        #
        # 4.1. name can be an expression.
        # eg: ${foo}
        # eg: ${foo} + ${bar} + ${baz} * np.max(${cat})
        # eg: np.max(${foo} + ${bar}) * np.ones((${foo}.data.size))
        #
        # 4.2. name can be a string of plain text r"^[ A-Za-z0-9_@.\/\[\]#&+-]*"
        # eg: foo
        # eg: foo_bar
        # eg: bar_
        # eg: foo-bar-baz2-l3-1
        # eg: foo_bar_baz2_l3_1
        # eg: foo/bar[0]/baz_1
        # eg: foo/bar[0]/baz-1
        #
        # The second case cannot have children, it does not need special consideration.

        # The first case would result in len(children) > 0. We find them (if they are pre-defined aliases) or create them.
        p = Parser().set_expression(self.name)
        if p.is_valid:
            for key in p.var_map.keys():
                value = ParserHelper.env.get(key)

                if isinstance(value, IplotSignalAdapter):
                    if self.data_access_enabled and len(self.data_source) and self.data_source != value.data_source:
                        self.status_info.reset()
                        self.status_info.da_msg = f"Data source conflict {self.data_source} != {value.data_source}."
                        self.status_info.result = Result.INVALID
                        logger.warning(self.status_info.da_msg)
                        break
                    self.children.append(value)
                else:
                    if self.data_access_enabled and (not len(self.data_source) or self.data_source.isspace()):
                        self.status_info.reset()
                        self.status_info.da_msg = "Data source unspecified."
                        self.status_info.result = Result.INVALID
                        logger.warning(self.status_info.da_msg)
                        break
                    elif self.data_access_enabled:
                        # Construct a new instance with our data source and time range, etc..
                        child = self._construct_named_offspring(key)
                        self.children.append(child)
                    elif self.processing_enabled:
                        # Cannot create a new instance without alias in this case.
                        self.status_info.reset()
                        self.status_info.proc_msg = f"Specified name '{key}' is not a pre-defined alias!"
                        self.status_info.result = Result.INVALID
                        logger.warning(self.status_info.proc_msg)
                        break

        if self.status_info.result == Result.INVALID:
            return
        else:
            # Add a reference to our alias.
            if isinstance(self.alias, str) and len(self.alias) and not self.alias.isspace():
                ParserHelper.env.update({self.alias: self})

            # Indicate readiness.
            self.status_info.result = Result.READY

    def _construct_named_offspring(self, name: str) -> IplotSignalAdapterT:
        cls = type(self)
        kwargs = dict()

        for f in fields(self):
            kwargs.update({f.name: getattr(self, f.name)})
        kwargs.update({'name': name})
        kwargs.update({'title': ''})
        kwargs.update({'children': []})
        return cls(**kwargs)

    def _init_title(self):
        # 1. From name
        if self.title is None:
            if isinstance(self.name, str) and not self.name.isspace() and len(self.name):
                self.title = self.name
            else:
                self.title = ''

        # 2. Alias overrides name for the title (appears in legend box)
        if isinstance(self.alias, str) and not self.alias.isspace() and len(self.alias):
            self.title = self.alias

        # 3. Shows the pulse number in the title (appears in legend box).
        if self.pulse_nb is not None:
            if not self.title.find(str(self.pulse_nb)):
                self.title += ':' + str(self.pulse_nb)

    def set_data(self, data=None):
        """Set the internal buffers for `time`, `data_primary` and `data_secondary`

        :param data: A collection of data buffers, defaults to None
        :type data: List[BufferObject], optional
        :return: None
        :rtype: NoneType
        """
        if data is None:
            super().set_data()

        # 1. Fill in data buffers
        if isinstance(data, typing.Collection):
            if len(data):
                if all([isinstance(val, np.ndarray) for val in data]):
                    for i, name in enumerate(['time', 'data_primary', 'data_secondary']):
                        try:
                            setattr(self, name, data[i])
                        except IndexError:
                            break

        # 2. Update x range
        if len(self.time) > 1:
            self.data_xrange = self.time[0], self.time[-1]

        # 3. Fix x-y shape mismatch.
        self.acquire_shape(self.data_primary, self.time)

        # 4. Fix x-z shape mismatch.
        self.acquire_shape(self.data_secondary, self.time)

        # 5. Set appropriate status.
        self.status_info.reset()
        self.status_info.num_points = len(self.time)
        self.status_info.result = Result.SUCCESS

        logger.debug(f"x.size: {len(self.time)}")
        logger.debug(f"y.size: {len(self.data_primary)}")
        logger.debug(f"z.size: {len(self.data_secondary)}")

        logger.debug(f"x.unit: {self.time_unit}")
        logger.debug(f"y.unit: {self.data_primary_unit}")
        logger.debug(f"z.unit: {self.data_secondary_unit}")

    @staticmethod
    def acquire_shape(source: BufferObject, target: BufferObject) -> BufferObject:
        """Modify `source` such that shape(`source`) == shape(`target`)

        :param source: This object will acquire its shape from `target` if it is not the same.
        :type source: BufferObject
        :param target: This object will dictate the shape of `source`
        :type target: BufferObject
        :return: The new modifed `source` object.
        :rtype: BufferObject
        """
        if np.isscalar(source):
            return BufferObject([source] * len(target))
        elif target.ndim == source.ndim:
            if len(source) != len(target) and len(source) == 1:
                logger.warning(
                    f"Caught x-target shape mismatch! Fixing it. len(source) = {len(source)} -> {len(target)}")
                source = np.linspace(source[0], source[-1], len(target))

    def compute(self, **kwargs):
        data_arrays = []
        # Evaluate each expression.
        for key, expr in kwargs.items():
            try:
                data_arrays.append(ParserHelper.evaluate(self, expr))
            except Exception as e:
                # Indicate failure with message and bail.
                self.status_info.proc_msg = f"Expression {key}={expr} | {str(e)}"
                self.status_info.result = Result.FAIL
                logger.warning(
                    f"Processing error: {self.status_info.proc_msg}")
                break
        else:
            if len(data_arrays) == 3:  # strict
                self.set_data(data_arrays)
            else:
                self.status_info.proc_msg = f"Unsupported size of data arrays. Expected triple. Got {len(data_arrays)}"
                self.status_info.result = Result.FAIL
                logger.warning(
                    f"Processing error: {self.status_info.proc_msg}")

    def _process_data(self):
        if len(self.children):
            # Cannot process data when _fetch_data failed or did not occur
            if self.status_info.result != Result.SUCCESS and self.data_access_enabled:
                return
    
            local_env = dict(ParserHelper.env)

            for child in self.children:
                if local_env.get(child.name) is None:
                    local_env.update({child.name: child})
                child._process_data()

            try:
                p = Parser().set_expression(self.name)
                p.substitute_var(local_env)
                p.eval_expr()
                if isinstance(p.result, ProcessingSignal):
                    p.result.copy_buffers_to(self)
                    self.compute(x=self.x_expr, y=self.y_expr, z=self.z_expr)
                else:
                    self.status_info.reset()
                    self.status_info.proc_msg = f"Result of expression={self.name} is not an instance of {type(self).__name__}"
                    self.status_info.result = Result.FAIL
                    logger.warning(
                        f"Processing error: {self.status_info.proc_msg}")
            except Exception as e:
                self.status_info.reset()
                self.status_info.proc_msg = str(e)
                self.status_info.result = Result.FAIL
                logger.warning(
                    f"Processing error: {self.status_info.proc_msg}")
        else:
            # Cannot process data when _fetch_data failed or did not occur
            if self.status_info.result != Result.SUCCESS and self.data_access_enabled:
                return

            self.compute(x=self.x_expr, y=self.y_expr, z=self.z_expr)

    def _on_data_access_finish(self, f: Future):
        e = f.exception()

        self.status_info.reset()

        if isinstance(e, Exception):
            # Indicate failure with message.
            self.status_info.da_msg = str(e)
            self.status_info.result = Result.FAIL
            logger.warning(
                f"Data access request error: {self.status_info.da_msg}")
            return

        res = f.result()
        if not isinstance(res, dict):
            # We don't know what happened. The iplotDataAccess module was unable to communicate the error.
            self.status_info.da_msg = 'Unknown error while fetching data'
            self.status_info.result = Result.FAIL
        else:
            # if data access succeded, the fetched data is encapsulated in a dict.
            self.time = res['time']
            self.time_unit = res['time_unit']
            self.data_primary = res['data_primary']
            self.data_primary_unit = res['data_primary_unit']
            self.data_secondary = res['data_secondary']
            self.data_secondary_unit = res['data_secondary_unit']
            self.status_info.reset()
            self.status_info.num_points = len(self.time)
            self.status_info.result = Result.SUCCESS

    def _fetch_data(self, results: dict = {}) -> typing.Tuple[Future, IplotSignalAdapterT]:
        """
        Make a data access call with AccessHelper and process the data if necessary.
        """
        # avoid request pile up.
        if self.status_info.result == Result.BUSY:
            return

        if not self.needs_refresh():
            return

        # Set appropriate status
        self.status_info.reset()
        self.status_info.result = Result.BUSY

        if len(self.children):
            # ask child signals to fetch data
            for child in self.children:
                child._fetch_data(results)
        else:
            # submit a fetch request for ourself.
            f = CachingAccessHelper.get().fetch_data(self)
            f.add_done_callback(self._on_data_access_finish)
            results.update({f: self})

    def _wait_data(self, results: dict):

        # The children wait for as long as parent's time out value.
        _, not_done = wait(results.keys(), timeout=self.time_out_value)
        for f in not_done:
            sig = results.get(f)
            sig.status_info.reset()
            sig.status_info.da_msg = f"time out ({self.time_out_value})"
            sig.status_info.proc_msg = f"time out ({self.time_out_value})"
            sig.status_info.result = Result.FAIL

        # if any child has a status==fail, then parent will indicate it.
        for child in self.children:
            if child.status_info.result == Result.FAIL:
                self.status_info.reset()
                if child.status_info.da_msg:
                    self.status_info.da_msg = f"child failure: " + child.status_info.da_msg
                if child.status_info.proc_msg:
                    self.status_info.proc_msg = f"child failure: " + child.status_info.proc_msg
                self.status_info.result = Result.FAIL
                break
        else:
            # fell through, none of the children failed
            if len(self.children):
                self.status_info.reset()
                self.status_info.result = Result.SUCCESS

    def get_data(self):
        results = {}
        self._fetch_data(results)
        self._wait_data(results)

        if self.processing_enabled:
            self._process_data()

        return [self.time, self.data_primary, self.data_secondary]

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
        if not self.data_access_enabled:
            return

        target_md5sum = hash_code(self, ["ts_start", "ts_end", "pulse_nb"])
        logger.debug(f"old={self.access_md5sum}, new={target_md5sum}")

        if self.access_md5sum != target_md5sum:
            self.access_md5sum = target_md5sum
            return not self._check_if_zoomed_in()
        else:
            return False

    def _check_if_zoomed_in(self):
        """If we are not zoomed in there is no need to refresh data"""
        if all(e is not None for e in [self.data_xrange[0], self.data_xrange[1], self.ts_start, self.ts_end]):
            return (self.data_xrange[0] < self.ts_start < self.data_xrange[1]
                    and self.data_xrange[0] < self.ts_end < self.data_xrange[1])
        else:
            return False


class AccessHelper:
    """
    A simple wrapper providing UDA data cache.
    For now we should only assume that data ranges are given by timestamps
    """

    async_enabled = False
    da = None
    num_samples_override = False
    num_samples = 1000
    query_no = 0

    def __init__(self) -> None:
        num_workers = None if self.async_enabled else 1
        self.pool = ProcessPoolExecutor(max_workers=num_workers)

    @staticmethod
    def construct_da_params(signal: IplotSignalAdapter):
        return dict(dataSName=signal.data_source,
                    varname=signal.name,
                    tsS=AccessHelper.uda_ts(signal, signal.ts_start),
                    tsE=AccessHelper.uda_ts(signal, signal.ts_end),
                    tsFormat='relative' if signal.ts_relative else 'absolute',
                    pulse=signal.pulse_nb,
                    envelope=signal.envelope,
                    nbp=AccessHelper.num_samples if AccessHelper.num_samples_override else -1
                    )

    @staticmethod
    def uda_ts(signal: IplotSignalAdapter, value):
        """Formats values as relative/absolute timestapms for UDA request or pretty print string"""
        # return str(np.datetime64(value, 'ns')) if not (signal.ts_relative or value is None) else value
        try:
            if not signal.ts_relative:
                return int(value)
            else:
                return float(value)
        except TypeError:
            return value

    @staticmethod
    def str_ts(signal: IplotSignalAdapter, value):
        try:
            if value is not None:
                if type(value) == np.datetime64:
                    return value
                if (type(value) == int or type(value) == float) and value > 10**15:
                    return np.datetime64(value, 'ns')
        except:
            logger.error(
                f"Unable to convert value {value} to string timestamp")

        return value

    @staticmethod
    def get():
        return AccessHelper()

    def fetch_data(self, signal: IplotSignalAdapter) -> Future:
        logger.debug("[UDA {}] Get data: {} ts_start={} ts_end={} pulse_nb={} nbsamples={} relative={}".format(AccessHelper.query_no, signal.name, self.str_ts(signal, signal.ts_start), self.str_ts(signal, signal.ts_end),
                                                                                                               signal.pulse_nb, -1, signal.ts_relative))
        AccessHelper.query_no += 1
        return self.pool.submit(AccessHelper._request_data, **(AccessHelper.construct_da_params(signal)))

    @staticmethod
    def _request_data(**da_params):
        tsS = da_params.get('tsS')
        tsE = da_params.get('tsE')
        pulse = da_params.get('pulse')
        envelope = da_params.get('envelope')
        tRelative = da_params.get('tsFormat') == 'relative'
        result = dict(time=[],
                      data_primary=[],
                      data_secondary=[],
                      time_unit='',
                      data_primary_unit='',
                      data_secondary_unit='')
        da_params.pop('envelope') # getEnvelope does not need this.

        def np_nvl(arr):
            return np.empty(0) if arr is None else np.array(arr)

        if (tsS is not None and tsE is not None) or pulse is not None:

            if envelope:
                (d_min, d_max) = AccessHelper.da.getEnvelope(**da_params)
                if d_min.errcode < 0 and d_max.errcode < 0:
                    da_params.update({'nbp': AccessHelper.num_samples})
                    (d_min, d_max) = AccessHelper.da.getEnvelope(**da_params)
                    if d_min.errcode < 0:
                        message = f"ErrCode: {d_min.errcode} | getEnvelope (minimum) failed for -1 and {AccessHelper.num_samples} samples. {da_params}"
                        raise DataAccessError(message)
                    elif d_max.errcode < 0:
                        message = f"ErrCode: {d_min.errcode} | getEnvelope (minimum) failed for -1 and {AccessHelper.num_samples} samples. {da_params}"
                        raise DataAccessError(message)

                xdata = np_nvl(d_min.xdata if d_min else None) if tRelative else np_nvl(
                    d_min.xdata if d_min else None)

                result['time'] = np_nvl(xdata)
                result['data_primary'] = np_nvl(d_min.ydata if d_min else None)
                result['data_secondary'] = np_nvl(
                    d_max.ydata if d_max else None)
                result['time_unit'] = d_min.xunit if d_min else ''
                result['data_primary_unit'] = d_min.yunit if d_min else ''
                result['data_secondary_unit'] = d_max.yunit if d_min else ''

            else:
                raw = AccessHelper.da.getData(**da_params)
                if raw.errcode < 0:
                    da_params.update({'nbp': AccessHelper.num_samples})
                    raw = AccessHelper.da.getData(**da_params)
                    if raw.errcode < 0:
                        message = f"ErrCode: {raw.errcode} | getData failed for -1 and dec_samples. {da_params}"
                        raise DataAccessError(message)

                xdata = np_nvl(raw.xdata) if tRelative else np_nvl(
                    raw.xdata).astype('int')

                if len(xdata) > 0:
                    logger.debug(
                        F"\tUDA samples: {len(xdata)} params={da_params}")
                    logger.debug(
                        F"\tX range: d_min={xdata[0]} d_max={xdata[-1]} delta={xdata[-1]-xdata[0]} type={xdata.dtype}")
                else:
                    logger.info(
                        F"\tUDA samples: {len(xdata)} params={da_params}")

                result['time'] = xdata
                result['data_primary'] = np_nvl(raw.ydata)
                result['data_secondary'] = np.empty(0).astype('double')
                result['time_unit'] = raw.xunit if raw.xunit else ''
                result['data_primary_unit'] = raw.yunit if raw.yunit else ''
                result['data_secondary_unit'] = ''
        else:
            raise DataAccessError(
                f"tsS={tsS}, tsE={tsE}, pulse_nb={pulse}")

        return result


class CachingAccessHelper(AccessHelper):
    KEY_PROP_NAMES = ["var_name", "ts_start", "ts_end", "pulse_nb",
                      "dec_samples", "data_source", "envelope", "ts_relative"]
    CACHE_PREFIX = "/tmp/cache_"

    def __init__(self, enable_cache=False):
        super().__init__()
        self.enable_cache = enable_cache

    @staticmethod
    def get():
        return CachingAccessHelper()

    def fetch_data(self, signal: IplotSignalAdapter) -> Future:
        if self.enable_cache:
            cached = self._cache_fetch(signal)
            if cached is not None:
                logger.info(F"HIT: {self._cache_filename(signal)}")
                return cached
            else:
                logger.info(F"MISS: {self._cache_filename(signal)}")
                return self._cache_put(signal, super().fetch_data(signal))
        else:
            return super().fetch_data(signal)

    def _cache_filename(self, signal: IplotSignalAdapter):
        return "{}{}.npy".format(self.CACHE_PREFIX, hash_code(signal, self.KEY_PROP_NAMES))

    def _cache_fetch(self, signal: IplotSignalAdapter):
        filename = self._cache_filename(signal)
        return np.load(filename, allow_pickle=True) if os.path.isfile(filename) else None

    def _cache_put(self, signal: IplotSignalAdapter, data):
        filename = self._cache_filename(signal)
        np.save(filename, data, allow_pickle=True)
        return data


class ParserHelper:
    """
    A wrapper linking iplotProcessing.Parser with a IplotSignalAdapter
    """
    env = dict()

    @staticmethod
    def evaluate(signal: IplotSignalAdapter, expression: str):
        """Evaluate the given `expression` in the scope of `signal`.

        :param signal: A signal object
        :type signal: IplotSignalAdapter
        :param expression: A string of text comprehensible by iplotProcessing.tools.Parser
        :type expression: str
        """
        logger.debug(
            f"Evaluating {expression} in scope of signal: {signal.name} @{id(signal)}")
        local_env = dict(ParserHelper.env)
        if expression.count('self'):
            local_env.update({'self': signal})

        p = Parser()
        p.inject(Parser.get_member_list(type(signal)))
        p.inject(Parser.get_member_list(BufferObject))
        p.set_expression(expression)
        if not p.is_valid:
            raise InvalidExpression(f"expression: {expression} is invalid!")

        p.substitute_var(local_env)
        p.eval_expr()
        return p.result
