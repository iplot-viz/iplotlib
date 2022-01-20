from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass, field
from functools import partial, wraps
import numpy as np
from queue import Empty, Queue
import threading
from typing import Any, Callable, Collection, Dict, List, Set
import weakref

from iplotlib.core.axis import Axis, RangeAxis
from iplotlib.core.canvas import Canvas
from iplotlib.core.limits import IplPlotViewLimits, IplAxisLimits
from iplotlib.core.plot import Plot
from iplotlib.core.signal import Signal
import iplotLogging.setupLogger as sl

from iplotlib.core.history_manager import HistoryManager
from iplotlib.core.property_manager import PropertyManager

logger = sl.get_logger(__name__)

@dataclass(frozen=True, eq=True)
class ImplementationPlotCacheItem:
    canvas: weakref.ReferenceType=None
    plot: weakref.ReferenceType=None
    stack_key: str = ''
    signals: List[weakref.ReferenceType] = field(default_factory=list)
    offsets: Dict[int, int] = field(default_factory=lambda:defaultdict(lambda:None))

class ImplementationPlotCacheTable:
    def __init__(self) -> None:
        pass
    
    def register(self, impl_obj: Any, canvas: Canvas=None, plot: Plot=None, stack_key: str='', signals: List[Signal]=[]):
        cache_item = ImplementationPlotCacheItem(
            canvas=weakref.ref(canvas),
            plot=weakref.ref(plot),
            stack_key=stack_key,
            signals=[weakref.ref(sig) for sig in signals])
        impl_obj._ipl_cache_item = cache_item

    def drop(self, impl_obj: Any):
        if hasattr(impl_obj, '_ipl_cache_item'):
            del impl_obj._ipl_cache_item

    def get_cache_item(self, impl_obj: Any) -> ImplementationPlotCacheItem:
        return impl_obj._ipl_cache_item if hasattr(impl_obj, '_ipl_cache_item') else None
    
    def transform_value(self, impl_obj: Any, ax_idx: int, value: Any, inverse=False):
        """Adds or subtracts axis offset from value trying to preserve type of offset (ex: does not convert to
        float when offset is int)"""
        base = 0
        ci = self.get_cache_item(impl_obj)
        if hasattr(ci, 'offsets') and ci.offsets[ax_idx] is not None:
            base = ci.offsets[ax_idx]
            if isinstance(base, int) or base.dtype.name == 'int64':
                value = int(value)
        return value - base if inverse else value + base

