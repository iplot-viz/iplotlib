"""
The BackendParserBase class parses the :data:`~iplotlib.core.canvas.Canvas` object
and translates its properties to implementation specific objects.

It uses a caching mechanism to store references to abstract iplotlib objects 
in the implementation plot object for later retrieval in event callbacks.

See :data:`~iplotlib.core.impl_base.ImplementationPlotCacheItem` and :data:
`~iplotlib.core.impl_base.ImplementationPlotCacheTable`

"""

# Author: Jaswant Sai Panchumarti

from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass, field
from functools import partial, wraps
import numpy as np
from queue import Empty, Queue
import threading
from typing import Any, Callable, Collection, Dict, List, Optional, Union
import weakref

from iplotProcessing.core import BufferObject
from iplotlib.core.axis import Axis, RangeAxis, LinearAxis
from iplotlib.core.canvas import Canvas
from iplotlib.core.limits import IplPlotViewLimits, IplAxisLimits, IplSignalLimits, IplSliderLimits
from iplotlib.core.plot import Plot, PlotXY, PlotXYWithSlider, PlotContour
from iplotlib.core.signal import Signal, SignalXY, SignalContour
import iplotLogging.setupLogger as Sl

from iplotlib.core.history_manager import HistoryManager
from iplotlib.core.property_manager import PropertyManager

logger = Sl.get_logger(__name__)


@dataclass(frozen=True, eq=True)
class ImplementationPlotCacheItem:
    """
    This cache item holds weak references to objects that can be fetched later on in event callbacks.
    """
    canvas: weakref.ReferenceType = None
    plot: weakref.ReferenceType = None
    stack_key: str = ''
    signals: List[weakref.ReferenceType] = field(default_factory=list)
    offsets: Dict[int, int] = field(default_factory=lambda: defaultdict(lambda: None))


class ImplementationPlotCacheTable:
    """
    A manager of objects of type :data:`iplotlib.core.impl_base.ImplementationPlotCacheItem`
    """

    def __init__(self) -> None:
        pass

    @staticmethod
    def register(impl_obj: Any, canvas: Canvas = None, plot: Plot = None, stack_key: str = '',
                 signals: List[Signal] = None):
        """
        Register the other arguments to the implementation plot(`impl_obj`)
        """
        if signals is None:
            signals = []

        cache_item = ImplementationPlotCacheItem(
            canvas=weakref.ref(canvas),
            plot=weakref.ref(plot),
            stack_key=stack_key,
            signals=[weakref.ref(sig) for sig in signals])
        impl_obj._ipl_cache_item = cache_item

    @staticmethod
    def drop(impl_obj: Any):
        """
        Delete the cache item associated with `impl_obj`
        """
        if hasattr(impl_obj, '_ipl_cache_item'):
            del impl_obj._ipl_cache_item

    @staticmethod
    def get_cache_item(impl_obj: Any) -> ImplementationPlotCacheItem:
        """
        Get the cache item associated with `impl_obj`
        """
        return impl_obj._ipl_cache_item if hasattr(impl_obj, '_ipl_cache_item') else None

    def transform_value(self, impl_obj: Any, ax_idx: int, value: Any, inverse=False):
        """
        Adds or subtracts axis offset from value trying to preserve type of offset (ex: does not convert to
        float when offset is int)
        """
        base = 0
        ci = self.get_cache_item(impl_obj)
        if hasattr(ci, 'offsets') and ci.offsets[ax_idx] is not None:
            base = ci.offsets[ax_idx]
            if isinstance(base, int) or type(base).__name__ == 'int64':
                value = int(value)
        return value - base if inverse else value + base
        # return value / 10000 if inverse else value * 10000


