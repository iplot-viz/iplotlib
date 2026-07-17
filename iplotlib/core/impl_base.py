"""
The BackendParserBase class parses the :data:`~iplotlib.core.canvas.Canvas` object
and translates its properties to implementation specific objects.

It uses a caching mechanism to store references to abstract iplotlib objects 
in the implementation plot object for later retrieval in event callbacks.

See :data:`~iplotlib.core.impl_base.ImplementationPlotCacheItem` and :data:
`~iplotlib.core.impl_base.ImplementationPlotCacheTable`

"""

# Author: Jaswant Sai Panchumarti

from datetime import datetime
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
from iplotlib.core.plot import Plot, PlotXY, PlotXYWithSlider, PlotContour, PlotImage, PlotContourWithSlider
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
        offset = self.get_cache_item(impl_obj).offsets[ax_idx]

        if offset is None:
            return value
        elif offset == 100_000:
            if inverse:
                return value / offset
            else:
                return value * offset
        else:
            if inverse:
                return value - offset
            else:
                return value + offset

    def get_slider_time(self, impl_obj: Any):
        """Return current slider time (ns) if impl_obj belongs to a slider plot, else None."""
        ci = self.get_cache_item(impl_obj)
        if ci is None:
            return None
        iplot = ci.plot()
        if iplot is None or not hasattr(iplot, 'slider') or iplot.slider is None:
            return None
        slider_idx = int(iplot.slider.value() if callable(getattr(iplot.slider, 'value', None)) else iplot.slider.val)
        for sig_ref in ci.signals:
            sig = sig_ref()
            if sig and hasattr(sig, 'time') and sig.time is not None and len(sig.time) > slider_idx:
                return float(sig.time[slider_idx])
        return None


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
        self._impl_plot_ranges_hash = defaultdict(
            lambda: defaultdict(dict))  # type: Dict[Any, int] # key is id(impl_plot)
        self._update = False
        self._restoring_view = False
        self._streaming_impl_plot_lut = defaultdict(lambda: [None, None])

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
                # We are not in the main thread, so the Streaming thread is added to the task queue
                # The call to self._impl_flush_method() triggers the main thread to execute draw_in_main_thread
                # This eventually calls process_work_queue in the correct thread
                self._impl_task_queue.put(partial(func, self, *args, **kwargs))
                self._impl_flush_method()

        return wrapper

    @run_in_one_thread
    def process_work_queue(self):
        # Processes a single pending task from the task queue
        # Since it is decorated with run_in_one_thread, it will never run in the wrong thread
        try:
            work_item = self._impl_task_queue.get_nowait()
            work_item()
        except Empty:
            logger.debug("Nothing to do.")

    @abstractmethod
    def get_impl_data(self, curve):
        pass

    def get_bottom_top(self, x_line, lo, hi):
        xd, yd = self.get_impl_data(x_line)
        if xd is not None and yd is not None:
            y_displayed = yd[((xd >= lo) & (xd <= hi))]
        else:
            y_displayed = []

        # Check if the visible Y data contains valid values
        if len(y_displayed) > 0:
            # Check if there exist NaN values in the y_displayed array
            if np.isnan(y_displayed).any():
                y_displayed = y_displayed[~np.isnan(y_displayed)]
            min_bot = np.min(y_displayed)
            max_top = np.max(y_displayed)
        else:
            min_bot = np.inf
            max_top = -np.inf

        return min_bot, max_top

    @abstractmethod
    def get_impl_lines(self, impl_plot: Any):
        pass

    @abstractmethod
    def autoscale_y_axis(self, impl_plot: Any, padding=0.1):
        """
        This function rescales the y-axis based on the data that is visible given the current limits of the X-axis
        """
        lines, lo, hi = self.get_impl_lines(impl_plot)
        bot, top = np.inf, -np.inf

        for line in lines:
            new_bot, new_top = self.get_bottom_top(line, lo, hi)
            if new_bot < bot:
                bot = new_bot
            if new_top > top:
                top = new_top

        # Apply default Y limits in case of missing or invalid data
        if bot == np.inf and top == -np.inf:
            bot, top = 0, 1

        return bot, top

    @abstractmethod
    def export_image(self, filename: str, **kwargs):
        pass

    def autoscale_all_plots(self):
        """
        Autoscale the Y axis of every PlotXY of the current canvas.

        This is the headless equivalent of the interactive 'Autoscale All' action:
        it reuses the same per-plot :meth:`autoscale_y_axis` logic but without any
        undo/redo bookkeeping. It is meant to be used by the image export path
        (e.g. ``export_image(..., autoscale=True)``) and does not alter the
        behavior of the interactive autoscale in any way.
        """
        if self.canvas is None:
            return
        for column in self.canvas.plots:
            for plot in column:
                if not isinstance(plot, PlotXY):
                    continue
                for impl_plot in self._plot_impl_plot_lut.get(id(plot), []):
                    if impl_plot is None:
                        continue
                    self.autoscale_y_axis(impl_plot)

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
        self._streaming_impl_plot_lut.clear()

    def process_ipl_canvas(self, canvas: Canvas):
        """
        Prepare the implementation canvas.

        :param canvas: A Canvas instance
        :type canvas: Canvas
        """
        if canvas is None:
            self.canvas = canvas
            self.clear()
            return

        logger.debug(f"ipl_canvas 1: {self._pm.get_value(canvas, 'step')}")

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
    def _y_axis_update_callback(self, current_plot: Any):
        """
        Callback that updates the Y axis limits when the axis bounds change in the corresponding plot implementation
        """
        if self._update:
            return
        plot = self._impl_plot_cache_table.get_cache_item(current_plot).plot()

        if self._pm.get_value(self.canvas, 'shared_x_axis'):
            shared_plots = self._get_all_shared_axes(current_plot)
        else:
            shared_plots = self._plot_impl_plot_lut.get(id(plot))  # Stacked plots

        for impl_plot in shared_plots:
            plot = self._impl_plot_cache_table.get_cache_item(impl_plot).plot()
            stacked_plots = self._plot_impl_plot_lut.get(id(plot))

            if self._pm.get_value(self.canvas, 'autoscale'):
                self._update = True
                self.autoscale_y_axis(impl_plot)
            else:
                if impl_plot != current_plot:
                    continue

            # Set Y Axis limits
            y_start, y_end = self.get_oaw_axis_limits(impl_plot, 1)
            pos = stacked_plots.index(impl_plot)
            y_sub_axis = plot.axes[1][pos]
            y_sub_axis.set_limits(y_start, y_end, 'current')

        self._update = False

    @abstractmethod
    def _x_axis_update_callback(self, current_plot: Any):
        """
        Callback that updates the X axis limits when the axis bounds change in the corresponding plot implementation.
        This callback ensures that all plots sharing the time axis are synchronized.
        """
        if self._update:
            return
        self._update = True

        if self._pm.get_value(self.canvas, 'shared_x_axis'):
            shared_plots = self._get_all_shared_axes(current_plot)
        else:
            plot = self._impl_plot_cache_table.get_cache_item(current_plot).plot()
            shared_plots = self._plot_impl_plot_lut.get(id(plot))

        new_start, new_end = self.get_oaw_axis_limits(current_plot, 0)

        for impl_plot in shared_plots:
            plot = self._impl_plot_cache_table.get_cache_item(impl_plot).plot()

            if isinstance(plot, PlotXYWithSlider) and len(shared_plots) > 1:
                self.update_slider_limits(plot, new_start, new_end)
            else:
                # Set X Axis limits
                plot.axes[0].set_limits(new_start, new_end, 'current')

                self.set_oaw_axis_limits(impl_plot, 0, (new_start, new_end))

                if self._impl_plot_cache_table.get_cache_item(impl_plot).plot().axes[0].is_date:
                    self.process_ipl_axis_formatter(impl_plot, self.get_impl_axis(impl_plot, 0), 0)

                signals = self._impl_plot_cache_table.get_cache_item(impl_plot).signals
                for signal_ref in signals:
                    signal = signal_ref()
                    if not isinstance(plot, PlotXYWithSlider):
                        signal.set_limits((new_start, new_end))
                    self.process_ipl_signal(signal)

        self._update = False

    @staticmethod
    def _plot_signal_ts_range(plot):
        """(ts_start, ts_end) of the first numeric-valued signal on ``plot``, or None."""
        if plot is None or not plot.signals:
            return None
        for stack in plot.signals.values():
            for signal in stack:
                if signal is None:
                    continue
                ts_start = getattr(signal, 'ts_start', None)
                ts_end = getattr(signal, 'ts_end', None)
                if isinstance(ts_start, (int, float)) and isinstance(ts_end, (int, float)):
                    return (ts_start, ts_end)
        return None

    def _get_all_shared_axes(self, base_impl_plot: Any) -> List[Any]:
        cache_item = self._impl_plot_cache_table.get_cache_item(base_impl_plot)
        base_plot = cache_item.plot()

        if isinstance(base_plot, PlotXYWithSlider) or base_plot is None:
            return []

        base_ts = self._plot_signal_ts_range(base_plot)
        base_begin, base_end = base_plot.axes[0].get_limits('original')

        shared = list()
        plot_list = self.get_canvas_plots()
        for plot_item in plot_list:
            cache_item = self._impl_plot_cache_table.get_cache_item(plot_item)

            try:
                plot = cache_item.plot()
            except AttributeError:
                continue

            # Slider plots: X axis follows z_data, not signal ts. Keep axis-original check.
            if isinstance(plot, PlotXYWithSlider):
                begin, end = plot.axes[0].get_limits('original')
                slider_values = plot.signals[1][0].z_data
                is_date = bool(min(slider_values) > (1 << 53) and max(slider_values) < (1 << 62))
                max_diff = self._pm.get_value(self.canvas, 'max_diff')
                max_diff_ns = max_diff * 1e9 if is_date else max_diff
                if abs(begin - base_begin) <= max_diff_ns and abs(end - base_end) <= max_diff_ns:
                    shared.append(plot_item)
                continue

            # XY plots: compare requested ts to bypass axis-original drift from
            # partial UDA coverage or data-derived x_expr.
            plot_ts = self._plot_signal_ts_range(plot)
            if base_ts is not None and plot_ts is not None:
                if plot_ts == base_ts:
                    shared.append(plot_item)
            else:
                begin, end = plot.axes[0].get_limits('original')
                is_date = plot.axes[0].is_date
                max_diff = self._pm.get_value(self.canvas, 'max_diff')
                max_diff_ns = max_diff * 1e9 if is_date else max_diff
                if abs(begin - base_begin) <= max_diff_ns and abs(end - base_end) <= max_diff_ns:
                    shared.append(plot_item)

        return shared

    @abstractmethod
    def get_canvas_plots(self):
        pass

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
    def process_ipl_axis_params(self, fc, fs, tick_number, axis: Axis, impl_axis: Any):
        """
        param
        """

    @abstractmethod
    def process_ipl_axis_formatter(self, impl_plot: Any, axis_item: Any, ax_idx: int):
        pass

    def process_ipl_axis(self, axis: LinearAxis, ax_idx: int, plot: Plot, impl_plot: Any):
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

        self.process_ipl_log_axis(axis_item, plot)

        fc = self._pm.get_value(axis, 'font_color')
        fs = self._pm.get_value(axis, 'font_size')

        axis_item._font_color = fc
        axis_item._font_size = fs
        axis_item._label = axis.label

        tick_number = self._pm.get_value(axis, 'tick_number')
        self.process_ipl_axis_params(fc, fs, tick_number, axis, axis_item)

        # Set axis limits
        if ax_idx != 1 or not self.canvas.streaming:  # In case of Streaming, just set X limits at the start
            # Recalculate when the stored range is unusable: either end missing (an
            # X range left open at one end) or degenerate (begin == end, as with
            # single-point workspaces). A None end left as-is would crash offsetting.
            if axis.begin is None or axis.end is None or axis.begin == axis.end:
                self.update_original_axis_limits(axis, impl_plot, ax_idx)
                padding_begin, padding_end = True, True

                # Only Y axis has canvas override
                if ax_idx == 1:
                    canvas_begin = self.canvas.canvas_begin
                    canvas_end = self.canvas.canvas_end

                    begin = canvas_begin if canvas_begin is not None else axis.original_begin
                    end = canvas_end if canvas_end is not None else axis.original_end

                    if canvas_begin is not None:
                        padding_begin = False
                    if canvas_end is not None:
                        padding_end = False

                else:
                    if isinstance(plot, PlotXYWithSlider):
                        begin = axis.begin
                        end = axis.end
                    else:
                        begin = axis.original_begin
                        end = axis.original_end

                # Adjust initial padding for Y axis
                if ax_idx == 1 and not (isinstance(plot, PlotContour) or isinstance(plot, PlotImage)):
                    h = end - begin
                    begin = begin - 0.1 * h if padding_begin else begin
                    end = end + 0.1 * h if padding_end else end
            else:
                begin, end = axis.begin, axis.end

            # Set X,Y axis limits
            self.set_oaw_axis_limits(impl_plot, ax_idx, [begin, end])
            axis.set_limits(begin, end, 'current')

        # Process Nanoseconds Axis
        if axis.is_date:
            self.process_ipl_axis_formatter(impl_plot, axis_item, ax_idx)

    def update_original_axis_limits(self, axis, impl_plot, ax_idx):
        logger.debug(f"process_ipl_axis: setting {ax_idx} axis range to {axis.original_begin} and {axis.original_end}")

        begin, end = +np.inf, -np.inf
        ci = self._impl_plot_cache_table.get_cache_item(impl_plot)
        # X axis with shared_x_axis: aggregate across all non-slider plots so single-point
        # signals in sibling subplots land on one consolidated range.
        if ax_idx == 0 and self._pm.get_value(self.canvas, 'shared_x_axis'):
            signals = []
            for col in self.canvas.plots:
                for p in col:
                    if p is None or isinstance(p, PlotXYWithSlider) or not p.signals:
                        continue
                    for stack in p.signals.values():
                        signals.extend(weakref.ref(s) for s in stack)
        elif ax_idx == 0 and ci and ci.plot() is not None and ci.plot().signals:
            signals = [weakref.ref(s) for stack in ci.plot().signals.values() for s in stack]
        else:
            signals = ci.signals if ci else []

        for signal_ref in signals:
            signal = signal_ref()
            signal.get_data()
            if not isinstance(signal.parent(), PlotImage):
                if isinstance(signal.parent(), PlotXYWithSlider) and ax_idx == 0:
                    data = signal.time  # Original values for slider
                    cur_data = signal.x_data
                    cur_data = cur_data[~np.isnan(cur_data)]
                    x_begin, x_end = min(np.min(cur_data).item(), begin), max(np.max(cur_data).item(), end)
                    axis.set_limits(x_begin, x_end, 'current')
                else:
                    if signal.envelope > 0 and ax_idx == 1:
                        # Envelope case Y axis
                        y_min = signal.data_store[1]
                        y_max = signal.data_store[2]
                        y_min = y_min[~np.isnan(y_min)]
                        y_max = y_max[~np.isnan(y_max)]
                        data = np.array([np.min(y_min).item(), np.max(y_max).item()])
                    else:
                        data = signal.x_data if ax_idx == 0 else signal.y_data
            else:
                data = self.set_image_limits(ax_idx, signal, impl_plot)
                origin = self._pm.get_value(signal.parent(), 'origin')
                if ax_idx == 1 and origin == 'upper':
                    begin = data[-1]
                    end = data[0]
                    break

            if len(data) > 0:
                data = data[~np.isnan(data)]
                begin, end = min(np.min(data).item(), begin), max(np.max(data).item(), end)
            else:
                begin = -0.5
                end = 0.5

        axis.set_limits(begin, end, 'original')

    @abstractmethod
    def set_image_limits(self, ax_idx: int, signal: SignalXY, impl_plot: Any):
        pass

    @abstractmethod
    def process_ipl_signal_impl_plot(self, signal: Signal):
        """"""

    @abstractmethod
    def process_ipl_signal_annotations(self, signal: Signal, impl_plot: Any):
        """
        """

    def _draw_time_signal_data(self, signal: Signal, impl_plot: Any):
        """
        Data for redrawing `signal` while the view is being reset: the draw-time
        snapshot (``restore_minimap_snapshot``), served without any data access.
        Returns None when the snapshot cannot honour the plot (no snapshot yet,
        or slider/contour/image data, which it does not capture).
        """
        if not isinstance(signal, SignalXY):
            return None
        ci = self._impl_plot_cache_table.get_cache_item(impl_plot)
        plot = ci.plot() if ci else None
        if plot is None or isinstance(plot, (PlotXYWithSlider, PlotContour, PlotImage)):
            return None
        restore = getattr(signal, 'restore_minimap_snapshot', None)
        return restore() if restore is not None else None

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

        # impl_plot can be None if signal was removed (e.g. during undo of shift)
        if impl_plot is None:
            return

        if self._restoring_view:
            # View reset: redraw from the draw-time snapshot, never re-request data.
            signal_data = self._draw_time_signal_data(signal, impl_plot)
            if signal_data is None:
                return
        else:
            # All good, make a data access request
            signal_data = signal.get_data()

        # Apply shift offsets if present (persisted in signal metadata)
        # This ensures offset survives any rebuild/refresh cycle
        drag_shift_dx = getattr(signal, '_drag_shift_dx', 0.0)
        drag_shift_dy = getattr(signal, '_drag_shift_dy', 0.0)
        if (drag_shift_dx != 0.0 or drag_shift_dy != 0.0) and len(signal_data) >= 2:
            signal_data = list(signal_data)  # Make mutable copy
            if drag_shift_dx != 0.0 and signal_data[0] is not None:
                signal_data[0] = signal_data[0] + drag_shift_dx
            if drag_shift_dy != 0.0 and signal_data[1] is not None:
                signal_data[1] = signal_data[1] + drag_shift_dy

        data = self.transform_data(impl_plot, signal_data)

        if hasattr(signal, 'envelope') and signal.envelope:
            if len(data) != 4:
                logger.error(f"Requested to draw envelope for sig({id(signal)}), but it does not have sufficient data"
                             f" arrays (==4). {signal}")
                return
            if not isinstance(signal, SignalXY):
                logger.error(f"Skipping envelope plot: only supported for SignalXY, but received {type(signal).__name__}")
                return
            self.do_impl_envelope_plot(signal, impl_plot, data[0], data[1], data[2], data[3])
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

        ci = self._impl_plot_cache_table.get_cache_item(impl_plot)
        plot = ci.plot() if ci else None

        # Y axis
        y_auto = group_data_units(impl_plot)
        if plot and len(plot.axes) > 1:
            stacked_plots = self._plot_impl_plot_lut.get(id(plot), [])
            pos = stacked_plots.index(impl_plot) if impl_plot in stacked_plots else 0
            y_axis = plot.axes[1][pos] if isinstance(plot.axes[1], Collection) else plot.axes[1]
            if y_axis.label == "":
                y_text = ""
            elif y_axis.label:
                y_text = y_axis.label
            else:
                y_text = y_auto or ""
                if y_auto:
                    y_axis._auto_label = y_auto
            self.set_impl_y_axis_label_text(impl_plot, y_text)

        # X axis
        x_auto = None
        if plot and hasattr(plot, 'axes') and len(plot.axes) > 0:
            x_axis = plot.axes[0]
            if isinstance(x_axis, LinearAxis) and not x_axis.is_date:
                if hasattr(signal, 'x_data') and hasattr(signal.x_data, 'unit'):
                    if not (
                            isinstance(ci.plot(), PlotXYWithSlider) or isinstance(ci.plot(), PlotContourWithSlider)):
                        x_auto = f"[{signal.x_data.unit or '? '}]"
            if x_axis.label == "":
                x_text = ""
            elif x_axis.label:
                x_text = x_axis.label
            else:
                x_text = x_auto or ""
                if x_auto:
                    x_axis._auto_label = x_auto
            self.set_impl_x_axis_label_text(impl_plot, x_text)

    @staticmethod
    def _get_visible_data(xd, yd, lo, hi):
        mask = (xd >= lo) & (xd <= hi)
        x_displayed = xd[mask]
        y_displayed = yd[mask]
        return x_displayed, y_displayed

    @staticmethod
    @abstractmethod
    def _update_marker_by_point_count(marker_line: Any, signal_x_data, signal_style: dict):
        pass

    def update_plot_line_streaming(self, signal: SignalXY, impl_plot: Any, plot_lines, x_data, y_data, style):
        """
        Updates the plot data during streaming, distinguishing between the cases when new data arrives and when no
        new data is received.

        The method stores the last X and Y points from the arrays and compares them with the most recent values. If
        the latest X value remains unchanged, it means no new data has arrived. In this case, a constant value is drawn
        to represent the last received Y point.
        """
        last_x = self._streaming_impl_plot_lut[signal.uid][0]
        last_y = self._streaming_impl_plot_lut[signal.uid][1]

        if len(x_data) > 0 and last_x != x_data[-1]:  # New data
            self._streaming_impl_plot_lut[signal.uid] = [x_data[-1], y_data[-1]]
            self.set_line_data(plot_lines[0], x_data, y_data)
            self._update_marker_by_point_count(plot_lines[0], x_data, style)

        elif len(x_data) > 0 and last_x == x_data[-1]:  # No new data
            now = int(datetime.now().timestamp() * 1e9)
            new_x = self.transform_value(impl_plot, 0, now, inverse=True)
            const_x = np.append(x_data, new_x)
            const_y = np.append(y_data, last_y)
            self.set_line_data(plot_lines[0], const_x, const_y)

        return plot_lines

    def do_impl_line_plot_xy(self, signal: SignalXY, impl_plot: Any, plot: PlotXY, cache_item, x_data, y_data):

        plot_lines = self._signal_impl_shape_lut.get(id(signal))  # type: List[Any]
        style = self.get_signal_style(signal)
        draw_fn = impl_plot.plot

        # Review to implement directly in PlotXY class
        if signal.color is None:
            # It means that the color has been reset but must keep the original color
            signal.color = signal.original_color

        # Visible data is adjusted based on extremities, but only for unprocessed signals.
        # Processed signals already use the visible range.
        # Skip this step in case of streaming mode, as x_data and y_data may be empty and lead to errors.

        if not signal.extremities and not self.canvas.streaming:
            x_limits = self.get_impl_x_axis_limits(impl_plot)
            x_data, y_data = self._get_visible_data(x_data, y_data, *x_limits)

        # Flatten single-column 2D y_data so it routes through the 1D path
        if y_data.ndim == 2 and y_data.shape[1] == 1:
            y_data = y_data.ravel()

        if plot_lines is not None:
            # Reflect downsampling in legend
            self.legend_downsampled_signal(signal, impl_plot, plot_lines[0])

            if x_data.ndim == 1 and y_data.ndim == 1:
                # Streaming
                if self.canvas.streaming and len(x_data) > 0:
                    plot_lines = self.update_plot_line_streaming(signal, impl_plot, plot_lines, x_data, y_data, style)
                else:
                    self.set_line_data(plot_lines[0], x_data, y_data)
                    self._update_marker_by_point_count(plot_lines[0], x_data, style)
            elif x_data.ndim == 1 and y_data.ndim == 2:
                for i, line in enumerate(plot_lines):
                    if y_data.shape == (0, 0):  # Case: no data for 2 dim y_data
                        self.set_line_data(line, x_data, y_data)
                    else:
                        self.set_line_data(line, x_data, y_data[:, i])
                    self._update_marker_by_point_count(line, x_data, style)

            if self.canvas.streaming:
                self.do_impl_streaming(impl_plot, plot, cache_item)

            self.visible_status(plot_lines, signal)

        else:
            if x_data.ndim == 1 and y_data.ndim == 1:
                plot_lines = self.create_plot_lines_1D(draw_fn, x_data, y_data, style)
                self._update_marker_by_point_count(plot_lines[0], x_data, style)
            elif x_data.ndim == 1 and y_data.ndim == 2:
                plot_lines = self.create_plot_lines_2D(draw_fn, signal, x_data, y_data, style)

        signal.lines = plot_lines

        return plot_lines

    @abstractmethod
    def visible_status(self, plot_lines, signal):
        pass

    @abstractmethod
    def do_impl_streaming(self, impl_plot: Any, plot: Plot, cache_item):
        pass

    @abstractmethod
    def set_line_data(self, line: Any, x_data, y_data):
        pass

    @abstractmethod
    def create_plot_lines_1D(self, draw_fn, x_data, y_data, style):
        pass

    @abstractmethod
    def create_plot_lines_2D(self, draw_fn, signal, x_data, y_data, style):
        pass

    @abstractmethod
    def get_signal_style(self, signal: SignalXY):
        pass

    @abstractmethod
    def legend_downsampled_signal(self, signal, impl_plot: Any, plot_lines: Any):
        pass

    @abstractmethod
    def get_line_label(self, line: Any):
        """"""

    def set_signal_visible(self, signal: Signal, visible: bool):
        """Set visibility of signal lines."""
        pass

    def remove_signal_lines(self, signal: Signal):
        """Remove signal lines from the plot."""
        pass

    def remove_signal_from_legend(self, impl_plot: Any, signal: Signal):
        """Remove signal from legend."""
        pass

    def add_signal_to_legend(self, impl_plot: Any, signal: Signal):
        """Add signal to legend."""
        pass

    def rebuild_legend(self, impl_plot: Any, plot: Plot):
        """Rebuild legend for the given plot. Default implementation does nothing."""
        pass

    def add_marker_scaled(self, impl_plot: Any, plot: PlotXY, x_coord, y_coord):
        """
        Function that returns the nearest point of the plot to create the corresponding marker.
        As the scale of the axes is very different, a normalization of the data is done to adjust the data to a
        common scale.
        """

        ranges = []
        marker_signal = None
        nearest_point = None
        nearest_line_label = None
        minor_dist = float('inf')

        for ax_idx, ax in enumerate(plot.axes):
            if isinstance(ax, RangeAxis):
                ranges = ax.get_limits()

        # Get the lines that are actually located in the current mpl_axes
        signals = self._impl_plot_cache_table.get_cache_item(impl_plot).signals

        # With the new X axis limits, we obtain the points within that range
        for signal_ref in signals:
            signal = signal_ref()
            x_data = signal.x_data
            for idx_line, line in enumerate(signal.lines):
                idx1 = np.searchsorted(x_data, ranges[0])
                idx2 = np.searchsorted(x_data, ranges[1])

                if isinstance(plot, PlotXYWithSlider):
                    x_zoom = signal.x_data[idx1:idx2]
                    y_data = signal.data_store[1]
                    y_zoom = y_data[self.get_slider_val(plot)][idx1:idx2]
                else:
                    x_zoom = signal.data_store[0][idx1:idx2]
                    y_data = signal.data_store[1]
                    if y_data.ndim == 1:
                        y_zoom = y_data[idx1:idx2]
                    else:  # ndim = 2
                        y_zoom = y_data[idx1:idx2, idx_line]

                # If the number of samples per signal is less than 100 we continue, if not the user shall keep zooming
                if len(x_zoom) > 100:
                    return None, len(x_zoom), None

                # If there are no data points in the zoomed region, skip this signal
                if not len(x_zoom):
                    continue

                # Get the points (x,y) for each signal
                points = list(zip(x_zoom, y_zoom))

                # Normalization of the points
                x_min, x_max = min(x_zoom), max(x_zoom)
                y_min, y_max = min(y_zoom), max(y_zoom)

                x_range = x_max - x_min if x_max != x_min else 1
                y_range = y_max - y_min if y_max != y_min else 1
                scaled_points = [((px - x_min) / x_range, (py - y_min) / y_range) for px, py in points]

                # Normalization of the coordinates where the user clicked
                x_coord_transform = self.transform_value(impl_plot, 0, x_coord)
                scaled_x = (x_coord_transform - x_min) / x_range
                scaled_y = (y_coord - y_min) / y_range

                # Get the nearest point using the Euclidian distance
                distances = [np.sqrt((px - scaled_x) ** 2 + (py - scaled_y) ** 2) for px, py in scaled_points]
                idx_result = np.argmin(distances)

                if distances[idx_result] < minor_dist:
                    minor_dist = distances[idx_result]
                    nearest_point = points[idx_result]
                    marker_signal = signal
                    nearest_line_label = self.get_line_label(line if not isinstance(line, Collection) else line[0])

        return nearest_point, marker_signal, nearest_line_label

    def do_impl_line_plot_image(self, signal: SignalXY, impl_plot: Any, plot: PlotImage, cache_item, data):

        plot_lines = self._signal_impl_shape_lut.get(id(signal))  # type: List[Any]
        # style = self.get_signal_style(signal)
        # draw_fn = impl_plot.plot
        img = None

        if plot_lines is None:
            if data.ndim == 2:
                img = self.create_image(impl_plot, plot, cache_item, data)

        signal.lines = img

        return img

    @abstractmethod
    def create_image(self, impl_plot: Any, plot: PlotImage, cache_item, data):
        pass

    def do_impl_line_plot_xy_slider(self, signal: SignalXY, impl_plot: Any, plot: PlotXYWithSlider, cache_item,
                                    x_data, y_data, z_data):
        plot_lines = self._signal_impl_shape_lut.get(id(signal))  # type: List[Any]
        style = self.get_signal_style(signal)
        draw_fn = impl_plot.plot

        ysub_data = self.get_ysub_data(plot, y_data)

        # Review to implement directly in PlotXY class
        if signal.color is None:
            signal.color = plot.get_next_color()

        if isinstance(plot_lines, list):
            if x_data.ndim == 1 and ysub_data.ndim == 1:
                self.set_line_data(plot_lines[0], x_data, ysub_data)
                # _update_marker_by_point_count(line, x_data, style)
            elif x_data.ndim == 1 and ysub_data.ndim == 2:  # TODO: pendant
                for i, line in enumerate(plot_lines):
                    line[0].set_xdata(x_data)
                    line[0].set_ydata(ysub_data[:, i])
            elif ysub_data.ndim == 0:
                xsub_data = self.get_ysub_data(plot, x_data)
                self.set_line_data(plot_lines[0], [xsub_data], [ysub_data])
                self._update_marker_by_point_count(plot_lines[0], [xsub_data], style)
            # For now, streaming just with Signal XY within a PlotXY
        else:
            if x_data.ndim == 1 and ysub_data.ndim == 1:
                plot_lines = self.create_slider_plot_lines_1D(draw_fn, x_data, ysub_data, style)
            elif x_data.ndim == 1 and ysub_data.ndim == 2:
                plot_lines = self.create_slider_plot_lines_2D(draw_fn, x_data, ysub_data, style)
            elif ysub_data.ndim == 0:
                xsub_data = self.get_ysub_data(plot, x_data)
                plot_lines = self.create_slider_plot_lines_1D(draw_fn, [xsub_data], [ysub_data], style)
                self._update_marker_by_point_count(plot_lines[0], [xsub_data], style)
                logger.warning("PlotXYWithSlider created with a single data point per slice")

        self.slider_visible_status(plot_lines, signal)

        signal.lines = plot_lines

        return plot_lines

    @abstractmethod
    def get_slider_val(self, plot: PlotXYWithSlider):
        pass

    @abstractmethod
    def get_ysub_data(self, plot: PlotXYWithSlider, y_data):
        pass

    @abstractmethod
    def create_slider_plot_lines_1D(self, draw_fn, x_data, y_data, style):
        pass

    @abstractmethod
    def create_slider_plot_lines_2D(self, draw_fn, x_data, y_data, style):
        pass

    @abstractmethod
    def slider_visible_status(self, plot_lines, signal):
        pass

    @abstractmethod
    def do_impl_line_plot_contour(self, signal: SignalContour, impl_plot: Any, plot: PlotContour, x_data, y_data,
                                  z_data):
        """"""

    @abstractmethod
    def do_impl_line_plot_contour_slider(self, signal: SignalContour, impl_plot: Any, plot: PlotContourWithSlider,
                                         x_data, y_data, z_data):
        """"""

    def do_impl_envelope_plot(self, signal: SignalXY, impl_plot: Any, x_data, y1_data, y2_data, y3_data):
        shapes = self._signal_impl_shape_lut.get(id(signal))  # type: List[List[Any]]

        draw_fn = impl_plot.plot
        style = self.get_signal_style(signal)
        style2 = dict(style)
        style2.pop("name", None)

        if shapes is not None:
            # Reflect downsampling in legend
            self.legend_downsampled_signal(signal, impl_plot, shapes[0][0])

            if x_data.ndim == 1 and y1_data.ndim == 1 and y2_data.ndim == 1 and y3_data.ndim == 1:
                self.set_line_data(shapes[0][0], x_data, y1_data)
                self.set_line_data(shapes[0][1], x_data, y2_data)
                self.set_line_data(shapes[0][2], x_data, y3_data)
                self.update_area_envelope_1D(shapes, impl_plot, x_data, y1_data, y2_data, style)
            # TODO elif x_data.ndim == 1 and y1_data.ndim == 2 and y2_data.ndim == 2:
        else:
            if x_data.ndim == 1 and y1_data.ndim == 1 and y2_data.ndim == 1:
                shapes = self.create_area_envelope_1D(draw_fn, impl_plot, signal, x_data, y1_data, y2_data, y3_data,
                                                      style, style2)
                signal.lines = shapes
                self._signal_impl_shape_lut.update({id(signal): shapes})
            # TODO elif x_data.ndim == 1 and y1_data.ndim == 2 and y2_data.ndim == 2:

    @abstractmethod
    def update_area_envelope_1D(self, shapes, impl_plot: Any, x_data, y1_data, y2_data, style):
        pass

    @abstractmethod
    def create_area_envelope_1D(self, draw_fn, impl_plot: Any, signal, x_data, y1_data, y2_data, y3_data, style,
                                style2):
        pass

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
            elif isinstance(plot, PlotImage):
                plot_lines = self.do_impl_line_plot_image(signal, impl_plot, plot, cache_item, data[0])
            else:
                plot_lines = self.do_impl_line_plot_xy(signal, impl_plot, plot, cache_item, data[0], data[1])
        elif isinstance(signal, SignalContour):
            if isinstance(plot, PlotContourWithSlider):
                plot_lines = self.do_impl_line_plot_contour_slider(signal, impl_plot, plot, data[0], data[1], data[2])
            else:
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
    def update_slider_limits(self, plot, begin, end):
        """
        Updates the slider's minimum and maximum values based on Zoom or Draw with shared time.
        Highlight the selected area in the slider.
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

    def get_shared_plot_xy_slider(self, plot_with_slider: PlotXYWithSlider | PlotContourWithSlider):
        """
        Returns a list of PlotXYWithSlider instances that share the same time range with the given PlotXYWithSlider
        """
        shared = []
        base_begin, base_end = plot_with_slider.axes[0].get_limits('original')
        for col in self.canvas.plots:
            for plot in col:
                if not (isinstance(plot, PlotXYWithSlider) or isinstance(plot,
                                                                         PlotContourWithSlider)) or plot == plot_with_slider:
                    continue

                # Check if it is date and the max difference is 1 second
                # Need to differentiate if it is absolute or relative
                if isinstance(plot, PlotXYWithSlider):
                    slider_values = plot.signals[1][0].z_data
                    is_date = bool(min(slider_values) > (1 << 53) and max(slider_values) < (1 << 62))
                elif isinstance(plot, PlotContourWithSlider):
                    slider_values = plot.signals[1][0].time
                    is_date = bool(min(slider_values) > (1 << 53) and max(slider_values) < (1 << 62))
                else:
                    is_date = plot.axes[0].is_date

                begin, end = plot.axes[0].get_limits('original')
                max_diff = self._pm.get_value(self.canvas, 'max_diff')
                max_diff_ns = max_diff * 1e9 if is_date else max_diff

                if abs(begin - base_begin) <= max_diff_ns and abs(end - base_end) <= max_diff_ns:
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

    def get_all_plot_limits(self) -> List[IplPlotViewLimits]:
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
                if self._focus_plot is not None and self._focus_plot != plot:
                    continue
                impl_list = self._plot_impl_plot_lut.get(id(plot))
                if not impl_list:
                    continue
                for impl_plot in impl_list:
                    plot_lims = self.get_plot_limits(impl_plot, True)
                    if not isinstance(plot_lims, IplPlotViewLimits):
                        continue
                    all_limits.append(plot_lims)
        return all_limits

    def get_plot_limits(self, impl_plot: Any, canvas_flag: bool = False) -> Optional[IplPlotViewLimits]:
        """
        Return limits for the given plot. The `which` argument can be `original` or `current`
        """
        plot = self._impl_plot_cache_table.get_cache_item(impl_plot).plot()
        signals = self._impl_plot_cache_table.get_cache_item(impl_plot).signals

        plot_lims = IplPlotViewLimits(plot_ref=weakref.ref(plot))

        # IplSignalLimits
        for plot_signal in signals:
            signal = plot_signal()
            plot_lims.signals_ranges.append(IplSignalLimits(signal.ts_start, signal.ts_end, weakref.ref(signal)))

        # IplAxisLimits
        #  -- X limits --
        x_begin, x_end = self.get_oaw_axis_limits(impl_plot, 0)
        plot_lims.axes_ranges.append(IplAxisLimits(x_begin, x_end))

        # -- Y limits --
        y_oaw_begin, y_oaw_end = self.get_oaw_axis_limits(impl_plot, 1)
        stacked_plots = self._plot_impl_plot_lut.get(id(plot))
        pos = stacked_plots.index(impl_plot)
        y_begin, y_end = plot.axes[1][pos].get_limits('current')

        if canvas_flag:  # Apply preferences case
            # Check Y axis limits at canvas level
            if (y_oaw_begin, y_oaw_end) == (y_begin, y_end):
                begin = self.canvas.canvas_begin if self.canvas.canvas_begin is not None else y_oaw_begin
                end = self.canvas.canvas_end if self.canvas.canvas_end is not None else y_oaw_end
                plot_lims.axes_ranges.append(IplAxisLimits(begin, end))
            else:
                plot_lims.axes_ranges.append(IplAxisLimits(y_begin, y_end))  # Case modify Axis preferences

        else:  # Zoom case
            # Check Y axis limits at canvas level
            if (y_oaw_begin, y_oaw_end) == (y_begin, y_end):
                plot_lims.axes_ranges.append(IplAxisLimits(y_oaw_begin, y_oaw_end))
            else:
                plot_lims.axes_ranges.append(IplAxisLimits(y_begin, y_end))  # Case modify Axis preferences

        # IplSliderLimits
        if isinstance(plot, PlotXYWithSlider) or isinstance(plot, PlotContourWithSlider):
            plot_lims.sliders_ranges.append(IplSliderLimits(plot.slider_last_min, plot.slider_last_max))

        return plot_lims

    def set_plot_limits(self, limits: IplPlotViewLimits):
        """
        Set limits for the plots.
        :data:`~iplotlib.core.commands.axes_range.IplotAxesRangeCmd` calls this on each plot
        when undoing/redoing an action.
        """
        plot = limits.plot_ref()
        ax_limits = limits.axes_ranges
        signal_limits = limits.signals_ranges
        impl_plot = None

        # Restore signal-level xrange values
        for signal_limit in signal_limits:
            signal = signal_limit.signal_ref()
            signal.set_xranges(signal_limit.get_limits())
            if impl_plot is None:
                impl_plot = self._signal_impl_plot_lut.get(signal.uid)

        # Set X limits
        self.set_oaw_axis_limits(impl_plot, 0, (ax_limits[0].begin, ax_limits[0].end))
        # isinstance(plot, PlotXYWithSlider): TODO: test with Slider

        # Set Y limits
        self.set_oaw_axis_limits(impl_plot, 1, (ax_limits[1].begin, ax_limits[1].end))
        # isinstance(plot, PlotXYWithSlider): TODO: test with Slider

        # Restore slider-specific limits, if the plot has one
        if isinstance(plot, PlotXYWithSlider) and self._pm.get_value(self.canvas, 'shared_x_axis'):
            self.set_impl_plot_slider_limits(plot, *limits.sliders_ranges[0].get_limits())

    def _draw_time_y_limits(self, plot, begin, end):
        """
        Return the Y range as Draw would show it: the original extent plus the 10%
        margin, unless a canvas-level Y min/max override is set (then it wins, with
        no margin). Contour and image plots get no margin. Mirrors the Y handling in
        :meth:`process_ipl_axis`.
        """
        if begin is None or end is None or isinstance(plot, (PlotContour, PlotImage)):
            return begin, end
        canvas_begin = self.canvas.canvas_begin
        canvas_end = self.canvas.canvas_end
        height = end - begin
        lo = canvas_begin if canvas_begin is not None else begin - 0.1 * height
        hi = canvas_end if canvas_end is not None else end + 0.1 * height
        return lo, hi

    def set_plot_limits_to_original(self, impl_plot: Any):
        """
        Restore a single plot to the ranges captured at draw time (the ``original``
        limits), leaving every other plot untouched. The X range is the exact window
        requested at draw time; the Y range gets the same margin Draw applies.

        Reuses the view-limit plumbing of undo/redo, and the redraws it triggers are
        served from the draw-time snapshots (:meth:`_draw_time_signal_data`), so no
        data-access request is issued.
        """
        target = self.get_plot_limits(impl_plot)
        if not isinstance(target, IplPlotViewLimits):
            return
        plot = target.plot_ref()
        if plot is None:
            return

        x_begin, x_end = plot.axes[0].get_limits('original')
        stacked_plots = self._plot_impl_plot_lut.get(id(plot))
        y_begin, y_end = plot.axes[1][stacked_plots.index(impl_plot)].get_limits('original')
        y_begin, y_end = self._draw_time_y_limits(plot, y_begin, y_end)

        target.axes_ranges[0].set_limits(x_begin, x_end)
        target.axes_ranges[1].set_limits(y_begin, y_end)
        # Signals inherit the plot's X range; realign them to the draw-time window
        # so their cached samples are reused on redraw.
        for signal_range in target.signals_ranges:
            signal_range.set_limits(x_begin, x_end)

        self._restoring_view = True
        try:
            self.set_plot_limits(target)
        finally:
            self._restoring_view = False

    def reset_all_plots_to_original(self):
        """
        Restore every visible plot to its draw-time ranges. Plots hidden by focus
        mode are skipped, mirroring the iteration in :meth:`get_all_plot_limits`.
        """
        if not isinstance(self.canvas, Canvas):
            return
        for col in self.canvas.plots:
            for plot in col:
                if plot is None:
                    continue
                if self._focus_plot is not None and self._focus_plot != plot:
                    continue
                impl_list = self._plot_impl_plot_lut.get(id(plot))
                if not impl_list:
                    continue
                for impl_plot in impl_list:
                    self.set_plot_limits_to_original(impl_plot)

    @staticmethod
    def create_offset(vals: Union[List, BufferObject]) -> Union[int, np.int64, np.uint64, None]:
        """
        Given a collection of values determine if creating offset is necessary and return it
        Returns None otherwise
        This offset is needed because matplotlib does not allow zooming so deep when the plot ends are too large.
        E.g. if the limits are O(10^15) the n you cannot zoom in where the distance between both is less than 1000.
        """
        begin, end = vals
        if begin < 10 ** 15:
            offset = 0
        else:
            # Always use an INTEGER midpoint reference, in nanosecond units.
            #
            # The previous design used offset == 100_000 (i.e. 100 us per axis
            # unit) for windows wider than ~1e14 ns. That capped the usable
            # resolution at ~400 ns regardless of how far you zoomed, because a
            # float64 axis coordinate around abs/1e5 (~1.8e13) has a ULP of
            # ~0.004 units. Zooming below that collapsed the view to zero width:
            # pan had nothing to translate, and the date locator produced a
            # single tick (so labels degenerated to the full timestamp instead
            # of the trailing digits).
            #
            # An integer midpoint keeps the axis in ns units and keeps
            # transform_value/transform_data in int64, so coordinates retain
            # sub-ns resolution for spans up to ~a week (about 2 ns at year
            # scale) -- enough to zoom, pan and label at nanosecond precision.
            offset = int((begin + end) // 2)

        return offset

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

    def axis_uses_offset(self, impl_plot: Any, ax_idx: int) -> bool:
        """
        An offset may only be applied to an axis whose formatter knows how to add it back,
        which is the date axis handled by `process_ipl_axis_formatter`. On any other axis the
        subtraction would reach the view unanswered and the values would read as ~0, so a
        signal that merely carries large numbers (e.g. nanosecond timestamps as its samples)
        must be left untouched.
        """
        if ax_idx != 0:
            return False
        ci = self._impl_plot_cache_table.get_cache_item(impl_plot)
        plot = ci.plot() if ci is not None else None
        return bool(plot is not None and plot.axes and plot.axes[0].is_date)

    def set_oaw_axis_limits(self, impl_plot: Any, ax_idx: int, limits):
        """
        Offset-aware version of implementation's `set_impl_x_axis_limits`, `set_impl_y_axis_limits`
        The `oaw` in the function name stands for OffsetAWare.
        """
        ci = self._impl_plot_cache_table.get_cache_item(impl_plot)
        ci.offsets[ax_idx] = self.create_offset(limits) if self.axis_uses_offset(impl_plot, ax_idx) else 0

        begin = self.transform_value(impl_plot, ax_idx, limits[0], inverse=True)
        end = self.transform_value(impl_plot, ax_idx, limits[1], inverse=True)
        logger.debug(f"\tLimits {begin} to to plot {end} ax_idx: {ax_idx}")

        if ax_idx == 0:
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
        ci = self._impl_plot_cache_table.get_cache_item(impl_plot)

        for ax_idx, d in enumerate(data):
            logger.debug(f"\t transform data ax_idx={ax_idx} d = {d} ")
            offset = ci.offsets[ax_idx]
            if offset == 0 or offset is None:
                ret.append(d)
            else:
                arr = np.asarray(d, dtype=np.int64)
                if offset == 100_000:
                    ret.append(BufferObject(arr / offset))
                else:
                    ret.append(BufferObject(arr - offset))
        return ret
