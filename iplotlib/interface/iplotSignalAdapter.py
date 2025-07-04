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
from collections import defaultdict
from dataclasses import dataclass, field, fields
import numpy as np
import os
import typing

from iplotlib.interface.utils import string_classifier
from iplotProcessing.common.errors import InvalidExpression
from iplotProcessing.core import BufferObject
from iplotProcessing.core import Signal as ProcessingSignal
from iplotProcessing.math.pre_processing.grid_mixing import align
from iplotProcessing.tools.parsers import Parser
from iplotProcessing.tools import hash_code

from iplotLogging import setupLogger

logger = setupLogger.get_logger(__name__)

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
    isDownsampled: bool = False
    x_expr: str = '${self}.time'
    y_expr: str = '${self}.data_store[1]'
    z_expr: str = '${self}.data_store[2]'
    extremities: bool = False
    plot_type: str = ''
    children: typing.List[IplotSignalAdapterT] = field(default_factory=list)
    status_info: StatusInfo = None
    data_access_enabled: bool = True
    processing_enabled: bool = True
    time_out_value: float = 60  # Unimplemented  ---> REVIEW: purpose of this attribute?

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

        # 2. Post-initialize ArraySignal's properties and our name.
        self._init_label()

        # 3. Help keep track of data access parameters.
        self._access_md5sum = None

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
        return hash_code(self, ["ts_start", "ts_end", "pulse_nb"])

    def get_data(self):
        # 1. Populate time, data_primary, data_secondary (if needed)
        if self._do_data_access():
            # 2. Use iplotProcessing to evaluate x_data, y_data, z_data
            self._do_data_processing()

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
    def acquire_shape(source: BufferObject, target: BufferObject) -> BufferObject:
        """Modify `source` such that shape(`source`) == shape(`target`)

        :param source: This object will acquire its shape from `target` if it is not the same.
        :type source: BufferObject
        :param target: This object will dictate the shape of `source`
        :type target: BufferObject
        :return: The new modified `source` object.
        :rtype: BufferObject
        """
        if np.isscalar(source):
            return BufferObject([source] * len(target))
        elif target.ndim == source.ndim:
            if len(source) != len(target) and len(source) == 1:
                logger.warning(
                    f"Caught x-target shape mismatch! Fixing it. len(source) = {len(source)} -> {len(target)}")
                return BufferObject(np.linspace(source[0], source[-1], len(target)), unit=source.unit)
            else:
                return source
        else:
            return source  # CHECK: Modify ndims

    def compute(self, **kwargs) -> dict:
        data_arrays = dict()
        # Evaluate each expression.
        for key, expr in kwargs.items():
            try:
                logger.debug(f" in compute key={key} expr={expr}")
                data_arrays.update({key: ParserHelper.evaluate(self, expr)})
            except Exception as e:
                logger.error(f"Error {e} in {expr}")
                continue
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

    def set_da_success(self):
        self.status_info.reset()
        self.status_info.stage = Stage.DA
        self.status_info.result = Result.SUCCESS
        self.status_info.num_points = len(self.data_store[0])
        self.status_info.inf = int(np.sum(np.isinf(self.data_store[1])))

    def set_da_fail(self, msg: str = ''):
        self.status_info.reset()
        self.status_info.stage = Stage.DA
        self.status_info.result = Result.FAIL
        self.status_info.msg = msg
        self.status_info.num_points = 0
        logger.warning(f"Data Access Error: {msg}")

    def set_proc_success(self):
        self.status_info.reset()
        self.status_info.stage = Stage.PROC
        self.status_info.num_points = len(self.x_data)
        self.status_info.inf = int(np.sum(np.isinf(self.y_data)))
        self.status_info.result = Result.SUCCESS

    def set_proc_fail(self, msg: str = ''):
        self.status_info.reset()
        self.status_info.stage = Stage.PROC
        self.status_info.result = Result.FAIL
        self.status_info.msg = msg
        self.status_info.num_points = 0
        logger.warning(f"Processing Error: {msg}")

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
        self.y_data = self.acquire_shape(self.y_data, self.x_data)

        # 3. Fix x-z shape mismatch.
        self.z_data = self.acquire_shape(self.z_data, self.x_data)

        self._report_xyz_data()

    def _process_data(self):
        # 1. Cannot process data when _fetch_data failed or did not occur
        if self.data_access_enabled and self.status_info.result != Result.SUCCESS:
            return

        # 2.Handle child signals.
        # Note: In this case, `self.name` is an expression, so prior to applying x,y,z we evaluate `self.name`
        if len(self.children):
            vm = dict(self._local_env)
            vm.update(ParserHelper.env)  # makes aliases accessible to parser

            # 2.1 Ensure all child signals have their time, data vectors (if DA enabled)
            children_data = defaultdict(list)
            for c, child in enumerate(self.children):
                if child.data_access_enabled and child._needs_refresh():
                    child._fetch_data()
                child._process_data()
                if len(self.children) > 1:
                    for ds in child.data_store:
                        children_data[c].append(ds.copy())

            # 2.2 Align all signals onto a common grid.
            if len(self.children) > 1:
                align(self.children)  # ,mode=self.alignment_mode, kind=self.interpolation_kind)

            # 2.2 Evaluate self.name. It is an expression combining multiple other signals.
            try:
                p = Parser().set_expression(self.name)
                p.substitute_var(vm)
                p.eval_expr()
                if isinstance(p.result, ProcessingSignal):
                    # Update first four buffers via slice assignment, auto-expanding as needed
                    self.data_store[:4] = p.result.data_store[:4]
                else:
                    self.set_proc_fail(f"Result of expression={self.name} is not an instance of {type(self).__name__}")
                    return
            except Exception as e:
                self.set_proc_fail(msg=str(e))
            finally:
                # restore backup.
                if len(self.children) > 1:
                    for c, child in enumerate(self.children):
                        child.data_store.clear()
                        for ds in children_data[c]:
                            child.data_store.append(ds)

        if self.status_info.result == Result.FAIL:
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
            # ask child signals to fetch data
            for child in self.children:
                if child._needs_refresh():
                    child._fetch_data()
                if child.status_info.result == Result.FAIL:
                    self.set_da_fail(msg=child.status_info.msg)  # get exact reason for failure from child.
                    break
            else:  # Fell through, all children succeded
                self.set_da_success()
        else:
            # submit a fetch request for ourself.
            CachingAccessHelper.get().fetch_data(self)

    def _do_data_access(self):
        # Skip if we are invalid.
        if self.status_info.result == Result.INVALID:
            return False

        # no name implies there is no need to request data. (we don't have a variable to ask the data source.)
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
        return dict(data_s_name=signal.data_source,
                    varname=signal.name,
                    tsS=AccessHelper.uda_ts(signal, signal.ts_start),
                    tsE=AccessHelper.uda_ts(signal, signal.ts_end),
                    tsFormat='relative' if signal.ts_relative else 'absolute',
                    pulse=signal.pulse_nb,
                    envelope=signal.envelope,
                    extremities=signal.extremities,
                    nbp=AccessHelper.num_samples if AccessHelper.num_samples_override else -1
                    )

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
                    return np.datetime64(value, 'ns')
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
            signal.data_store[0] = BufferObject(np.append(signal.data_store[0], res['d0']))
            signal.data_store[1] = BufferObject(np.append(signal.data_store[1], res['d1']))
            signal.data_store[2] = BufferObject(np.append(signal.data_store[2], res['d2']))
            signal.data_store[3] = BufferObject(np.append(signal.data_store[3], res['d3']))
        else:
            signal.data_store.clear()
            signal.data_store.append(BufferObject(res['d0']))
            signal.data_store.append(BufferObject(res['d1']))
            signal.data_store.append(BufferObject(res['d2']))
            signal.data_store.append(BufferObject(res['d3']))
        logger.debug(f"on_fetch_done: {len(res['d1'])}")
        # units can be specified separately, if your data access module does not use the BufferObject subclass.
        if res.get('d0_unit'):
            signal.data_store[0].unit = res['d0_unit']
        if res.get('d1_unit'):
            signal.data_store[1].unit = res['d1_unit']
        if res.get('d2_unit'):
            signal.data_store[2].unit = res['d2_unit']
        if res.get('d3_unit'):
            signal.data_store[3].unit = res['d3_unit']

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
        for var_name in signal.depends_on:
            tmp_local_env[var_name] = local_env[var_name]
            tmp_local_env[var_name].ts_start = signal.ts_start
            tmp_local_env[var_name].ts_end = signal.ts_end
            if var_name != "self":
                tmp_local_env[var_name].get_data()
            if var_name != 'self' or len(tmp_local_env[var_name].data_store[0]) != 0:
                dependencies.append(tmp_local_env[var_name])

        for sig1, sig2 in zip(dependencies[:-1], dependencies[1:]):
            if not np.array_equal(sig1.data_store[0], sig2.data_store[0]):
                needs_realign = True
                break

        if needs_realign:
            align(dependencies)
            signal.set_data(tmp_local_env['self'].data_store)

        p.clear_expr()
        p.set_expression(expression, True)
        p.substitute_var(tmp_local_env)
        p.eval_expr()
        if p.has_time_units:
            return p.result.astype('int64')
        else:
            return p.result

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