class BackendParserBase(ABC):
    """
    An abstract graphics parser for iplotlib.
    Graphics implementations should subclass this base class.

    This class does many convenient things that do not require direct access
    to instances of the graphic implementation classes.
    """

    def __init__(self, canvas: Canvas = None, focus_plot=None, focus_plot_stack_key=None,
                 impl_flush_method: Callable = None) -> None:

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
        self._axis_impl_plot_lut = weakref.WeakValueDictionary()  # type: Dict[int, Any] # key is id(Axis)
        self._plot_impl_plot_lut = defaultdict(list)  # type: Dict[int, List[Any]] # key is id(Plot)
        self._signal_impl_plot_lut = weakref.WeakValueDictionary()  # type: Dict[str, Any] # key is (Signal.uid)
        self._signal_impl_shape_lut = dict()  # type: Dict[int, Any] # key is id(Signal)
        self._stale_citems = list()  # type: List[ImplementationPlotCacheItem]
        self._impl_plot_ranges_hash = defaultdict(
            lambda: defaultdict(dict))  # type: Dict[Any, int] # key is id(impl_plot)

    def run_in_one_thread(func):
        """
        A decorator that causes all matplotlib operations to execute in the main thread (self._impl_draw_thread) even
        if these functions were called in other threads
        - if self._impl_flush_method is None then decorated method is executed immediately.
        - if self._impl_flush_method is not None then decorated method will be executed immediately as long as current
          thread is the same as self._impl_draw_thread, in other case it will be queued for later execution and
          self._impl_flush_method should process this queue in the draw thread.
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
        """
        All stale plots are updated here.
        """
        logger.debug(f"Stale cItems : {self._stale_citems}")
        for ci in self._stale_citems:
            if ci is None:
                continue
            signals = ci.signals
            for signal_ref in signals:
                self.process_ipl_signal(signal_ref())
            plot = ci.plot()
            for stack_id, key in enumerate(sorted(plot.signals.keys())):
                mpl_axes = self._plot_impl_plot_lut[id(ci.plot())][stack_id]
                for ax_idx in range(len(plot.axes)):
                    if isinstance(plot.axes[ax_idx], Collection):
                        axis = plot.axes[ax_idx][stack_id]
                        self.process_ipl_axis(axis, ax_idx, plot, mpl_axes)
                    else:
                        axis = plot.axes[ax_idx]
                        self.process_ipl_axis(axis, ax_idx, plot, mpl_axes)
        self.unstale_cache_items()

    @abstractmethod
    def autoscale_y_axis(self, impl_plot):
        pass

    @abstractmethod
    def export_image(self, filename: str, **kwargs):
        pass

    @abstractmethod
    def clear(self):
        """
        Clear the lookup tables.
        Implementations can and should clean up any other helper LUTs they might create.
        It is also a good idea to clear your layout in the implementation.
        """
        self._axis_impl_plot_lut.clear()
        self._plot_impl_plot_lut.clear()
        self._signal_impl_plot_lut.clear()
        self._signal_impl_shape_lut.clear()

    def process_ipl_canvas(self, canvas: Canvas):
        """
        Prepare the implementation canvas.

        :param canvas: A Canvas instance
        :type canvas: Canvas
        """
        if canvas is not None:
            logger.debug(f"ipl_canvas 1: {self._pm.get_value(canvas, 'step')}")
        if canvas is None:
            self.canvas = canvas
            self.clear()
            return

        # 1. Clear layout.
        self.clear()

        # 2. Allocate
        self.canvas = canvas
        if self._focus_plot is None:
            self.canvas.focus_plot = None
            self.set_canvas_gridspec(canvas.rows, canvas.cols)
        else:
            self.canvas.focus_plot = self._focus_plot
            self.set_canvas_gridspec(1, 1)

        # 3. Fill the canvas with plots.
        for i, col in enumerate(canvas.plots):
            for j, plot in enumerate(col):
                if self._focus_plot is not None:
                    if self._focus_plot == plot:
                        logger.debug(f"Focusing on plot: {plot}")
                        self.process_ipl_plot(plot, 0, 0)
                    elif isinstance(plot, PlotXYWithSlider):
                        plot.slider = None
                else:
                    self.process_ipl_plot(plot, i, j)

        # 4. Update the title at the top of canvas.
        if self._pm.get_value(self.canvas, 'title') is not None:
            if not self._pm.get_value(self.canvas, 'font_size'):
                canvas.font_size = None
            self.set_suptitle(self._pm.get_value(self.canvas, 'title'),
                              font_size=self._pm.get_value(self.canvas, 'font_size'),
                              font_color=self._pm.get_value(self.canvas, 'font_color') or 'black')

    def set_canvas_gridspec(self, rows: int, cols: int):
        """
        Set the canvas gridspec for the implementation.
        This is called when the canvas is set or cleared.
        """
        pass

    @abstractmethod
    def set_suptitle(self, title: str, font_size: int = None, font_color: str = 'black'):
        """
        Set the canvas suptitle.
        This is called when the canvas is set or cleared.
        """

    @abstractmethod
    def process_ipl_plot(self, plot: Plot, column: int, row: int):
        """
        Prepare the implementation plot.

        :param plot: A Plot instance
        :param column: Specific column
        :param row: Specific row
        :type plot: Plot
        :type column: int
        :type row: int
        """

    @abstractmethod
    def process_ipl_log_axis(self, axis: Any, plot: Plot):
        """
        Prepare the implementation axis.

        :param axis
        :param ax_idx
        :param plot: An Axis instance
        :param impl_plot
        :type axis: Axis
        :type ax_idx: int
        :type plot: Plot
        :type impl_plot: Any
        """

    @abstractmethod
    def process_ipl_axis_params(self, fc, fs, axis: Axis, impl_axis: Any):
        """
        param
        """

    @abstractmethod
    def process_ipl_axis_formatter(self, impl_plot: Any, axis_item: Any, ax_idx: int):
        pass

    @abstractmethod
    def process_ipl_axis_ticks(self, tick_number, impl_plot: Any):
        pass

    def process_ipl_axis(self, axis: Axis, ax_idx: int, plot: Plot, impl_plot: Any):
        """
        Prepare the implementation axis.

        :param axis
        :param ax_idx
        :param plot: An Axis instance
        :param impl_plot
        :type axis: Axis
        :type ax_idx: int
        :type plot: Plot
        :type impl_plot: Any
        """

        axis_item = self.get_impl_axis(impl_plot, ax_idx)
        self._axis_impl_plot_lut.update({id(axis): impl_plot})

        if isinstance(axis, Axis):
            self.process_ipl_log_axis(axis_item, plot)

            fc = self._pm.get_value(axis, 'font_color')
            fs = self._pm.get_value(axis, 'font_size')

            axis_item._font_color = fc
            axis_item._font_size = fs
            axis_item._label = axis.label

            self.process_ipl_axis_params(fc, fs, axis, axis_item)

        if isinstance(axis, RangeAxis) and axis.begin is not None and axis.end is not None:
            if self._pm.get_value(self.canvas, 'autoscale') and ax_idx == 1:
                self.autoscale_y_axis(impl_plot)
            else:
                logger.debug(f"process_ipl_axis: setting {ax_idx} axis range to {axis.begin} and {axis.end}")
                self.set_oaw_axis_limits(impl_plot, ax_idx, [axis.begin, axis.end])

        if isinstance(axis, LinearAxis) and axis.is_date:
            self.process_ipl_axis_formatter(impl_plot, axis_item, ax_idx)

        # Set number of ticks and labels
        tick_number = self._pm.get_value(axis, 'tick_number')
        self.process_ipl_axis_ticks(tick_number, axis_item)

    @abstractmethod
    def process_ipl_signal_impl_plot(self, signal: Signal):
        """"""

    @abstractmethod
    def process_ipl_signal_annotations(self, signal: Signal, impl_plot: Any):
        """
        """

    @run_in_one_thread
    def process_ipl_signal(self, signal: Signal):
        """
        Refresh a specific signal. This will repaint the necessary items after the signal
                    data has changed.

        Args:
            signal (Signal): An object derived from abstract iplotlib.core.signal.Signal
        """

        if not isinstance(signal, Signal):
            return

        impl_plot = self.process_ipl_signal_impl_plot(signal)

        # All good, make a data access request
        signal_data = signal.get_data()

        data = self.transform_data(impl_plot, signal_data)

        if hasattr(signal, 'envelope') and signal.envelope:
            if len(data) != 3:
                logger.error(f"Requested to draw envelope for sig({id(signal)}), but it does not have sufficient data"
                             f" arrays (==3). {signal}")
                return
            self.do_impl_envelope_plot(signal, impl_plot, data[0], data[1], data[2])
        else:
            if len(data) < 2:
                logger.error(f"Requested to draw line for sig({id(signal)}), but it does not have sufficient data "
                             f"arrays (<2). {signal}")
                return
            self.do_impl_line_plot(signal, impl_plot, data)

        self.update_axis_labels_with_units(impl_plot, signal)

        # Check for annotations if the marker labels are visible
        self.process_ipl_signal_annotations(signal, impl_plot)

    def update_axis_labels_with_units(self, impl_plot: Any, signal: Signal):
        """
        Get the unit information from the signal object and set the axis labels with those units.
        """

        def group_data_units(impl_plot: Any):
            """
            Function that returns axis label made from signal units"""
            units = []
            ci = self._impl_plot_cache_table.get_cache_item(impl_plot)
            if hasattr(ci, 'signals') and ci.signals:
                for signal_ref in ci.signals:
                    s = signal_ref()
                    try:
                        assert isinstance(s.y_data.unit, str)
                        if len(s.y_data) and len(s.y_data.unit):
                            units.append(s.y_data.unit)
                    except (AttributeError, AssertionError):
                        continue
            units = set(units) if len(set(units)) == 1 else units
            return '[{}]'.format(']['.join(units)) if len(units) else None

        yaxis = self.get_impl_y_axis(impl_plot)
        if hasattr(yaxis, "_label") and not yaxis._label:
            label = group_data_units(impl_plot)
            if label:
                self.set_impl_y_axis_label_text(impl_plot, label)
        xaxis = self.get_impl_x_axis(impl_plot)
        put_label = False
        ci = self._impl_plot_cache_table.get_cache_item(impl_plot)
        if hasattr(ci, 'plot') and ci.plot():
            if hasattr(ci.plot(), 'axes'):
                xax = ci.plot().axes[0]
                if isinstance(xax, LinearAxis):
                    put_label |= (not xax.is_date)

        if put_label and hasattr(signal, 'x_data'):
            if hasattr(signal.x_data, 'unit'):
                label = f"[{signal.x_data.unit or '?'}]"
                if label and not isinstance(ci.plot(), PlotXYWithSlider):
                    self.set_impl_x_axis_label_text(impl_plot, label)
        # label from preferences takes precedence.
        if hasattr(xaxis, "_label") and xaxis._label:
            self.set_impl_x_axis_label_text(impl_plot, xaxis._label)

    @abstractmethod
    def do_impl_line_plot_xy(self, signal: SignalXY, impl_plot: Any, plot: PlotXY, cache_item, x_data, y_data):

        """"""

    @abstractmethod
    def do_impl_line_plot_xy_slider(self, signal: SignalXY, impl_plot: Any, plot: PlotXYWithSlider, cache_item,
                                    x_data, y_data, z_data):
        """"""

    @abstractmethod
    def do_impl_line_plot_contour(self, signal: SignalContour, impl_plot: Any, plot: PlotContour, x_data, y_data,
                                  z_data):
        """"""

    @abstractmethod
    def do_impl_envelope_plot(self, signal: Signal, impl_plot: Any, x_data, y1_data, y2_data):
        """"""

    def do_impl_line_plot(self, signal: Signal, impl_plot: Any, data: List[BufferObject]):
        try:
            cache_item = self._impl_plot_cache_table.get_cache_item(impl_plot)
            plot = cache_item.plot()
        except AttributeError:
            cache_item = None
            plot = None

        plot_lines = None
        if isinstance(signal, SignalXY):
            if isinstance(plot, PlotXYWithSlider):
                plot_lines = self.do_impl_line_plot_xy_slider(signal, impl_plot, plot, cache_item, data[0], data[1],
                                                              data[2])
            else:
                plot_lines = self.do_impl_line_plot_xy(signal, impl_plot, plot, cache_item, data[0], data[1])
        elif isinstance(signal, SignalContour):
            plot_lines = self.do_impl_line_plot_contour(signal, impl_plot, plot, data[0], data[1], data[2])

        self._signal_impl_shape_lut.update({id(signal): plot_lines})

    def update_range_axis(self, range_axis: RangeAxis, ax_idx: int, impl_plot: Any, which='current'):
        """
        If axis is a RangeAxis update its min and max to implementation chart's view limits
        """
        if not isinstance(range_axis, RangeAxis) or impl_plot is None:
            return
        limits = self.get_oaw_axis_limits(impl_plot, ax_idx)
        range_axis.set_limits(*limits, which)
        logger.debug(f"Axis update: impl_plot={id(impl_plot)} range_axis={id(range_axis)} ax_idx={ax_idx} {range_axis}")

    def update_multi_range_axis(self, range_axes: Collection[RangeAxis], ax_idx: int, impl_plot: Any):
        """
        Updates RangeAxis instances begin and end to mpl_axis limits. Works also on stacked axes
        """
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
        """
        Implementation must set the view limits on `ax_idx` axis to the tuple `limits`
        Returns True if the limits were successfully set, False otherwise
        """

    @abstractmethod
    def set_impl_plot_slider_limits(self, plot, start, end):
        """
        This method updates the slider's range and annotations, and highlights the
        selected region if it does not span the full available range. Used during
        Undo/Redo actions to restore previous slider limits.
        """

    @abstractmethod
    def set_focus_plot(self, impl_plot: Any):
        """Sets the focus plot."""

    def undo(self):
        """
        Simply redirect the call to history manager
        """
        self._hm.undo()

    def redo(self):
        """
        Simply redirect the call to history manager
        """
        self._hm.redo()

    def drop_history(self):
        """
        Simply redirect the call to history manager
        """
        self._hm.drop()

    def unstale_cache_items(self):
        """
        Remove all stacle cache items.
        This is called after all the stale plots are updated in refresh_data.
        Call it manually should you want to discard the stale plots.
        """
        self._stale_citems.clear()

    def get_shared_plot_xy_slider(self, plot_with_slider: PlotXYWithSlider):
        """
        Returns a list of PlotXYWithSlider instances that share the same time range with the given PlotXYWithSlider
        """
        shared = []
        limits = self.get_plot_limits(plot_with_slider, 'original')
        base_begin, base_end = limits.axes_ranges[0].begin, limits.axes_ranges[0].end
        for col in self.canvas.plots:
            for plot in col:
                if not isinstance(plot, PlotXYWithSlider) or plot == plot_with_slider:
                    continue
                limits = self.get_plot_limits(plot, 'original')
                begin, end = limits.axes_ranges[0].begin, limits.axes_ranges[0].end

                max_diff = self._pm.get_value(self.canvas, 'max_diff')
                max_diff_ns = max_diff * 1e9 if plot.axes[0].is_date or isinstance(plot, PlotXYWithSlider) else max_diff

                if ((begin, end) == (base_begin, base_end) or (
                        abs(begin - base_begin) <= max_diff_ns and abs(end - base_end) <= max_diff_ns)):
                    shared.append(plot)
        return shared

    def get_shared_plots(self, which='original'):
        """
        Return a list of plots that share the same X-axis range as the focus plot.
        Two plots are considered shared if:
            - Their X-axis range (begin, end) is exactly the same, or
            - The difference in their X-axis range is smaller than a configurable threshold (`max_diff`)
        """
        shared_plots = []

        # Check if it is a PlotXYWithSlider, since in this case shared plots are not returned
        if isinstance(self._focus_plot, PlotXYWithSlider):
            return shared_plots

        # Get original limits of the base plot (focus plot)
        limits = self.get_plot_limits(self._focus_plot, which)
        base_begin, base_end = limits.axes_ranges[0].begin, limits.axes_ranges[0].end

        for col in self.canvas.plots:
            for plot in col:
                if plot == self._focus_plot:
                    continue

                limits = self.get_plot_limits(plot, which)
                begin, end = limits.axes_ranges[0].begin, limits.axes_ranges[0].end

                max_diff = self._pm.get_value(self.canvas, 'max_diff')
                max_diff_ns = max_diff * 1e9 if plot.axes[0].is_date or isinstance(plot, PlotXYWithSlider) else max_diff

                if ((begin, end) == (base_begin, base_end) or (
                        abs(begin - base_begin) <= max_diff_ns and abs(end - base_end) <= max_diff_ns)):
                    shared_plots.append(plot)

        return shared_plots

    def get_all_plot_limits_focus(self, which='current'):
        """
        Return limits of all plots, synchronizing shared plots with the focus plot.
        Shared plots are updated to match the focus plot’s X-axis and signal ranges. This ensures consistency across
        synchronized plots, which is useful for linked zooming or panning behaviors.
        """
        all_limits = []
        if not isinstance(self.canvas, Canvas):
            return all_limits

        shared = self.get_shared_plots()
        base_limits = self.get_plot_limits(self._focus_plot, which)
        axes_limits = base_limits.axes_ranges
        signal_limits = base_limits.signals_ranges

        for col in self.canvas.plots:
            for plot in col:
                plot_lims = self.get_plot_limits(plot, which)
                if not isinstance(plot_lims, IplPlotViewLimits):
                    continue
                if plot in shared:  # The focus plot is not included in 'shared'
                    if not isinstance(plot, PlotXYWithSlider):
                        # Synchronize X-axis limits
                        plot_lims.axes_ranges[0].begin = axes_limits[0].begin
                        plot_lims.axes_ranges[0].end = axes_limits[0].end

                        # Synchronize signal value limits
                        for signal_limit in plot_lims.signals_ranges:
                            signal_limit.begin = signal_limits[-1].begin
                            signal_limit.end = signal_limits[-1].end

                        # Set new limits for each shared plot
                        self.set_plot_limits(plot_lims)
                    else:
                        # In the case of a PlotXYWithSlider, what should be updated are the sliders_ranges
                        slider_min = np.searchsorted(plot.signals[1][0].z_data, axes_limits[0].begin)
                        slider_max = np.searchsorted(plot.signals[1][0].z_data, axes_limits[0].end)

                        # Ensure indices are within the valid range of the signal's time data
                        max_len = len(plot.signals[1][0].z_data) - 1
                        slider_min = max(0, min(slider_min, max_len))
                        slider_max = max(0, min(slider_max, max_len))

                        plot_lims.sliders_ranges[0].begin = slider_min
                        plot_lims.sliders_ranges[0].end = slider_max

                        # Update plot slider limits
                        plot.slider_last_min = slider_min
                        plot.slider_last_max = slider_max

                all_limits.append(plot_lims)
        return all_limits

    def get_all_plot_limits(self, which='current') -> List[IplPlotViewLimits]:
        """
        Return limits of all plots. The `which` argument can be `original` or `current`
        Use this function to construct an :data:`~iplotlib.core.commands.axes_range.IplotAxesRangeCmd` instance
        that you could push onto the history manager.
        """
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

    def get_plot_limits(self, plot: Plot, which='current') -> Optional[IplPlotViewLimits]:
        """
        Return limits for the given plot. The `which` argument can be `original` or `current`
        """
        if not isinstance(self.canvas, Canvas) or not isinstance(plot, Plot):
            return None
        plot_lims = IplPlotViewLimits(plot_ref=weakref.ref(plot))
        for plot_signals in plot.signals.values():
            for sig in plot_signals:
                plot_lims.signals_ranges.append(IplSignalLimits(sig.ts_start, sig.ts_end, weakref.ref(sig)))
        for axes in plot.axes:
            if isinstance(axes, Collection):
                for axis in axes:
                    if not isinstance(axis, RangeAxis):
                        continue
                    begin, end = axis.get_limits(which)
                    plot_lims.axes_ranges.append(IplAxisLimits(begin, end, weakref.ref(axis)))
            elif isinstance(axes, RangeAxis):
                axis = axes  # singular name is easier to read for single axis
                begin, end = axis.get_limits(which)
                plot_lims.axes_ranges.append(IplAxisLimits(begin, end, weakref.ref(axis)))

        # Save slider limits for PlotXYWithSlider
        if isinstance(plot, PlotXYWithSlider):
            plot_lims.sliders_ranges.append(IplSliderLimits(plot.slider_last_min, plot.slider_last_max))

        return plot_lims

    def set_plot_limits(self, limits: IplPlotViewLimits):
        """
        Set limits for the plots.
        :data:`~iplotlib.core.commands.axes_range.IplotAxesRangeCmd` calls this on each plot
        when undoing/redoing an action.
        """
        i = 0
        plot = limits.plot_ref()
        ax_limits = limits.axes_ranges

        # Restore signal-level xrange values
        for signal_limit in limits.signals_ranges:
            signal = signal_limit.signal_ref()
            signal.set_xranges(signal_limit.get_limits())

        for ax_idx, axes in enumerate(plot.axes):
            if isinstance(axes, Collection):
                for axis in axes:
                    if isinstance(axis, RangeAxis):
                        impl_plot = self._axis_impl_plot_lut.get(id(axis))
                        if not self.set_impl_plot_limits(impl_plot, ax_idx,
                                                         (ax_limits[i].begin, ax_limits[i].end)) or isinstance(plot,
                                                                                                               PlotXYWithSlider):
                            axis.set_limits(*ax_limits[i].get_limits())
                        i += 1
            elif isinstance(axes, RangeAxis):
                axis = axes
                impl_plot = self._axis_impl_plot_lut.get(id(axis))
                if not self.set_impl_plot_limits(impl_plot, ax_idx,
                                                 (ax_limits[i].begin, ax_limits[i].end)) or isinstance(plot,
                                                                                                       PlotXYWithSlider):
                    axis.set_limits(*ax_limits[i].get_limits())
                i += 1

        # Restore slider-specific limits, if the plot has one
        if isinstance(plot, PlotXYWithSlider) and self._pm.get_value(self.canvas, 'shared_x_axis'):
            self.set_impl_plot_slider_limits(plot, *limits.sliders_ranges[0].get_limits())

        self.refresh_data()

    @staticmethod
    def create_offset(vals: Union[List, BufferObject]) -> Union[int, np.int64, np.uint64, None]:
        """
        Given a collection of values determine if creating offset is necessary and return it
        Returns None otherwise
        This offset is needed because matplotlib does not allow zooming so deep when the plot ends are too large.
        E.g. if the limits are O(10^15) the n you cannot zoom in where the distance between both is less than 1000.
        """
        if (isinstance(vals, (List, BufferObject)) and len(vals) > 0 and
                isinstance(vals[0], (int, np.int64, np.uint64)) and vals[0] > 10 ** 15):
            return int(vals[0])
        return None

    def get_value(self, impl_plot: Any, ax_idx: int, data_sample):
        """
        Offset-aware get axis value
        """
        return self.transform_value(impl_plot, ax_idx, data_sample)

    @abstractmethod
    def get_impl_x_axis(self, impl_plot: Any):
        """
        Implementations should return the x axis
        """

    @abstractmethod
    def get_impl_y_axis(self, impl_plot: Any):
        """
        Implementations should return the y axis
        """

    def get_impl_axis(self, impl_plot, axis_idx):
        """
        Convenience method that gets implementation axis by index 
        instead of using separate methods `get_impl_x_axis`/`get_impl_y_axis`
        """
        if 0 <= axis_idx <= 1:
            return [self.get_impl_x_axis, self.get_impl_y_axis][axis_idx](impl_plot)
        return None

    @abstractmethod
    def get_impl_x_axis_limits(self, impl_plot: Any):
        """
        Implementations should return the x range
        """

    @abstractmethod
    def get_impl_y_axis_limits(self, impl_plot: Any):
        """
        Implementations should return the y range
        """

    def get_oaw_axis_limits(self, impl_plot: Any, ax_idx: int):
        """
        Offset-aware version of implementation's `get_impl_x_axis_limits`, `get_impl_y_axis_limits`
        The `oaw` in the function name stands for OffsetAWare.
        """
        begin, end = (None, None)
        if ax_idx == 0:
            begin, end = self.get_impl_x_axis_limits(impl_plot)
        elif ax_idx == 1:
            begin, end = self.get_impl_y_axis_limits(impl_plot)
        return self.transform_value(impl_plot, ax_idx, begin), self.transform_value(impl_plot, ax_idx, end)

    @abstractmethod
    def set_impl_x_axis_limits(self, impl_plot: Any, limits: tuple):
        """
        Implementations should set the x range
        """

    @abstractmethod
    def set_impl_y_axis_limits(self, impl_plot: Any, limits: tuple):
        """
        Implementations should set the y range
        """

    def set_oaw_axis_limits(self, impl_plot: Any, ax_idx: int, limits):
        """
        Offset-aware version of implementation's `set_impl_x_axis_limits`, `set_impl_y_axis_limits`
        The `oaw` in the function name stands for OffsetAWare.
        """
        ci = self._impl_plot_cache_table.get_cache_item(impl_plot)
        if ci.offsets[ax_idx] is None:
            ci.offsets[ax_idx] = self.create_offset(limits)

        if ci.offsets[ax_idx] is not None:
            begin = self.transform_value(impl_plot, ax_idx, limits[0], inverse=True)
            end = self.transform_value(impl_plot, ax_idx, limits[1], inverse=True)
            logger.debug(f"\tLimits {begin} to to plot {end} ax_idx: {ax_idx} case 0")
        else:
            begin = limits[0]
            end = limits[1]
            logger.debug(f"\tLimits {begin} to to plot {end} ax_idx: {ax_idx} case 1")
        if ax_idx == 0:
            if begin == end and begin is not None:
                begin = end - 1
            self.set_impl_x_axis_limits(impl_plot, (begin, end))
        elif ax_idx == 1:
            self.set_impl_y_axis_limits(impl_plot, (begin, end))

    @abstractmethod
    def set_impl_x_axis_label_text(self, impl_plot: Any, text: str):
        """
        Implementations should set the x axis label text
        """

    @abstractmethod
    def set_impl_y_axis_label_text(self, impl_plot: Any, text: str):
        """
        Implementations should set the y axis label text
        """

    @abstractmethod
    def transform_value(self, impl_plot: Any, ax_idx: int, value: Any, inverse=False):
        """
        Adds or subtracts axis offset from value trying to preserve type of offset (ex: does not convert to
        float when offset is int)
        """

    def transform_data(self, impl_plot: Any, data):
        """
        This function post processes data if it cannot be plot with matplotlib directly.
        Currently, it transforms data if it is a large integer which can cause overflow in matplotlib
        """
        ret = []
        if isinstance(data, Collection):
            ci = self._impl_plot_cache_table.get_cache_item(impl_plot)
            for i, d in enumerate(data):
                logger.debug(f"\t transform data i={i} d = {d} ")

                offset = None
                if ci:
                    offset = ci.offsets[i]
                    if offset is None and i == 0:
                        offset = self.create_offset(d)
                        ci.offsets[i] = offset

                if ci and offset is not None:
                    logger.debug(f"\tApplying data offsets {offset} to plot {id(impl_plot)} ax_idx: {i}")
                    if isinstance(d, Collection) and not isinstance(d, (str, bytes)):
                        arr = np.asarray(d, dtype=np.int64)
                        ret.append(BufferObject(arr - offset))  # / 10000
                    else:
                        ret.append(np.int64(d) - offset)  # / 10000
                else:
                    ret.append(d)
        return ret