class BackendParserBase(ABC):
    def __init__(self, canvas: Canvas=None, focus_plot=None, focus_plot_stack_key=None, impl_flush_method: Callable=None) -> None:
        """An abstract graphics parser for iplotlib.
            Graphics implementations should subclass this base class.
        """
        super().__init__()
        self.canvas = canvas
        self._hm = HistoryManager()
        self._pm = PropertyManager()
        self._impl_plot_cache_table = ImplementationPlotCacheTable()
        self._impl_flush_method = impl_flush_method
        self._impl_task_queue = Queue()
        self._impl_draw_thread = threading.current_thread()
        self._focus_plot = focus_plot
        self._focus_plot_stack_key = focus_plot_stack_key
        self._layout = None
        self._axis_impl_plot_lut = weakref.WeakValueDictionary() # type: Dict[Axis, Any] # key is id(Axis)
        self._plot_impl_plot_lut = defaultdict(list) # type: Dict[Plot, List[Any]] # key is id(Plot)
        self._signal_impl_plot_lut = weakref.WeakValueDictionary() # type: Dict[Signal, Any] # key is id(Signal)
        self._signal_impl_shape_lut = dict() # type: Dict[Signal, Any] # key is id(Signal)
        self._stale_citems = list() # type: List[ImplementationPlotCacheItem]
        self._impl_plot_ranges_hash = defaultdict(lambda: defaultdict(dict)) # type: Dict[Any, int] # key is id(impl_plot)

    def run_in_one_thread(func):
        """
        A decorator that causes all matplotlib operations to execute in the main thread (self._impl_draw_thread) even if these functions were called in other threads
        - if self._impl_flush_method is None then decorated method is executed immediately
        - if self._impl_flush_method is not None then decorated method will be executed immediately as long as current thread is the same as self._impl_draw_thread,
          in other case it will be queued for later execution and self._impl_flush_method should process this queue in the draw thread
        """
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            if threading.current_thread() == self._impl_draw_thread or self._impl_flush_method is None:
                return func(self, *args, **kwargs)
            else:
                self._impl_task_queue.put(partial(func, self, *args, **kwargs))
                self._impl_flush_method()

        return wrapper

    @run_in_one_thread
    def process_work_queue(self):
        try:
            work_item = self._impl_task_queue.get_nowait()
            work_item()
        except Empty:
            logger.debug("Nothing to do.")

    @run_in_one_thread
    def refresh_data(self):
        logger.debug(f"Stale cItems : {self._stale_citems}")
        for ci in self._stale_citems:
            if ci is None:
                continue
            signals = ci.signals
            for signal_ref in signals:
                self.process_ipl_signal(signal_ref())
        self.unstale_cache_items()

    @abstractmethod
    def export_image(self, filename: str, **kwargs):
        pass

    @abstractmethod
    def clear(self):
        """Clear the lookup tables. 
            Implementations can and should clean up any other helper LUTs they might create.
            It is also a good idea to clear your layout in the implementation.
        """
        self._axis_impl_plot_lut.clear()
        self._plot_impl_plot_lut.clear()
        self._signal_impl_plot_lut.clear()
        self._signal_impl_shape_lut.clear()

    @abstractmethod
    def process_ipl_canvas(self, canvas: Canvas):
        """Prepare the implementation canvas.

        :param canvas: A Canvas instance
        :type canvas: Canvas
        """

    @abstractmethod
    def process_ipl_plot(self, plot: Plot, column: int, row: int):
        """Prepare the implementation plot.

        :param plot: A Plot instance
        :type plot: Plot
        """
    
    @abstractmethod
    def process_ipl_axis(self, axis: Axis, ax_idx: int, plot: Plot, impl_plot: Any):
        """Prepare the implementation axis.

        :param plot: An Axis instance
        :type axis: Axis
        """
    
    @abstractmethod
    @run_in_one_thread
    def process_ipl_signal(self, signal: Signal):
        """Prepare the implementation shape for the plot of a signal.

        :param signal: A Signal instance
        :type signal: Signal
        """

    def update_range_axis(self, range_axis: RangeAxis, ax_idx: int, impl_plot: Any, which='current'):
        """If axis is a RangeAxis update its min and max to implementation chart's view limits"""
        if not isinstance(range_axis, RangeAxis):
            return
        limits = self.get_oaw_axis_limits(impl_plot, ax_idx)
        if which == 'current':
            range_axis.begin = limits[0]
            range_axis.end = limits[1]
        else: # which == 'original'
            range_axis.original_begin = range_axis.begin
            range_axis.original_end = range_axis.end
        logger.debug(f"Axis update: impl_plot={id(impl_plot)} range_axis={id(range_axis)} ax_idx={ax_idx} {range_axis}")

    def update_multi_range_axis(self, range_axes: Collection[RangeAxis], ax_idx: int, impl_plot: Any):
        """Updates RangeAxis instances begin and end to mpl_axis limits. Works also on stacked axes"""
        ax_ranges = []
        for ax in range_axes:
            if ax_idx == 0:
                self.update_range_axis(ax, ax_idx, impl_plot)
                ax_ranges.append([ax.begin, ax.end])
            else:
                if isinstance(ax, RangeAxis):
                    self.update_range_axis(ax, ax_idx, self._axis_impl_plot_lut.get(id(ax)))
                    ax_ranges.append([ax.begin, ax.end])
                else:
                    ax_ranges.append([None, None])
        return ax_ranges

    @abstractmethod
    def set_impl_plot_limits(self, impl_plot: Any, ax_idx: int, limits: tuple) -> bool:
        """Implementation must set the view limits on `ax_idx` axis to the tuple `limits`
        Returns True if the limits were successfully set, False otherwise
        """

    @abstractmethod
    def set_focus_plot(self, impl_plot: Any):
        """Sets the focus plot."""

    def undo(self):
        self._hm.undo()
    
    def redo(self):
        self._hm.redo()
    
    def drop_history(self):
        self._hm.drop()
    
    def unstale_cache_items(self):
        self._stale_citems.clear()

    def get_all_plot_limits(self, which='current') -> List[IplPlotViewLimits]:
        all_limits = []
        if not isinstance(self.canvas, Canvas):
            return all_limits
        for col in self.canvas.plots:
            for plot in col:
                plot_lims = self.get_plot_limits(plot, which)
                if not isinstance(plot_lims, IplPlotViewLimits):
                    continue
                all_limits.append(plot_lims)
        return all_limits

    def get_plot_limits(self, plot: Plot, which='current') -> IplPlotViewLimits:
        if not isinstance(self.canvas, Canvas) or not isinstance(plot, Plot):
            return None
        plot_lims = IplPlotViewLimits(plot_ref=weakref.ref(plot))
        for axes in plot.axes:
            if isinstance(axes, Collection):
                for axis in axes:
                    if isinstance(axis, RangeAxis):
                        begin, end = axis.get_limits(which)
                        plot_lims.axes_ranges.append(IplAxisLimits(begin, end, weakref.ref(axis)))
            elif isinstance(axes, RangeAxis):
                axis = axes # singular name is easier to read for single axis
                begin, end = axis.get_limits(which)
                plot_lims.axes_ranges.append(IplAxisLimits(begin, end, weakref.ref(axis)))
        return plot_lims

    def set_plot_limits(self, limits: IplPlotViewLimits):
        i = 0
        plot = limits.plot_ref()
        ax_limits = limits.axes_ranges
        for ax_idx, axes in enumerate(plot.axes):
            if isinstance(axes, Collection):
                for axis in axes:
                    if isinstance(axis, RangeAxis):
                        impl_plot = self._axis_impl_plot_lut.get(id(axis))
                        if not self.set_impl_plot_limits(impl_plot, ax_idx, [ax_limits[i].begin, ax_limits[i].end]):
                            axis.begin = ax_limits[i].begin
                            axis.end = ax_limits[i].end
                        i += 1
            elif isinstance(axes, RangeAxis):
                axis = axes
                impl_plot = self._axis_impl_plot_lut.get(id(axis))
                if not self.set_impl_plot_limits(impl_plot, ax_idx, [ax_limits[i].begin, ax_limits[i].end]):
                    axis.begin = ax_limits[i].begin
                    axis.end = ax_limits[i].end
                i += 1
        self.refresh_data()

    @staticmethod
    def create_offset(vals):
        """Given a collection of values determine if creting offset is necessary and return it
        Returns None otherwise"""
        if isinstance(vals, Collection) and len(vals) > 0:
            if ((hasattr(vals, 'dtype') and vals.dtype.name == 'int64')
                    or (type(vals[0]) == int)
                    or isinstance(vals[0], np.int64)) and vals[0] > 10**15:
                return vals[0]
        if isinstance(vals, Collection) and len(vals) > 0:
            if ((hasattr(vals, 'dtype') and vals.dtype.name == 'uint64')
                    or (type(vals[0]) == int)
                    or isinstance(vals[0], np.uint64)) and vals[0] > 10**15:
                return vals[0]
        return None

    def get_value(self, impl_plot: Any, ax_idx: int, data_sample):
        """Offset-aware get axis value"""
        return self.transform_value(impl_plot, ax_idx, data_sample)

    @abstractmethod
    def get_impl_x_axis(self, impl_plot: Any):
        """Implementations should return the x axis"""

    @abstractmethod
    def get_impl_y_axis(self, impl_plot: Any):
        """Implementations should return the y axis"""

    def get_impl_axis(self, impl_plot: Plot, axis_idx):
        """Convenience method that gets matplotlib axis by index instead of using separate methods get_xaxis/get_yaxis"""
        if 0 <= axis_idx <= 1:
            return [self.get_impl_x_axis, self.get_impl_y_axis][axis_idx](impl_plot)
        return None

    @abstractmethod
    def get_impl_x_axis_limits(self, impl_plot: Any):
        """Implementations should return the x range"""

    @abstractmethod
    def get_impl_y_axis_limits(self, impl_plot: Any):
        """Implementations should return the y range"""

    @abstractmethod
    def get_oaw_axis_limits(self, impl_plot: Any, ax_idx: int):
        """Offset-aware version of implementation's get_x_limits, get_y_limits"""

    @abstractmethod
    def set_impl_x_axis_limits(self, impl_plot: Any, limits: tuple):
        """Implementations should set the x range"""

    @abstractmethod
    def set_impl_y_axis_limits(self, impl_plot: Any, limits: tuple):
        """Implementations should set the y range"""

    @abstractmethod
    def set_oaw_axis_limits(self, impl_plot: Any, ax_idx: int, limits):
        """Offset-aware version of implementation's set_x_limits, set_y_limits"""

    @abstractmethod
    def transform_value(self, impl_plot: Any, ax_idx: int, value: Any, inverse=False):
        """Adds or subtracts axis offset from value trying to preserve type of offset (ex: does not convert to
        float when offset is int)"""

    @abstractmethod
    def transform_data(self, impl_plot: Any, data):
        """This function post processes data if it cannot be plot with matplotlib directly.
        Currently it transforms data if it is a large integer which can cause overflow in matplotlib"""
