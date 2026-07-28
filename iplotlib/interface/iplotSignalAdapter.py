# Description: Extend Data-Access, Data-Processing to self-aware iplotlib.core.Signal
# Author: Abadie Lana
# Changelog:
#   Sept 2021: -Inherit from ArraySignal and ProcessingSignal [Jaswant Sai Panchumarti]
#              -Added attributes for x, y, z expression fields. [Jaswant Sai Panchumarti]
#              -Extract data-access code into fetch_data method. [Jaswant Sai Panchumarti]
#              -Apply processing right after data access in fetch_data [Jaswant Sai Panchumarti]
#              -Teach AccessHelper to explore ProcessingSignal objects. [Jaswant Sai Panchumarti]
#              -Rename AccessHelper.get_data -> AccessHelper._fetch_data (no longer returns data)
#              [Jaswant Sai Panchumarti]
#              -Translate iplotDataAccess.DataObj into ProcessingSignal in AccessHelper._fetch_data
#              [Jaswant Sai Panchumarti]
#  Oct 2021:   Changes by Jaswant
#              - All data requests are done in blocking fashion.
#              - Added ParserHelper.
#              - Added on_fetch_done to AccessHelper
#              - Renamed DataAccessSignal ->IplotSignalAdapter.
#              - Removed dec_samples. Use fall back value if default -1 parameter fails.
#              - Added _process_data() to IplotSignalAdapter
#              - Added compute() to IplotSignalAdapter
#              - Added StatusInfo to IplotSignalAdapter
#              - Parse given time as isoformat datetime only if it is a non-empty string
#  Dec 2021:   Changes by Jaswant
#              - If the number of child signals is > 1, then align them onto a common grid before evaluating an
#              expression.
#              - The alignment modifies the data_store. After evaluation, restore the original buffers.
#  Feb 2023:   Changes by Alberto Luengo
#              - Re-alignment of signals with different shapes to allow plot X vs. Y variables
from dataclasses import dataclass, field, fields
import numpy as np
import os
import typing

from iplotlib.interface.utils import string_classifier
from iplotProcessing.common.errors import InvalidExpression
from iplotProcessing.common.interpolation import InterpolationKind
from iplotProcessing.core import BufferObject
from iplotProcessing.core import Signal as ProcessingSignal
from iplotProcessing.math.pre_processing.grid_mixing import align
from iplotProcessing.tools.parsers import Parser
from iplotProcessing.tools import hash_code

from iplotLogging import setupLogger

logger = setupLogger.get_logger(__name__)

#: Sentinel for IplotSignalAdapter.interpolation: choose the realignment
#: interpolation automatically from the dependencies' sampling (mint#120).
INTERPOLATION_AUTO = 'auto'

#: Dependencies sampled faster than this are considered continuously sampled for
#: the automatic realignment interpolation; slower ones are treated as
#: event-driven (a new value is only published on change).
CONTINUOUS_RATE_THRESHOLD_HZ = 100.0

# Dedup key (source, target, len_src, len_tgt, case): same mismatch across signals warns once.
_TRUNCATE_WARN_KEYS: typing.Set[tuple] = set()

IplotSignalAdapterT = typing.TypeVar('IplotSignalAdapterT', bound='IplotSignalAdapter')


class DataAccessError(Exception):
    pass


class Result:
    BUSY = 'Busy'
    INVALID = 'Invalid'
    FAIL = 'Fail'
    READY = 'Ready'
    SUCCESS = 'Success'


class Stage:
    DA = 'Data-Access'
    INIT = 'Initialization'
    PROC = 'Processing'


@dataclass
class StatusInfo:
    msg: str = ''
    num_points: int = 0
    result: str = Result.READY
    sep = '|'
    stage: str = Stage.INIT
    inf: int = 0

    def reset(self):
        self.msg = ''
        self.num_points = 0
        self.result = Result.READY
        self.stage = Stage.INIT
        self.sep = '|'
        self.inf = 0

    def __str__(self) -> str:
        if self.result == Result.BUSY or self.result == Result.INVALID:
            return self.result + self.sep + self.stage
        elif self.result == Result.FAIL:
            return f"{self.stage}{self.sep}{self.num_points} points" + \
                (f"{self.sep} {self.inf} infinities" if self.inf > 0 else "")
        elif self.result == Result.READY:
            return self.result
        elif self.result == Result.SUCCESS:
            return f"{self.result}{self.sep}{self.num_points} points" + \
                (f"{self.sep} {self.inf} infinities" if self.inf > 0 else "")


@dataclass
class IplotSignalAdapter(ProcessingSignal):
    """
        This is an adapter class that is the culmination of two crucial classes in the iplotlib framework.
        Its purpose is to make ProcessingSignal interface compatible with the ArraySignal interface.

        Warning: Consider this class as a frozen blueprint, i.e, do not expect it to be consistent once
        some of the parameters are modified after initialization. Such parameters are name, alias,
        data_access_enabled, processing_enabled
    """
    data_source: str = ''
    alias: str = ''
    stream_valid: bool = True
    pulse_nb: int = None
    ts_start: str = ''
    ts_end: str = ''
    ts_relative: bool = False
    envelope: bool = False
    calibrated: bool = False
    isDownsampled: bool = False
    x_expr: str = '${self}.time'
    y_expr: str = '${self}.data'
    z_expr: str = '${self}.data_store[2]'
    extremities: bool = False
    plot_type: str = ''
    children: typing.List[IplotSignalAdapterT] = field(default_factory=list)
    status_info: StatusInfo = None
    data_access_enabled: bool = True
    processing_enabled: bool = True
    time_out_value: float = 60  # Unimplemented  ---> REVIEW: purpose of this attribute?
    #: Interpolation used when this signal's expressions realign dependencies with
    #: different time bases (see ParserHelper.evaluate / align()). The default
    #: 'auto' picks linear interpolation only when every dependency is raw (not
    #: downsampled) and its observed rate is above CONTINUOUS_RATE_THRESHOLD_HZ;
    #: otherwise sample-and-hold ('previous') is used, because slow, event-driven
    #: signals only publish a new value on change — no new sample means the value
    #: is constant, and interpolating between updates would invent values
    #: (mint#120). Any InterpolationKind value can be set explicitly to force a
    #: specific behaviour.
    interpolation: str = INTERPOLATION_AUTO

    def __post_init__(self):
        super().__init__()

        # 1.1 Initialize access parameters
        if string_classifier.is_non_empty(self.ts_start):
            self.ts_start = np.datetime64(self.ts_start, 'ns').astype('int64').item()

        if string_classifier.is_non_empty(self.ts_end):
            self.ts_end = np.datetime64(self.ts_end, 'ns').astype('int64').item()

        self.ts_relative = string_classifier.is_non_empty(self.pulse_nb)
        self._local_env = dict()

        # 1.2. Initialize attributes that will not be dataclass fields.
        self.x_data = BufferObject()
        self.y_data = BufferObject()
        self.z_data = BufferObject()
        # Full-range minimap snapshot; invalidated by clear_minimap_snapshot().
        self._minimap_x_data = None
        self._minimap_y_data = None
        self._minimap_y_max_data = None
        self._minimap_y_avg_data = None
        self._minimap_is_downsampled = False

        # 2. Post-initialize ArraySignal's properties and our name.
        self._init_label()

        # 3. Help keep track of data access parameters.
        self._access_md5sum = None
        # One-shot marker: the current ts range is a genuine time window that was
        # propagated from a shared-time zoom (see set_time_window()).
        self._ts_is_time_window = False
        # Time base the expressions were last evaluated over (pure expression
        # signals only); enables the reverse X-to-time mapping (mint#120).
        self._expr_time_base = None

        # 4. Parse name and prepare a hierarchy of objects if needed.
        self.status_info = StatusInfo()
        self.status_info.result = Result.BUSY
        self._init_children(self.name)

        # 5. Initialize dependencies
        self.depends_on = ParserHelper.get_dependencies([self.x_expr, self.y_expr, self.z_expr])

        if self.status_info.result == Result.INVALID:
            return
        else:
            # Add a reference to our alias.
            if string_classifier.is_non_empty(self.alias):
                ParserHelper.env.update({self.alias: self})

            # Indicate readiness.
            self.status_info.result = Result.READY

    def calculate_data_hash(self):
        return hash_code(self, ["ts_start", "ts_end", "pulse_nb", "calibrated"])

    def get_data(self):
        # 1. Populate time, data_primary, data_secondary (if needed)
        if self._do_data_access():
            # 2. Use iplotProcessing to evaluate x_data, y_data, z_data
            self._do_data_processing()

        if hasattr(self, 'envelope') and self.envelope and len(self.data_store[0]) > 0:
            return [self.x_data, self.y_data, self.z_data, self.data_store[3]]
        else:
            return [self.x_data, self.y_data, self.z_data]

    def set_data(self, data=None):
        """Set `x_data`, `y_data` and `z_data`.

        :param data: A collection of data buffers, defaults to None
        :type data: List[BufferObject], optional
        :return: None
        :rtype: NoneType
        """
        if data is None:
            super().set_data()  # as of now this does nothing.

        self._finalize_xyz_data(data)

        self.data_store[0] = self.x_data
        self.data_store[1] = self.y_data
        self.data_store[2] = self.z_data
        self.set_da_success()

    @staticmethod
    def truncate_to_target(source: BufferObject, target: BufferObject,
                           source_label: str = 'source', target_label: str = 'target') -> BufferObject:
        """Align `source` to the shape of `target`.

        This function truncates `source` when it is longer than `target`. As a special case,
        a single-element `source` is expanded to match `target`'s length by replicating the
        value (no data is invented). It does not extend `source` with assumed values in any
        other case.

        :param source: The object to align.
        :type source: BufferObject
        :param target: The object whose shape should be matched.
        :type target: BufferObject
        :param source_label: Name of the expression producing `source` (e.g. 'y' or 'z').
        :param target_label: Name of the expression producing `target` (e.g. 'x').
        :return: The aligned `source` object.
        :rtype: BufferObject
        """
        if np.isscalar(source):
            return BufferObject([source] * len(target))

        if target.ndim != source.ndim:
            return source  # CHECK: Modify ndims

        if len(source) == len(target):
            return source

        # Source empty means the axis isn't used by this signal; not a mismatch.
        if len(source) == 0:
            return source

        def _log_mismatch(case: str, msg: str) -> None:
            key = (source_label, target_label, len(source), len(target), case)
            if key in _TRUNCATE_WARN_KEYS:
                logger.debug(msg)
            else:
                _TRUNCATE_WARN_KEYS.add(key)
                logger.warning(msg)

        if len(source) == 1:
            _log_mismatch(
                'replicate',
                f"{source_label} and {target_label} expressions produced arrays of different lengths "
                f"({source_label} has {len(source)} point, {target_label} has {len(target)}). "
                f"Replicating the single-point {source_label} to match the {target_label} size. "
                f"To avoid this warning, make sure both expressions return arrays of the same length.")
            return BufferObject(np.full(len(target), source[0], dtype=source.dtype), unit=source.unit)

        if len(target) < len(source):
            _log_mismatch(
                'truncate',
                f"{source_label} and {target_label} expressions produced arrays of different lengths "
                f"({source_label} has {len(source)} points, {target_label} has {len(target)}). "
                f"Truncating {source_label} to match {target_label}. "
                f"To avoid this warning, make sure both expressions return arrays of the same length "
                f"(e.g. use [0:1] slicing to align with a single-point expression).")
            return BufferObject(source[:len(target)], unit=source.unit)

        _log_mismatch(
            'no-extend',
            f"{source_label} and {target_label} expressions produced arrays of different lengths "
            f"({source_label} has {len(source)} points, {target_label} has {len(target)}). "
            f"{source_label} cannot be extended without assuming data; leaving it as-is. "
            f"Make sure both expressions return arrays of the same length.")
        return source

    def compute(self, **kwargs) -> dict:
        data_arrays = dict()
        correspondance = {"x": 0, "y": 1, "z": 2}

        # Evaluate each expression.
        for key, expr in kwargs.items():
            try:
                if self.x_expr == '${self}.time' and self.y_expr == '${self}.data' and self.z_expr == '${self}.data_store[2]':
                    logger.debug(f"No processing needed to compute key={key} expr={expr}")
                    data_arrays.update({key: self.data_store[correspondance[key]]})
                else:
                    logger.debug(f" in compute key={key} expr={expr}")
                    result = ParserHelper.evaluate(self, expr)
                    r_dbg = np.asarray(result)
                    logger.debug(f"mint#120: compute '{getattr(self, 'label', '?')}' {key}={expr} -> "
                                f"n={r_dbg.size} dtype={r_dbg.dtype} "
                                f"unit={getattr(result, 'unit', '?')} "
                                f"min={r_dbg.min() if r_dbg.size and np.issubdtype(r_dbg.dtype, np.number) else '-'} "
                                f"max={r_dbg.max() if r_dbg.size and np.issubdtype(r_dbg.dtype, np.number) else '-'}")
                    data_arrays.update({key: result})
            except Exception as e:
                logger.error(f"Error {e} in {expr}")
                continue

        # Clear the dictionary result
        ParserHelper.dict_result.clear()

        return data_arrays

    @property
    def data_xrange(self):
        if len(self.x_data.ravel()) > 1:
            return self.x_data.ravel()[0], self.x_data.ravel()[-1]
        else:
            return None, None

    def get_ranges(self):
        return [[self.ts_start, self.ts_end]]

    def set_xranges(self, ranges):
        def np_convert(value):
            if isinstance(value, np.generic):
                if isinstance(value, np.float64):
                    return value.astype('float').item()
                else:
                    return value.astype('int64').item()
            else:
                return value

        self.ts_start = np_convert(ranges[0])
        self.ts_end = np_convert(ranges[1])
        if self.pulse_nb is not None and self.ts_start == '' and self.ts_end == '':
            self._access_md5sum = self.calculate_data_hash()

        for child in self.children:
            child.ts_start = self.ts_start
            child.ts_end = self.ts_end
            # child._access_md5sum = self._access_md5sum

        # self.ts_start = ranges[0].astype(target_type).item() if isinstance(ranges[0], np.generic) else ranges[0]
        # self.ts_end = ranges[1].astype(target_type).item() if isinstance(ranges[0][0], np.generic) else ranges[0][1]

    def set_time_window(self, begin, end):
        """Set the requested data range from a trusted time window.

        Used when a shared-time zoom is propagated to a plot whose X axis is not
        time (X-versus-Y, iplot-viz/mint#120): ``begin``/``end`` come from the
        time plot that was zoomed, so they are genuine times regardless of the
        shape of this signal's processed X data. The range is marked so that
        :meth:`_needs_refresh` allows a refetch/reprocess even when the X data is
        not monotonically increasing (a zoom made on the X-versus-Y plot itself
        keeps the conservative behaviour, since a non-bijective X cannot be
        mapped back to a time interval).
        """
        self.set_xranges((begin, end))
        self._ts_is_time_window = True
        for child in self.children:
            child._ts_is_time_window = True

    def refresh_over_time_window(self, begin, end, _visited=None):
        """Refresh this signal and its expression dependencies over a trusted time window.

        Used when a shared-time zoom is propagated to an X-versus-Y plot
        (iplot-viz/mint#120). Expression signals (e.g. x_expr='${A}.data') are
        evaluated against the *current* buffers of their alias dependencies, so
        those dependencies are refreshed first — including aliases that are not
        displayed on any plot of the shared group and therefore were not
        refetched by the zoom itself. Dependencies already refetched over the
        same window are left untouched (their data hash is unchanged).
        """
        if _visited is None:
            _visited = set()
        if id(self) in _visited:
            return
        _visited.add(id(self))

        for alias in getattr(self, 'depends_on', None) or ():
            if alias == 'self':
                continue
            dep = ParserHelper.env.get(alias)
            if isinstance(dep, IplotSignalAdapter) and dep is not self:
                dep.refresh_over_time_window(begin, end, _visited)

        self.set_time_window(begin, end)
        self.get_data()

    def set_da_success(self):
        self.status_info.reset()
        self.status_info.stage = Stage.DA
        self.status_info.result = Result.SUCCESS
        self.status_info.num_points = len(self.data_store[0])
        self.status_info.inf = int(np.sum(np.isinf(np.asarray(self.data_store[1], dtype=float))))

    def set_da_fail(self, msg: str = ''):
        self.status_info.reset()
        self.status_info.stage = Stage.DA
        self.status_info.result = Result.FAIL
        self.status_info.msg = msg
        self.status_info.num_points = 0
        logger.warning(f"Data Access Error in {self._signal_context()}: {msg}")

    def set_proc_success(self):
        self.status_info.reset()
        self.status_info.stage = Stage.PROC
        self.status_info.num_points = len(self.x_data)
        self.status_info.inf = int(np.sum(np.isinf(np.asarray(self.y_data, dtype=float))))
        self.status_info.result = Result.SUCCESS

    def set_proc_fail(self, msg: str = ''):
        self.status_info.reset()
        self.status_info.stage = Stage.PROC
        self.status_info.result = Result.FAIL
        self.status_info.msg = msg
        self.status_info.num_points = 0
        logger.warning(f"Processing Error in {self._signal_context()}: {msg}")

    def _signal_context(self) -> str:
        alias = getattr(self, 'alias', '') or ''
        name = getattr(self, 'name', '') or ''
        parts = []
        if alias and alias != name:
            parts.append(f"signal '{alias}'")
        if name:
            parts.append(f"variable/expression='{name}'")
        for attr in ('x_expr', 'y_expr', 'z_expr'):
            expr = getattr(self, attr, '') or ''
            if expr and expr not in ('${self}.time', '${self}.data', '${self}.data_store[2]'):
                parts.append(f"{attr}='{expr}'")
        return ', '.join(parts) if parts else 'signal'

    def inject_external(self, append: bool = False, **kwargs):
        AccessHelper.on_fetch_done(self, kwargs, append=append)
        self._access_md5sum = self.calculate_data_hash()
        self._do_data_processing()

    # Private API begins here.
    def _init_children(self, expression: str):
        # 1. input can be an expression.
        # eg: ${foo}
        # eg: ${foo} + ${bar} + ${baz} * np.max(${cat})
        # eg: np.max(${foo} + ${bar}) * np.ones((${foo}.data.size))
        #
        # 2. input can be a string of plain text r"^[A-Za-z0-9_@.\/\[\]#&+-]+"
        # eg: foo
        # eg: foo_bar
        # eg: bar_
        # eg: foo-bar-baz2-l3-1
        # eg: foo_bar_baz2_l3_1
        # eg: foo/bar[0]/baz_1
        # eg: foo/bar[0]/baz-1
        # The second case cannot have children, it does not need special consideration.

        # The first case would result in len(children) > 0. We find them (if they are pre-defined aliases) or create
        # them.
        try:
            p = Parser().set_expression(expression)
        except InvalidExpression as e:
            self.status_info.reset()
            self.status_info.msg = f"{e}"
            self.status_info.result = Result.INVALID
            return

        if not p.is_valid:
            return

        keys = set(p.var_map.keys())
        keys.discard('self')  # don't bother with self here.
        for key in keys:
            value = ParserHelper.env.get(key)

            if isinstance(value, IplotSignalAdapter):
                # This is an aliased signal.
                if self.data_access_enabled and string_classifier.is_non_empty(
                        self.data_source) and self.data_source != value.data_source:
                    self.status_info.reset()
                    self.status_info.msg = f"Data source conflict {self.data_source} != {value.data_source}."
                    self.status_info.result = Result.INVALID
                    logger.warning(self.status_info.msg)
                    break
                self.children.append(value)
            else:
                # This is a new/pre-defined signal.
                if self.data_access_enabled and string_classifier.is_empty(self.data_source):
                    self.status_info.reset()
                    self.status_info.msg = "Data source unspecified."
                    self.status_info.result = Result.INVALID
                    logger.warning(self.status_info.msg)
                    break
                elif self.data_access_enabled and key not in self._local_env:
                    # Construct a new instance with our data source and time range, etc...
                    child = self._construct_named_offspring(key)
                    self._local_env.update({key: child})
                    self.children.append(child)
                elif self.processing_enabled:
                    # Cannot create a new instance if only processing is enabled.
                    self.status_info.reset()
                    self.status_info.msg = f"Specified name '{key}' is not a pre-defined alias!"
                    self.status_info.result = Result.INVALID
                    logger.warning(self.status_info.msg)
                    break

    def _construct_named_offspring(self, name: str) -> IplotSignalAdapterT:
        cls = type(self)
        kwargs = dict()

        for f in fields(self):
            kwargs.update({f.name: getattr(self, f.name)})
        kwargs.update({'name': name})
        kwargs.update({'label': ''})
        kwargs.update({'children': []})
        return cls(**kwargs)

    def _init_label(self):
        # 1. From name
        if self.label is None:
            if string_classifier.is_non_empty(self.name):
                self.label = self.name
            else:
                self.label = ''

        # 2. Alias overrides name for the label (appears in legend box)
        if string_classifier.is_non_empty(self.alias):
            self.label = self.alias

        # 3. Shows the pulse number in the label (appears in legend box).
        if self.pulse_nb is not None:
            pulse_as_string = str(self.pulse_nb)
            if string_classifier.is_non_empty(pulse_as_string):
                if self.label.find(pulse_as_string) < 0:
                    self.label += ':' + pulse_as_string

    def _report_xyz_data(self, verbose: int = 0):
        logger.debug(f"x.size: {len(self.x_data)}")
        logger.debug(f"y.size: {len(self.y_data)}")
        logger.debug(f"z.size: {len(self.z_data)}")

        logger.debug(f"x.unit: {self.x_data.unit}")
        logger.debug(f"y.unit: {self.y_data.unit}")
        logger.debug(f"z.unit: {self.z_data.unit}")

        if verbose > 0:
            logger.debug(f"x: {self.x_data}")
            logger.debug(f"y: {self.y_data}")
            logger.debug(f"z: {self.z_data}")

    def _finalize_xyz_data(self, data=None):
        # 1. Fill in data buffers
        if isinstance(data, typing.Collection):
            if len(data):
                if all([isinstance(val, np.ndarray) for val in data]):
                    for i, name in enumerate(['x_data', 'y_data', 'z_data']):
                        try:
                            setattr(self, name, data[i].view(BufferObject))
                        except IndexError:
                            break
                        logger.debug(f"[UDA len_data={len(data)} name={name} i={i} len_data_i={len(data[i])}]")
        # 2. Fix x-y shape mismatch.
        self.y_data = self.truncate_to_target(self.y_data, self.x_data,
                                              source_label='y', target_label='x')

        # 3. Fix x-z shape mismatch.
        self.z_data = self.truncate_to_target(self.z_data, self.x_data,
                                              source_label='z', target_label='x')

        # 3b. Align envelope avg buffer to x_data for the minimap snapshot guard below.
        if getattr(self, 'envelope', False) and len(self.data_store) >= 4:
            self.data_store[3] = self.truncate_to_target(
                self.data_store[3], self.x_data,
                source_label='avg', target_label='x')

        # 4. Capture the full-range minimap snapshot on first populate.
        if self._minimap_x_data is None and len(self.x_data) > 0:
            self._minimap_x_data = self.x_data.copy()
            self._minimap_y_data = self.y_data.copy()
            self._minimap_is_downsampled = self.isDownsampled
            if (getattr(self, 'envelope', False) and len(self.data_store) >= 4
                    and len(self.z_data) == len(self.x_data)
                    and len(self.data_store[3]) == len(self.x_data)):
                self._minimap_y_max_data = self.z_data.copy()
                self._minimap_y_avg_data = self.data_store[3].copy()

        self._report_xyz_data()

    def clear_minimap_snapshot(self):
        """Drop the cached full-range minimap data so the next load repopulates it."""
        self._minimap_x_data = None
        self._minimap_y_data = None
        self._minimap_y_max_data = None
        self._minimap_y_avg_data = None
        self._minimap_is_downsampled = False

    def restore_minimap_snapshot(self):
        """
        Restore the buffers and the downsampled state to the full-range data
        captured at draw time (the same snapshot the minimap renders) and return
        it shaped like :meth:`get_data`, or None when no snapshot is available.

        The data hash is refreshed so the restored buffers count as up to date for
        the current time range: redisplaying them triggers no data access.
        """
        x_data = self._minimap_x_data
        y_data = self._minimap_y_data
        if x_data is None or y_data is None or len(x_data) == 0:
            return None
        envelope = getattr(self, 'envelope', False)
        if envelope and (self._minimap_y_max_data is None or self._minimap_y_avg_data is None):
            return None

        self.x_data = x_data.copy()
        self.y_data = y_data.copy()
        if envelope:
            self.z_data = self._minimap_y_max_data.copy()
            # Realign the raw envelope store: statistics index min/max/avg by the displayed data.
            self.data_store[0] = self.x_data
            self.data_store[1] = self.y_data
            self.data_store[2] = self.z_data
            self.data_store[3] = self._minimap_y_avg_data.copy()
        # The downsampled state drives the legend marker and the next-zoom refetch.
        self.isDownsampled = self._minimap_is_downsampled
        self._access_md5sum = self.calculate_data_hash()
        self.set_da_success()

        if envelope:
            return [self.x_data, self.y_data, self.z_data, self.data_store[3]]
        return [self.x_data, self.y_data, self.z_data]

    def _process_data(self):
        # 1. Cannot process data when _fetch_data failed or did not occur
        if self.data_access_enabled and self.status_info.result != Result.SUCCESS:
            return

        # 2.Handle child signals
        # Note: In this case, `self.name` is an expression, so prior to applying x,y,z we evaluate `self.name`
        if len(self.children):
            vm = dict(self._local_env)
            vm.update(ParserHelper.env)  # makes aliases accessible to parser
            vm['self'] = self

            # 2.1 Ensure all child signals have their time, data vectors (if DA enabled)
            # Note: Before, a backup was used to get back original data for all child. Now, we use a dict called
            # dict_result which contains the processed data, avoiding to modify the original data of the child.

            # 2.2 Check if children are aligned in time
            tmp_local_env = dict(vm)
            tmp_local_env['self'] = self
            dependencies = []
            for child in self.children:
                if hasattr(child, "data_store") and len(child.data_store[0]) != 0:
                    dependencies.append(child)

            needs_realign = False
            for sig1, sig2 in zip(dependencies[:-1], dependencies[1:]):
                if not np.array_equal(sig1.data_store[0], sig2.data_store[0]):
                    needs_realign = True
                    break

            if needs_realign and len(dependencies) > 1:
                ParserHelper.dict_result = align(
                    dependencies, curr_signal=self,
                    kind=ParserHelper.resolve_alignment_kind(self, dependencies)) or {}

            # 2.3 Evaluate 'self.name'. It is an expression combining multiple other signals
            try:
                p = Parser()
                p.inject(Parser.get_member_list(type(self)))
                p.inject(self.alias_map)
                p.clear_expr()

                if 'data' not in self.alias_map.keys():
                    # Envelope validation: if the result comes from signals that use envelope data, the current signal
                    # must also be marked as envelope. Otherwise, processing cannot continue and an exception is raised
                    if not self.envelope:
                        self.set_proc_fail(
                            f"Result of expression={self.name} is derived from signals with envelope data. "
                            f"Ensure the result signal is configured to use envelope.")
                        return
                    self.data_store.clear()
                    if ParserHelper.dict_result:
                        first_key = next(iter(ParserHelper.dict_result))
                        self.data_store.append(ParserHelper.dict_result[first_key]['time'])
                    else:
                        self.data_store.append(dependencies[0].time)
                    for idx in self.dependent_accessors:
                        p.set_expression(self.name, True, True, idx)
                        p.substitute_var(tmp_local_env, ParserHelper.dict_result, self.alias_map, self.envelope)
                        p.eval_expr()
                        # Set envelope data
                        result = p.result if isinstance(p.result, BufferObject) else BufferObject(p.result)
                        self.data_store.append(result)
                else:
                    p.set_expression(self.name, True)
                    p.substitute_var(tmp_local_env, ParserHelper.dict_result)
                    p.eval_expr()

                    # Set result
                    if isinstance(p.result, (BufferObject, np.ndarray)):
                        if ParserHelper.dict_result:
                            first_key = next(iter(ParserHelper.dict_result))
                            self.data_store[0] = ParserHelper.dict_result[first_key]['time']
                        else:
                            self.data_store[0] = dependencies[0].time
                        self.data_store[1] = p.result if isinstance(p.result, BufferObject) else BufferObject(p.result)
                    else:
                        self.set_proc_fail(
                            f"Result of expression={self.name} is not an instance of {type(self).__name__}")
                        return
            except Exception as e:
                self.set_proc_fail(msg=str(e))
                return
            finally:
                ParserHelper.dict_result.clear()
        elif self.status_info.result == Result.FAIL:
            # Only an unevaluated Fail persists: a successful evaluation above
            # supersedes a Fail from before the children had data.
            return

        # 3. Finally, apply x, y, z expressions to populate `x_data`, `y_data` and `z_data` respectively
        # self.compute evaluates expressions (IDV-333)
        data_arrays = self.compute(x=self.x_expr, y=self.y_expr, z=self.z_expr)
        self._finalize_xyz_data([data_arrays.get('x'), data_arrays.get('y'), data_arrays.get('z')])
        # logger.debug("[UDA x={} y={} z={} ] ".format(len(data_arrays.get('x')),len(data_arrays.get('y')),
        # len(data_arrays.get('z'))))

        # 4. Set ts_start and ts_end to avoid hash mismatch
        # if len(data_arrays.get('x')) > 0:
        #     self.set_xranges([data_arrays.get('x')[0], data_arrays.get('x')[-1]])
        #     self._access_md5sum = self.calculate_data_hash()

        self.set_proc_success()

    def _fetch_data(self):
        """
        Make a data access call with AccessHelper.
        """
        # avoid request pile up, shouldn't occur internally since all requests are blocking
        if self.status_info.result == Result.BUSY:
            return

        # Set appropriate status
        self.status_info.reset()

        if len(self.children):
            isDownsampled = False
            alias_map = {}
            # ask child signals to fetch data
            for child in self.children:
                if child._needs_refresh():
                    child._fetch_data()
                if child.status_info.result == Result.FAIL:
                    self.set_da_fail(msg=child.status_info.msg)  # get exact reason for failure from child.
                    break
                if not alias_map:
                    alias_map = child.alias_map
                elif alias_map != child.alias_map:
                    self.set_da_fail(
                        msg="Cannot process signal with envelope and signal with no envelope")  # get exact reason for failure from child.
                    break
                else:
                    alias_map = child.alias_map
                isDownsampled |= child.isDownsampled
            else:  # Fell through, all children succeded
                self.isDownsampled = isDownsampled
                self.alias_map.clear()
                self.alias_map.update(alias_map)
                self.set_da_success()
        else:
            # submit a fetch request for ourself.
            CachingAccessHelper.get().fetch_data(self)

    def _do_data_access(self):
        # Skip if we are invalid.
        if self.status_info.result == Result.INVALID:
            return False

        # no name implies there is no need to request data (we don't have a variable to ask the data source)
        nonempty_name = string_classifier.is_non_empty(self.name)
        if nonempty_name and self.data_access_enabled:

            if self._needs_refresh():
                self._fetch_data()
                return True
            elif self.status_info.stage == Stage.PROC:
                self.set_da_success()
                return False
        else:
            # 1. either name is empty, trivial (no data access, so emulate a success DA)
            # or 
            # 2.data_access_enabled = False. Assume that user called set_data(...), so, emulate a success DA
            if self.status_info.stage == Stage.INIT:
                self.set_da_success()
                return True
            if getattr(self, '_ts_is_time_window', False):
                # A shared-time zoom propagated a trusted time window to this
                # dependent expression signal (empty name, e.g. x_expr='${A}.data',
                # as produced by MINT for X-versus-Y rows). It has no data access of
                # its own; its dependencies were refetched over the window by their
                # own plots, so re-run processing to re-evaluate the X/Y expressions
                # over their new buffers (iplot-viz/mint#120).
                self._ts_is_time_window = False
                self.set_da_success()
                logger.debug(f"mint#120: forced reprocess of expression signal "
                            f"'{self.label}' over ts=({self.ts_start}, {self.ts_end})")
                return True
            return False

    def _do_data_processing(self):
        # Skip if we are invalid.
        if self.status_info.result == Result.INVALID:
            return

        if self.processing_enabled:
            self._process_data()
        else:
            self._finalize_xyz_data(self.data_store)

    def _needs_refresh(self) -> bool:
        if not self.data_access_enabled:
            return False

        # One-shot flag: consumed here so a later zoom made on the X-versus-Y plot
        # itself falls back to the conservative monotonic-X criterion below.
        ts_is_time_window = getattr(self, '_ts_is_time_window', False)
        self._ts_is_time_window = False

        target_md5sum = self.calculate_data_hash()
        logger.debug(
            f"old={self._access_md5sum}, new={target_md5sum} downsampled={self.isDownsampled} and id={id(self)}")
        if self._access_md5sum is None:
            self._access_md5sum = target_md5sum
            return True
        elif self._access_md5sum != target_md5sum:
            self._access_md5sum = target_md5sum

            if AccessHelper.num_samples_override or self.isDownsampled:
                return True
            elif self.x_expr != "${self}.time":
                if ts_is_time_window:
                    # The range was propagated from a shared-time zoom made on a
                    # time plot (set_time_window); it is a valid time window no
                    # matter what the processed X samples look like, so the X
                    # column can safely be refetched and reprocessed over it.
                    return True
                x_data_incremental = all(self.x_data[i + 1] - self.x_data[i] > 0 for i in range(len(self.x_data) - 1))
                return x_data_incremental
            elif len(self.children):
                return True
            elif self.plot_type == 'PlotContour':
                return False
            elif self._contained_bounds():
                return False
            else:
                return True
        else:
            return False

    def _contained_bounds(self):
        if not hasattr(self.x_data, '__len__'):
            return
        if len(self.x_data) < 2:
            return
        xmin, xmax = self.x_data[0], self.x_data[-1]
        if all(e is not None for e in [xmin, xmax, self.ts_start, self.ts_end]):
            return (xmin < self.ts_start < xmax) and (xmin < self.ts_end < xmax)
        else:
            return False


class AccessHelper:
    """
        A simple wrapper providing single threaded data access.
        All Data requests are blocking and occur sequentially i.e, first to enter, first to exit.
        Concurrent execution is not implemented but the infrastructure is set up to not come in your way,
        should you wish to introduce concurrency.
        See fetch_data(), _submit_fetch(), on_fetch_done() and request_data()
        For ex. the input and output of request_data() are python builtins i.e, a dictionary
        compatible with pipes/queues/process-pool-executors.
    """

    da = None
    num_samples_override = False
    num_samples = 1000
    query_no = 0

    def __init__(self) -> None:
        pass

    @staticmethod
    def construct_da_params(signal: IplotSignalAdapter):
        params = dict(data_s_name=signal.data_source,
                      varname=signal.name,
                      tsS=AccessHelper.uda_ts(signal, signal.ts_start),
                      tsE=AccessHelper.uda_ts(signal, signal.ts_end),
                      tsFormat='relative' if signal.ts_relative else 'absolute',
                      pulse=signal.pulse_nb,
                      envelope=signal.envelope,
                      extremities=signal.extremities,
                      nbp=AccessHelper.num_samples if AccessHelper.num_samples_override else -1
                      )
        # retType is UDA-specific; IMASPy has no notion of calibrated data
        if signal.calibrated:
            ds = AccessHelper.da.get_data_source(signal.data_source) if AccessHelper.da else None
            if ds is None or ds.source_type == 'CODAC_UDA':
                params['retType'] = 'doubleCalibrated'
        return params

    @staticmethod
    def uda_ts(signal: IplotSignalAdapter, value):
        """Formats values as relative/absolute timestamps for UDA request or pretty print string
            Logic is to return integer if not relative time, else return float.
            if given value is an empty string or n alphabetic character or NoneType, just return None
        """
        # return str(np.datetime64(value, 'ns')) if not (signal.ts_relative or value is None) else value
        try:
            if not signal.ts_relative:
                return int(value)
            else:
                return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def str_ts(value):
        try:
            if value is not None:
                if isinstance(value, np.datetime64):
                    return value
                if isinstance(value, (int, float)) and value > 10 ** 15:
                    return np.datetime64(int(value), 'ns')
        except Exception as e:
            logger.error(f"Error {e}: Unable to convert value {value} to string timestamp")

        return value

    @staticmethod
    def get():
        return AccessHelper()

    @staticmethod
    def on_fetch_done(signal: IplotSignalAdapter, res: dict, append: bool = False):

        if not isinstance(res, dict):
            signal.set_da_fail(msg=r"¯\_(ツ)_/¯ Unknown error while fetching data")
            return

        signal.alias_map.clear()
        signal.alias_map.update(res['alias_map'])

        # we can append to existing data if required (in case of real time streaming)
        if append and len(signal.data_store[0]) > 0:
            new_store = [
                BufferObject(np.append(signal.data_store[0], res['d0'])),
                BufferObject(np.append(signal.data_store[1], res['d1'])),
                BufferObject(np.append(signal.data_store[2], res['d2'])),
                BufferObject(np.append(signal.data_store[3], res['d3'])),
            ]
        else:
            new_store = [
                BufferObject(res['d0']),
                BufferObject(res['d1']),
                BufferObject(res['d2']),
                BufferObject(res['d3']),
            ]
        logger.debug(f"on_fetch_done: {len(res['d1'])}")
        # units can be specified separately, if your data access module does not use the BufferObject subclass.
        if res.get('d0_unit'):
            new_store[0].unit = res['d0_unit']
        if res.get('d1_unit'):
            new_store[1].unit = res['d1_unit']
        if res.get('d2_unit'):
            new_store[2].unit = res['d2_unit']
        if res.get('d3_unit'):
            new_store[3].unit = res['d3_unit']
        # Single slice-assignment so a concurrent reader (e.g. a parent
        # expression's reprocess on another thread) sees either the old or
        # the new data_store, never a partially-populated one.
        signal.data_store[:] = new_store

        signal.set_da_success()

    @staticmethod
    def _submit_fetch(signal: IplotSignalAdapter):
        """This would wrap a blocking call to _request_data. For now, it is sequential.

        :param signal: the signal instance
        :type signal: IplotSignalAdapter
        """
        in_params = AccessHelper.construct_da_params(signal)
        out_params = dict()
        try:
            result = AccessHelper._request_data(**in_params)
            out_params.update(result)
            signal.isDownsampled = result['isds']
            # Update pulse_nb and legend label with the resolved value (for 0/-1 special pulses)
            if result.get('resolved_pulse') and str(signal.pulse_nb) != result['resolved_pulse']:
                old_pulse = str(signal.pulse_nb)
                signal.pulse_nb = result['resolved_pulse']
                if old_pulse and signal.label and old_pulse in signal.label:
                    signal.label = signal.label.replace(old_pulse, signal.pulse_nb)
        except Exception as e:
            # Indicate failure with message.
            if signal.pulse_nb:
                message = f"{e} for the signal: {signal.name} within the pulse: {signal.pulse_nb}"
            else:
                message = f"{e} for the signal: {signal.name}"
            signal.set_da_fail(msg=message)
            return

        # finalize function after fetch.
        AccessHelper.on_fetch_done(signal, out_params)

    def fetch_data(self, signal: IplotSignalAdapter):
        """Run a single data access request at a time.

        :param signal: the signal instance
        :type signal: IplotSignalAdapter
        """
        logger.debug(f"[UDA {AccessHelper.query_no}] Get data: {signal.name} "
                     f"ts_start={self.str_ts(signal.ts_start)} "
                     f"ts_end={self.str_ts(signal.ts_end)} "
                     f"pulse_nb={signal.pulse_nb} "
                     f"nbsamples={AccessHelper.num_samples if AccessHelper.num_samples_override else -1} "
                     f"relative={signal.ts_relative}")
        AccessHelper.query_no += 1
        AccessHelper._submit_fetch(signal)

    @staticmethod
    def _request_data(**da_params) -> dict:
        ts_s = da_params.get('tsS')
        ts_e = da_params.get('tsE')
        pulse = da_params.get('pulse')
        envelope = da_params.get('envelope')
        t_relative = da_params.get('tsFormat') == 'relative'
        # indicate if the signal was downsampled
        ds = False
        result = dict(alias_map=dict(),
                      d0=np.zeros(0),
                      d1=np.zeros(0),
                      d2=np.zeros(0),
                      d3=np.zeros(0),
                      d0_unit='',
                      d1_unit='',
                      d2_unit='',
                      d3_unit='',
                      isds=False)
        da_params.pop('envelope')  # getEnvelope does not need this.

        def np_nvl(arr):
            return np.empty(0) if arr is None else np.array(arr)

        if (ts_s is not None and ts_e is not None) or pulse is not None:

            if envelope:
                (d_env) = AccessHelper.da.get_envelope(**da_params)
                if d_env.errdesc == 'Number of samples in reply exceeds available limit. Reduce request interval,' \
                                    ' use decimation or read data by chunks.':
                    da_params.update({'nbp': AccessHelper.num_samples})
                    (d_env) = AccessHelper.da.get_envelope(**da_params)
                    ds = True
                if d_env.errcode < 0:
                    if d_env.errcode < 0:
                        message = f"ErrCode: {d_env.errcode} | getEnvelope (minimum) failed for -1 and" \
                                  f" {AccessHelper.num_samples} samples. {da_params}"
                        raise DataAccessError(message)

                xdata = np_nvl(d_env.xdata if d_env else None) if t_relative else np_nvl(
                    d_env.xdata if d_env else None)

                result['alias_map'] = {'time': {'idx': 0, 'independent': True},
                                       'dmin': {'idx': 1},
                                       'dmax': {'idx': 2},
                                       'davg': {'idx': 3}
                                       }
                result['d0'] = np_nvl(xdata)
                result['d1'] = np_nvl(d_env.ydata_min if d_env else None)
                result['d2'] = np_nvl(d_env.ydata_max if d_env else None)
                result['d3'] = np_nvl(d_env.ydata_avg if d_env else None)
                result['d0_unit'] = d_env.xunit if d_env else ''
                result['d1_unit'] = d_env.yunit if d_env else ''
                result['d2_unit'] = d_env.yunit if d_env else ''
                result['d3_unit'] = d_env.yunit if d_env else ''
                result['isds'] = ds
                if d_env and d_env.resolved_pulse:
                    result['resolved_pulse'] = d_env.resolved_pulse
                logger.debug(f"[UDA ] nbsMIN={len(d_env.ydata_min)} nbsMAX={len(d_env.ydata_max)}")

            else:
                raw = AccessHelper.da.get_data(**da_params)
                if raw.errcode < 0:
                    if raw.errdesc == 'Number of samples in reply exceeds available limit. Reduce request interval,' \
                                      ' use decimation or read data by chunks.':
                        da_params.update({'nbp': AccessHelper.num_samples})
                        raw = AccessHelper.da.get_data(**da_params)
                        ds = True
                    # if raw.errcode < 0: # try with fallback no. of points.
                    #     da_params.update({'nbp': AccessHelper.num_samples})
                    #     raw = AccessHelper.da.getData(**da_params)
                    # means no data found
                    if raw.errcode < 0:
                        message = f"ErrCode: {raw.errcode} | getData failed. Error: {raw.errdesc}"
                        raise DataAccessError(message)

                xdata = np_nvl(raw.xdata) if t_relative else np_nvl(raw.xdata).astype('int64')

                if len(xdata) > 0:
                    logger.debug(f"\tUDA samples: {len(xdata)} params={da_params}")
                    logger.debug(f"\tX range: d_min={xdata[0]} d_max={xdata[-1]} delta={xdata[-1] - xdata[0]}"
                                 f" type={xdata.dtype}")
                else:
                    logger.info(f"\tUDA samples: {len(xdata)} params={da_params}")

                result['alias_map'] = {'time': {'idx': 0, 'independent': True},
                                       'data': {'idx': 1}
                                       }
                result['d0'] = xdata
                result['d1'] = np_nvl(raw.ydata)
                result['d2'] = np.empty(0).astype('double')
                result['d3'] = np.empty(0).astype('double')
                result['d0_unit'] = raw.xunit if raw.xunit else ''
                result['d1_unit'] = raw.yunit if raw.yunit else ''
                result['d2_unit'] = ''
                result['d3_unit'] = ''
                result['isds'] = ds
                if raw.resolved_pulse:
                    result['resolved_pulse'] = raw.resolved_pulse
        else:
            raise DataAccessError(f"tsS={ts_s}, tsE={ts_e}, pulse_nb={pulse}")

        return result


class CachingAccessHelper(AccessHelper):
    """A cached layer over access helper
    """
    KEY_PROP_NAMES = ["var_name", "ts_start", "ts_end", "pulse_nb",
                      "dec_samples", "data_source", "envelope", "ts_relative"]
    CACHE_PREFIX = "/tmp/cache_"

    def __init__(self, enable_cache=False):
        super().__init__()
        self.enable_cache = enable_cache

    @staticmethod
    def get():
        return CachingAccessHelper()

    def fetch_data(self, signal: IplotSignalAdapter):
        if self.enable_cache:
            cached = self._cache_fetch(signal)
            if cached is not None:
                logger.info(f"HIT: {self._cache_filename(signal)}")
                return cached
            else:
                logger.info(f"MISS: {self._cache_filename(signal)}")
                return self._cache_put(signal, super().fetch_data(signal))
        else:
            return super().fetch_data(signal)

    def _cache_filename(self, signal: IplotSignalAdapter):
        return f"{self.CACHE_PREFIX}{hash_code(signal, self.KEY_PROP_NAMES)}"

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
    dict_result = dict()

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
        local_env.update({'self': signal})

        p = Parser()
        p.inject(Parser.get_member_list(type(signal)))
        p.inject(signal.alias_map)
        p.set_expression(expression, True)
        if not p.is_valid:
            raise InvalidExpression(f"expression: {expression} is invalid!")

        # Handle time offsets with units
        for var_name in p.var_map.keys():
            match = p.marker_in + var_name + p.marker_out + '.time'
            if expression.count(match) and p.has_time_units:
                if signal.time.unit == "nanoseconds":
                    signal.time.unit = 'ns'
                replacement = f"{match}.astype('datetime64[{signal.time.unit}]')"
                expression = expression.replace(match, replacement)
                logger.debug(f"|==> replaced {match} with {replacement}")
                logger.debug(f"expression: {expression}")

        p.clear_expr()
        p.set_expression(expression, True)
        if not p.is_valid:
            raise InvalidExpression(f"expression: {expression} is invalid!")

        # Realign the signals on which it depends if necessary
        needs_realign = False
        dependencies = list()
        tmp_local_env = dict()
        isDownsampled = False

        for var_name in signal.depends_on:
            tmp_local_env[var_name] = local_env[var_name]
            tmp_local_env[var_name].ts_start = signal.ts_start
            tmp_local_env[var_name].ts_end = signal.ts_end

            if var_name != "self":
                tmp_local_env[var_name].get_data()
                isDownsampled |= tmp_local_env[var_name].isDownsampled

            if var_name != 'self' or len(tmp_local_env[var_name].data_store[0]) != 0:
                dependencies.append(tmp_local_env[var_name])

        # Set downsampling attribute for processed signal
        if len(signal.depends_on) > 1:
            if signal.name != '':
                isDownsampled |= signal.isDownsampled
                signal.isDownsampled = isDownsampled
            else:
                signal.isDownsampled = isDownsampled

        for sig1, sig2 in zip(dependencies[:-1], dependencies[1:]):
            if not np.array_equal(sig1.data_store[0], sig2.data_store[0]):
                needs_realign = True
                break

        if needs_realign and not ParserHelper.dict_result:
            kind = ParserHelper.resolve_alignment_kind(signal, dependencies)
            logger.debug(f"mint#120: evaluate '{expression}': realigning "
                        f"{[getattr(d, 'label', '?') for d in dependencies]} "
                        f"(time bases: {[(len(d.data_store[0]), getattr(d.data_store[0], 'unit', '?')) for d in dependencies]}, "
                        f"kind={kind})")
            ParserHelper.dict_result = align(dependencies, signal, kind=kind)
            signal.set_data(tmp_local_env['self'].data_store)

        p.clear_expr()
        p.set_expression(expression, True)
        p.substitute_var(tmp_local_env, ParserHelper.dict_result)
        p.eval_expr()
        if p.has_time_units:
            result = p.result.astype('int64')
        else:
            result = p.result
        p.clear_expr()

        # Crop the result of a pure expression signal (empty name, e.g. MINT's
        # X-versus-Y rows) to its requested time window. Dependencies may
        # legitimately hold a superset of the window: once a zoom drops below the
        # downsampling threshold their buffers contain raw data covering more than
        # the requested range and are not refetched on deeper zooms. Time plots
        # crop through the axis view, but an X-versus-Y signal derives its X from
        # the dependency *values*, so without cropping its range stays that of the
        # whole buffer and the axis no longer follows the zoom (mint#120).
        if (getattr(signal, 'name', '') == ''
                and isinstance(signal.ts_start, (int, float))
                and isinstance(signal.ts_end, (int, float))
                and hasattr(result, '__len__')):
            base = None
            if ParserHelper.dict_result:
                base = next(iter(ParserHelper.dict_result.values())).get('time')
            elif dependencies:
                base = dependencies[0].data_store[0]
            if base is not None and len(base) == len(result):
                base_arr = np.asarray(base)
                if np.issubdtype(base_arr.dtype, np.number):
                    mask = (base_arr >= signal.ts_start) & (base_arr <= signal.ts_end)
                    if mask.any() and not mask.all():
                        logger.debug(f"mint#120: cropping '{expression}' result to ts window: "
                                    f"{int(mask.sum())}/{len(result)} samples kept")
                        result = result[mask]
                        base_arr = base_arr[mask]
                    elif not mask.any():
                        logger.debug(f"mint#120: ts window [{signal.ts_start}, {signal.ts_end}] does not "
                                    f"overlap the evaluated time base of '{expression}'; keeping the "
                                    f"full buffer ({len(result)} samples)")
                    # Retain the time base the expression was evaluated over: it
                    # is what allows a zoom made on the X-versus-Y plot to be
                    # mapped back to a time window when the X column is strictly
                    # monotonic (mint#120 reverse direction). Kept consistent
                    # with any cropping applied to the result above.
                    signal._expr_time_base = base_arr
        return result

    @staticmethod
    def resolve_alignment_kind(signal, dependencies) -> str:
        """Interpolation kind for realigning the dependencies of ``signal``.

        An explicit InterpolationKind set on the signal wins. With the default
        'auto', linear interpolation is chosen only when *every* dependency is
        raw (not downsampled) and its observed sample rate is above
        CONTINUOUS_RATE_THRESHOLD_HZ. Downsampled buffers keep sample-and-hold:
        their grid is the downsampler's, not the signal's, so no assumption is
        made from it. Any dependency below the threshold is treated as
        event-driven — a new value is only published on change — and keeps
        sample-and-hold ('previous') for the whole alignment, which never
        invents values between updates (mint#120).
        """
        preference = getattr(signal, 'interpolation', None) or INTERPOLATION_AUTO
        if preference != INTERPOLATION_AUTO:
            return preference

        for dep in dependencies:
            if getattr(dep, 'isDownsampled', False):
                # Downsampled buffers keep the conservative default: their grid
                # is the downsampler's, not the signal's, so no assumption about
                # the native sampling is made from it.
                return InterpolationKind.PREVIOUS
            base = dep.data_store[0]
            n = len(base)
            if n < 2:
                return InterpolationKind.PREVIOUS
            t0, t1 = float(base[0]), float(base[-1])
            span = abs(t1 - t0)
            if span <= 0:
                return InterpolationKind.PREVIOUS
            # Large values encode nanosecond timestamps (same heuristic as the
            # date detection elsewhere in the code base).
            span_s = span / 1e9 if max(abs(t0), abs(t1)) > (1 << 53) else span
            if (n - 1) / span_s < CONTINUOUS_RATE_THRESHOLD_HZ:
                return InterpolationKind.PREVIOUS
        return InterpolationKind.LINEAR

    @staticmethod
    def get_dependencies(expr_list: list) -> set:
        dependencies = set()
        for expr in expr_list:
            while True:
                if expr.find(Parser.marker_in) == -1 or expr.find(Parser.marker_out) == -1:
                    break
                marker_in_pos = expr.find(Parser.marker_in)
                marker_out_pos = expr.find(Parser.marker_out)
                var = expr[marker_in_pos + len(Parser.marker_in):marker_out_pos]
                match = Parser.marker_in + var + Parser.marker_out
                replc = 'X'
                expr = expr.replace(match, replc)
                dependencies.add(var)
        return dependencies
