# Changelog:
#   Jan 2023:   -Added support for legend position and layout [Alberto Luengo]

from contextlib import ExitStack
from typing import Any, Callable, Collection, List

import numpy as np
from matplotlib.axes import Axes as MPLAxes
from matplotlib.axis import Tick
from matplotlib.axis import Axis as MPLAxis
from matplotlib.backend_bases import FigureCanvasBase
from matplotlib.figure import Figure
from matplotlib.gridspec import GridSpecFromSubplotSpec, SubplotSpec
from matplotlib.lines import Line2D
from matplotlib.text import Annotation, Text
from matplotlib.widgets import MultiCursor
from matplotlib.ticker import MaxNLocator
from pandas.plotting import register_matplotlib_converters

import iplotLogging.setupLogger as sl
from iplotProcessing.core import BufferObject
from iplotlib.core import (Axis,
                           LinearAxis,
                           RangeAxis,
                           Canvas,
                           BackendParserBase,
                           Plot,
                           Signal)
from iplotlib.core.impl_base import ImplementationPlotCacheTable
from iplotlib.impl.matplotlib.dateFormatter import NanosecondDateFormatter

logger = sl.get_logger(__name__)
STEP_MAP = {"linear": "default", "mid": "steps-mid", "post": "steps-post", "default": "steps-pre",
            "pre": "steps-pre", "steps-mid": "steps-mid", "steps-post": "steps-post", "steps-pre": "steps-pre"}

class MatplotlibParser(BackendParserBase):

    def __init__(self,
                 canvas: Canvas = None,
                 tight_layout: bool = True,
                 focus_plot=None,
                 focus_plot_stack_key=None,
                 impl_flush_method: Callable = None) -> None:
        """Initialize underlying matplotlib classes.
        """
        super().__init__(canvas=canvas, focus_plot=focus_plot, focus_plot_stack_key=focus_plot_stack_key, impl_flush_method=impl_flush_method)

        self.map_legend_to_ax = {}
        self.legend_size = 8
        self._cursors = []

        register_matplotlib_converters()
        self.figure = Figure()
        self._impl_plot_ranges_hash = dict()

        if tight_layout:
            self.enable_tight_layout()
        else:
            self.disable_tight_layout()

    def export_image(self, filename: str, **kwargs):
        super().export_image(filename, **kwargs)
        dpi = kwargs.get("dpi") or 300
        width = kwargs.get("width") or 18.5
        height = kwargs.get("height") or 10.5

        self.figure.set_size_inches(width/dpi, height/dpi)
        self.process_ipl_canvas(kwargs.get('canvas'))
        self.figure.savefig(filename)

    def do_mpl_line_plot(self, signal: Signal, mpl_axes: MPLAxes, x_data, y_data):
        lines = self._signal_impl_shape_lut.get(id(signal))  # type: List[List[Line2D]]
        try:
            cache_item = self._impl_plot_cache_table.get_cache_item(mpl_axes)
            plot = cache_item.plot()
        except AttributeError:
            plot = None

        if signal.color is None:
            signal.color = plot.get_next_color()

        style = self.get_signal_style(signal, plot)

        if isinstance(lines, list):
            if x_data.ndim == 1 and y_data.ndim == 1:
                line = lines[0][0]  # type: Line2D
                line.set_xdata(x_data)
                line.set_ydata(y_data)
            elif x_data.ndim == 1 and y_data.ndim == 2:
                for i, line in enumerate(lines):
                    line[0].set_xdata(x_data)
                    line[0].set_ydata(y_data[:, i])
            if self.canvas.streaming:
                mpl_axes.set_ylim(min(y_data) - 0.01, max(y_data) + 0.01)
                ax_window = mpl_axes.get_xlim()[1] - mpl_axes.get_xlim()[0]
                mpl_axes.set_xlim(max(x_data) - ax_window, max(x_data))
            self.figure.canvas.draw_idle()
            # Not necessary, the lines has already all the style
            # for line in lines:
            #     for k, v in style.items():
            #         setter = getattr(line[0], f"set_{k}")
            #         if v is None and k != "drawstyle":
            #             continue
            #         setter(v)
        else:
            params = dict(**style)
            draw_fn = mpl_axes.plot
            if x_data.ndim == 1 and y_data.ndim == 1:
                lines = [draw_fn(x_data, y_data, **params)]
            elif x_data.ndim == 1 and y_data.ndim == 2:
                lines = draw_fn(x_data, y_data, **params)
                lines = [[line] for line in lines]

            self._signal_impl_shape_lut.update({id(signal): lines})

    def do_mpl_envelope_plot(self, signal: Signal, mpl_axes: MPLAxes, x_data, y1_data, y2_data):
        shapes = self._signal_impl_shape_lut.get(id(signal))  # type: List[List[Line2D]]
        try:
            cache_item = self._impl_plot_cache_table.get_cache_item(mpl_axes)
            plot = cache_item.plot()
        except AttributeError:
            plot = None
        style = self.get_signal_style(signal, plot)

        if shapes is not None:
            if x_data.ndim == 1 and y1_data.ndim == 1 and y2_data.ndim == 1:
                shapes[0][0].set_xdata(x_data)
                shapes[0][0].set_ydata(y1_data)
                shapes[0][1].set_xdata(x_data)
                shapes[0][1].set_ydata(y2_data)
                shapes[0][2].remove()
                shapes[0][2] = mpl_axes.fill_between(x_data, y1_data, y2_data,
                                                     alpha=0.3,
                                                     color=shapes[0][0].get_color(),
                                                     step=STEP_MAP[style['drawstyle']].replace('steps-', ''))
            self.figure.canvas.draw_idle()

            # TODO elif x_data.ndim == 1 and y1_data.ndim == 2 and y2_data.ndim == 2:
        else:
            params = dict(**style)
            draw_fn = mpl_axes.plot
            # if step is not None and step != 'None':
            #   params.update({'where': step})
            #  draw_fn = mpl_axes.step

            if x_data.ndim == 1 and y1_data.ndim == 1 and y2_data.ndim == 1:
                line_1 = draw_fn(x_data, y1_data, **params)
                params2 = params.copy()
                signal.color = line_1[0].get_color()
                params2.update(color=signal.color, label='')
                line_2 = draw_fn(x_data, y2_data, **params2)
                area = mpl_axes.fill_between(x_data, y1_data, y2_data,
                                             alpha=0.3,
                                             color=params2['color'],
                                             step=STEP_MAP[style['drawstyle']].replace('steps-', ''))

                self._signal_impl_shape_lut.update({id(signal): [line_1 + line_2 + [area]]})
            # TODO elif x_data.ndim == 1 and y1_data.ndim == 2 and y2_data.ndim == 2:

    def clear(self):
        super().clear()
        self.figure.clear()

    def set_impl_plot_limits(self, impl_plot: Any, ax_idx: int, limits: tuple) -> bool:
        if not isinstance(impl_plot, MPLAxes):
            return False
        self.set_oaw_axis_limits(impl_plot, ax_idx, limits)
        return True

    def _get_all_shared_axes(self, base_mpl_axes: MPLAxes):
        if not isinstance(self.canvas, Canvas):
            return []

        cache_item = self._impl_plot_cache_table.get_cache_item(base_mpl_axes)
        if not hasattr(cache_item, 'plot'):
            return
        base_plot = cache_item.plot()
        if not isinstance(base_plot, Plot):
            return
        shared = list()
        base_limits = self.get_plot_limits(base_plot, which='original')
        base_begin, base_end = base_limits.axes_ranges[0].begin, base_limits.axes_ranges[0].end

        if (base_begin, base_end) != (None, None) or (base_begin, base_end) == (None, None):
            for axes in self.figure.axes:
                cache_item = self._impl_plot_cache_table.get_cache_item(axes)
                if not hasattr(cache_item, 'plot'):
                    continue
                plot = cache_item.plot()
                if not isinstance(plot, Plot):
                    continue
                limits = self.get_plot_limits(plot, which='original')
                begin, end = limits.axes_ranges[0].begin, limits.axes_ranges[0].end
                if (begin, end) == (base_begin, base_end):
                    shared.append(axes)
        return shared

    def process_ipl_canvas(self, canvas: Canvas):
        """This method analyzes the iplotlib canvas data structure and maps it
        onto an internal matplotlib.figure.Figure instance.

        """
        if canvas is not None:
            logger.debug(f"ipl_canvas 1: {canvas.step}")
        super().process_ipl_canvas(canvas)
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
            self._layout = self.figure.add_gridspec(canvas.rows, canvas.cols)
        else:
            self.canvas.focus_plot = self._focus_plot
            self._layout = self.figure.add_gridspec(1, 1)

        # 3. Fill the canvas with plots.
        stop_drawing = False
        for i, col in enumerate(canvas.plots):

            for j, plot in enumerate(col):

                if self._focus_plot is not None:
                    if self._focus_plot == plot:
                        logger.debug(f"Focusing on plot: {plot}")
                        self.process_ipl_plot(plot, 0, 0)
                        stop_drawing = True
                        break
                else:
                    self.process_ipl_plot(plot, i, j)

            if stop_drawing:
                break

        # Update the previous number of ticks at Canvas level
        self.canvas.prev_tick_number = self.canvas.tick_number

        # Update the previous background color at Canvas level
        self.canvas.prev_background_color = self.canvas.background_color

        # 4. Update the title at the top of canvas.
        if canvas.title is not None:
            if not canvas.font_size:
                canvas.font_size = None
            self.figure.suptitle(
                canvas.title, size=canvas.font_size, color=self.canvas.font_color or 'black')

    def process_ipl_plot(self, plot: Plot, column: int, row: int):
        logger.debug(f"process_ipl_plot AA: {self.canvas.step}")
        super().process_ipl_plot(plot, column, row)
        if not isinstance(plot, Plot):
            return

        grid_item = self._layout[row: row + plot.row_span,
                             column: column + plot.col_span]  # type: SubplotSpec

        if not self.canvas.full_mode_all_stack and self._focus_plot_stack_key is not None:
            stack_sz = 1
        else:
            stack_sz = len(plot.signals.keys())

        # Create a vertical layout with `stack_sz` rows and 1 column inside grid_item
        subgrid_item = grid_item.subgridspec(
            stack_sz, 1, hspace=0)  # type: GridSpecFromSubplotSpec

        mpl_axes_prev = None
        for stack_id, key in enumerate(sorted(plot.signals.keys())):
            is_stack_plot_focused = self._focus_plot_stack_key == key

            if self.canvas.full_mode_all_stack or self._focus_plot_stack_key is None or is_stack_plot_focused:
                signals = plot.signals.get(key) or list()

                if not self.canvas.full_mode_all_stack and self._focus_plot_stack_key is not None:
                    row_id = 0
                else:
                    row_id = stack_id

                mpl_axes = self.figure.add_subplot(
                    subgrid_item[row_id, 0], sharex=mpl_axes_prev)
                mpl_axes_prev = mpl_axes
                self._plot_impl_plot_lut[id(plot)].append(mpl_axes)
                # Keep references to iplotlib instances for ease of access in callbacks.
                self._impl_plot_cache_table.register(mpl_axes, self.canvas, plot, key, signals)
                mpl_axes.set_xmargin(0)
                mpl_axes.set_autoscalex_on(True)
                mpl_axes.set_autoscaley_on(True)

                # Set the plot title
                if plot.title is not None and stack_id == 0:
                    fc = self._pm.get_value(
                        'font_color', self.canvas, plot) or 'black'
                    fs = self._pm.get_value('font_size', self.canvas, plot)
                    if not fs:
                        fs = None
                    mpl_axes.set_title(plot.title, color=fc, size=fs)

                # Set the background color
                if self.canvas.background_color != self.canvas.prev_background_color:
                    mpl_axes.set_facecolor(self.canvas.background_color)
                    # Refresh background color for each plot
                    plot.background_color = self.canvas.background_color
                elif plot.background_color is None:
                    mpl_axes.set_facecolor(self.canvas.background_color)
                    plot.background_color = self.canvas.background_color
                elif plot.background_color != self.canvas.background_color:
                    mpl_axes.set_facecolor(plot.background_color)
                else:
                    mpl_axes.set_facecolor(self.canvas.background_color)

                # If this is a stacked plot the X axis should be visible only at the bottom
                # plot of the stack except it is focused
                # Hides an axis in a way that grid remains visible,
                # By default in matplotlib the grid is treated as part of the axis
                visible = ((stack_id + 1 == len(plot.signals.values())) or
                           (is_stack_plot_focused and not self.canvas.full_mode_all_stack))
                for e in mpl_axes.get_xaxis().get_children():
                    if isinstance(e, Tick):
                        e.tick1line.set_visible(visible)
                        # e.tick2line.set_visible(visible)
                        e.label1.set_visible(visible)
                        # e.label2.set_visible(visible)
                    else:
                        e.set_visible(visible)

                # Show the grid if enabled
                show_grid = self._pm.get_value('grid', self.canvas, plot)
                mpl_axes.grid(show_grid)

                # Update properties of the plot axes
                for ax_idx in range(len(plot.axes)):
                    if isinstance(plot.axes[ax_idx], Collection):
                        axis = plot.axes[ax_idx][stack_id]
                        self.process_ipl_axis(axis, ax_idx, plot, mpl_axes)
                    else:
                        axis = plot.axes[ax_idx]
                        self.process_ipl_axis(axis, ax_idx, plot, mpl_axes)

                for signal in signals:
                    self._signal_impl_plot_lut.update({id(signal): mpl_axes})
                    self.process_ipl_signal(signal)

                # Show the plot legend if enabled
                show_legend = self._pm.get_value('legend', self.canvas, plot)
                if show_legend:
                    plot_leg_position = self._pm.get_value('legend_position', self.canvas, plot)
                    canvas_leg_position = self._pm.get_value('legend_position', self.canvas)
                    plot_leg_layout = self._pm.get_value('legend_layout', self.canvas, plot)
                    canvas_leg_layout = self._pm.get_value('legend_layout', self.canvas)

                    plot_leg_position = canvas_leg_position if plot_leg_position == 'same as canvas' \
                        else plot_leg_position
                    plot_leg_layout = canvas_leg_layout if plot_leg_layout == 'same as canvas' \
                        else plot_leg_layout

                    ncols = 1 if plot_leg_layout == 'vertical' else len(signals)

                    legend_props = dict(size=self.legend_size)
                    leg = mpl_axes.legend(prop=legend_props, loc=plot_leg_position, ncol=ncols)
                    if self.figure.get_tight_layout():
                        leg.set_in_layout(False)
                    for legend_line, ax_line in zip(leg.get_lines(), mpl_axes.get_lines()):
                        legend_line.set_picker(3)  # Enable picking on the legend line.
                        self.map_legend_to_ax[legend_line] = ax_line



        # Observe the axis limit change events
        if not self.canvas.streaming:
            for axes in mpl_axes.get_shared_x_axes().get_siblings(mpl_axes):
                axes.callbacks.connect(
                    'xlim_changed', self._axis_update_callback)
                axes.callbacks.connect(
                    'ylim_changed', self._axis_update_callback)

    def _axis_update_callback(self, mpl_axes):

        affected_axes = mpl_axes.get_shared_x_axes().get_siblings(mpl_axes)

        if self.canvas.shared_x_axis:
            other_axes = self._get_all_shared_axes(mpl_axes)
            for other_axis in other_axes:
                cur_x_limits =self.get_oaw_axis_limits(mpl_axes, 0)
                other_x_limits =self.get_oaw_axis_limits(other_axis, 0)
                if cur_x_limits[0] != other_x_limits[0] or cur_x_limits[1] != other_x_limits[1]:
                    self.set_oaw_axis_limits(other_axis, 0, cur_x_limits)

        for a in affected_axes:
            ranges_hash = hash((*a.get_xlim(), *a.get_ylim()))
            current_hash = self._impl_plot_ranges_hash.get(id(a))

            if current_hash is not None and (ranges_hash == current_hash):
                continue

            self._impl_plot_ranges_hash[id(a)] = ranges_hash
            ranges = []

            ci = self._impl_plot_cache_table.get_cache_item(a)
            if not hasattr(ci, 'plot'):
                continue
            if not isinstance(ci.plot(), Plot):
                continue

            for ax_idx, ax in enumerate(ci.plot().axes):
                if isinstance(ax, Collection):
                    ranges.append(self.update_multi_range_axis(ax, ax_idx, a))
                elif isinstance(ax, RangeAxis):
                    self.update_range_axis(ax, ax_idx, a)
                    ranges.append([ax.begin, ax.end])

            if not hasattr(ci, 'signals'):
                continue
            if not ci.signals:
                continue

            for signal_ref in ci.signals:
                signal = signal_ref()
                if hasattr(signal, "set_xranges"):
                    signal.set_xranges([ranges[0][0], ranges[0][1]])
                    logger.debug(f"callback update {ranges[0][0]} axis range to {ranges[0][1]}")
            if ci not in self._stale_citems:
                self._stale_citems.append(ci)

    def process_ipl_axis(self, axis: Axis, ax_idx, plot: Plot, impl_plot: MPLAxes):
        super().process_ipl_axis(axis, ax_idx, plot, impl_plot)
        mpl_axis = self.get_impl_axis(
            impl_plot, ax_idx)  # type: MPLAxis
        self._axis_impl_plot_lut.update({id(axis): impl_plot})

        if isinstance(axis, Axis):
            fc = self._pm.get_value(
                'font_color', self.canvas, plot, axis) or 'black'
            fs = self._pm.get_value('font_size', self.canvas, plot, axis)

            mpl_axis._font_color = fc
            mpl_axis._font_size = fs
            mpl_axis._label = axis.label

            label_props = dict(color=fc)
            # Set ticks on the top and right axis
            if self.canvas.ticks_position:
                tick_props = dict(color=fc, labelcolor=fc, tick1On=True, tick2On=True, direction='in')
            else:
                tick_props = dict(color=fc, labelcolor=fc, tick1On=True, tick2On=False)

            if fs is not None and fs > 0:
                label_props.update({'fontsize': fs})
                tick_props.update({'labelsize': fs})
            if axis.label is not None:
                mpl_axis.set_label_text(axis.label, **label_props)

            mpl_axis.set_tick_params(**tick_props)

        if isinstance(axis, RangeAxis) and axis.begin is not None and axis.end is not None and (axis.begin or axis.end):
            logger.debug(
                f"process_ipl_axis: setting {ax_idx} axis range to {axis.begin} and {axis.end}")
            self.set_oaw_axis_limits(impl_plot, ax_idx, [axis.begin, axis.end])

        if isinstance(axis, LinearAxis):
            if axis.is_date:
                ci = self._impl_plot_cache_table.get_cache_item(impl_plot)
                mpl_axis.set_major_formatter(
                    NanosecondDateFormatter(ax_idx, offset_lut=ci.offsets, round=self.canvas.round_hour))

        # Configurate number of ticks and labels
        if self.canvas.tick_number != self.canvas.prev_tick_number:
            mpl_axis.set_major_locator(MaxNLocator(self.canvas.tick_number))
            # Refresh tick number for each plot
            axis.tick_number = self.canvas.tick_number
        elif axis.tick_number != self.canvas.tick_number:
            mpl_axis.set_major_locator(MaxNLocator(axis.tick_number))
        else:
            mpl_axis.set_major_locator(MaxNLocator(self.canvas.tick_number))

    @BackendParserBase.run_in_one_thread
    def process_ipl_signal(self, signal: Signal):
        """Refresh a specific signal. This will repaint the necessary items after the signal
            data has changed.

        Args:
            signal (Signal): An object derived from abstract iplotlib.core.signal.Signal
        """

        if not isinstance(signal, Signal):
            return

        mpl_axes = self._signal_impl_plot_lut.get(id(signal))  # type: MPLAxes
        if not isinstance(mpl_axes, MPLAxes):
            logger.error(
                f"MPLAxes not found for signal {signal}. Unexpected error. signal_id: {id(signal)}")
            return

        # All good, make a data access request.
        # logger.debug(f"\tprocessipsignal before ts_start {signal.ts_start} ts_end {signal.ts_end} status: {signal.status_info.result} ")
        signal_data = signal.get_data()

        data = self.transform_data(mpl_axes, signal_data)

        if hasattr(signal, 'envelope') and signal.envelope:
            if len(data) != 3:
                logger.error(
                    f"Requested to draw envelope for sig({id(signal)}), but it does not have sufficient data arrays (==3). {signal}")
                return
            self.do_mpl_envelope_plot(
                signal, mpl_axes, data[0], data[1], data[2])
        else:
            if len(data) < 2:
                logger.error(
                    f"Requested to draw line for sig({id(signal)}), but it does not have sufficient data arrays (<2). {signal}")
                return
            self.do_mpl_line_plot(signal, mpl_axes, data[0], data[1])

        self.update_axis_labels_with_units(mpl_axes, signal)

    def enable_tight_layout(self):
        self.figure.set_tight_layout(True)

    def disable_tight_layout(self):
        self.figure.set_tight_layout(False)

    def set_focus_plot(self, mpl_axes: MPLAxes):

        def get_x_axis_range(plot):
            if plot is not None and plot.axes is not None and len(plot.axes) > 0 and isinstance(plot.axes[0], RangeAxis):
                return plot.axes[0].begin, plot.axes[0].end

        def set_x_axis_range(plot, begin, end):
            if plot is not None and plot.axes is not None and len(plot.axes) > 0 and isinstance(plot.axes[0], RangeAxis):
                plot.axes[0].begin = begin
                plot.axes[0].end = end

        if isinstance(mpl_axes, MPLAxes):
            ci = self._impl_plot_cache_table.get_cache_item(mpl_axes)
            plot = ci.plot()
            stack_key = ci.stack_key
        else:
            plot = None
            stack_key = None

        logger.debug(f"Focusing on plot: {id(plot)}, stack_key: {stack_key}")

        if self._focus_plot is not None and plot is None:
            if self.canvas.shared_x_axis and len(self._focus_plot.axes) > 0 and isinstance(self._focus_plot.axes[0], RangeAxis):
                begin, end = get_x_axis_range(self._focus_plot)

                for columns in self.canvas.plots:
                    for plot_temp in columns:
                        if plot_temp != self._focus_plot:
                            logger.debug(
                                f"Setting range on plot {id(plot_temp)} focused= {id(self._focus_plot)} begin={begin}")
                            if plot_temp.axes[0].original_begin == self._focus_plot.axes[0].original_begin and \
                                    plot_temp.axes[0].original_end == self._focus_plot.axes[0].original_end:
                                set_x_axis_range(plot_temp, begin, end)

        self._focus_plot = plot
        self._focus_plot_stack_key = stack_key

    @BackendParserBase.run_in_one_thread
    def activate_cursor(self):

        if self.canvas.crosshair_per_plot:
            plots = {}
            for ax in self.figure.axes:
                ci = self._impl_plot_cache_table.get(ax)
                if hasattr(ci, 'plot') and ci.plot():
                    plot = ci.plot()
                    if not plots.get(id(plot)):
                        plots[id(plot)] = [ax]
                    else:
                        plots[id(plot)].append(ax)
            axes = list(plots.values())
        else:
            axes = [self.figure.axes]

        for axes_group in axes:
            if not axes_group:
                continue

            self._cursors.append(
                MultiCursor2(self.figure.canvas, axes_group,
                             x_label=self.canvas.enable_Xlabel_crosshair,
                             y_label=self.canvas.enable_Ylabel_crosshair,
                             val_label=self.canvas.enable_ValLabel_crosshair,
                             color=self.canvas.crosshair_color, lw=self.canvas.crosshair_line_width,
                             horizOn=False or self.canvas.crosshair_horizontal,
                             vertOn=self.canvas.crosshair_vertical, useblit=True,
                             cache_table=self._impl_plot_cache_table))

    @BackendParserBase.run_in_one_thread
    def deactivate_cursor(self):
        for cursor in self._cursors:
            cursor.remove()
        self._cursors.clear()

    def get_signal_style(self, signal: Signal, plot: Plot = None):
        style = dict()

        if signal.label:
            style['label'] = signal.label
        if hasattr(signal, "color"):
            style['color'] = signal.color

        style['linewidth'] = self._pm.get_value('line_size', self.canvas, plot, signal=signal) or 1
        style['linestyle'] = (self._pm.get_value('line_style', self.canvas, plot, signal=signal) or "Solid").lower()
        style['marker'] = self._pm.get_value('marker', self.canvas, plot, signal=signal)
        style['markersize'] = self._pm.get_value('marker_size', self.canvas, plot, signal=signal) or 0
        step =  self._pm.get_value('step', self.canvas, plot, signal=signal)
        if step is None:
            step = 'linear'
        style["drawstyle"] = STEP_MAP[step]

        return style

    def _redraw_in_frame_with_grid(self, a):
        """A copy of Axes.redraw_in_frame that fixes the problem of not drawing the grid since grid is treated as a part of the axes
        This function tries to hide all axis elements besides the grid itself before drawing"""
        with ExitStack() as stack:
            hide_elements = []
            for axis in [a.get_xaxis(), a.get_yaxis()]:
                hide_elements += [e for e in axis.get_children()
                                  if not (isinstance(e, Tick))]
                hide_elements += [a for e in axis.get_children() if isinstance(e, Tick)
                                  for a in e.get_children() if isinstance(a, Text)]

            for artist in [a.title, a._right_title, *hide_elements]:
                stack.callback(artist.set_visible, artist.get_visible())
                artist.set_visible(False)

            a.draw(a.figure._cachedRenderer)

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

    def get_impl_x_axis(self, impl_plot: Any):
        if isinstance(impl_plot, MPLAxes):
            return impl_plot.get_xaxis()
        else:
            return None

    def get_impl_y_axis(self, impl_plot: Any):
        if isinstance(impl_plot, MPLAxes):
            return impl_plot.get_yaxis()
        else:
            return None

    def get_impl_x_axis_limits(self, impl_plot: Any):
        if isinstance(impl_plot, MPLAxes):
            return impl_plot.get_xlim()
        else:
            return None

    def get_impl_y_axis_limits(self, impl_plot: Any):
        if isinstance(impl_plot, MPLAxes):
            return impl_plot.get_ylim()
        else:
            return None

    def get_oaw_axis_limits(self, impl_plot: Any, ax_idx: int):
        """Offset-aware version of implementation's get_x_limit, get_y_limit"""
        begin, end = (None, None)
        if 0 <= ax_idx <= 1:
            begin, end = [self.get_impl_x_axis_limits, self.get_impl_y_axis_limits][ax_idx](impl_plot)
        return self.transform_value(impl_plot, ax_idx, begin), self.transform_value(impl_plot, ax_idx, end)

    def set_impl_x_axis_limits(self, impl_plot: Any, limits: tuple):
        if isinstance(impl_plot, MPLAxes):
            impl_plot.set_xlim(limits)

    def set_impl_y_axis_limits(self, impl_plot: Any, limits: tuple):
        if isinstance(impl_plot, MPLAxes):
            impl_plot.set_ylim(limits)
        else:
            return None

    def set_oaw_axis_limits(self, impl_plot: Any, ax_idx: int, limits):
        ci = self._impl_plot_cache_table.get_cache_item(impl_plot)
        case=0
        if hasattr(ci, 'offsets') and ci.offsets[ax_idx] is None:
            new_offset = self.create_offset(limits)
            if new_offset is not None:
                ci.offsets[ax_idx] = new_offset

        if hasattr(ci, 'offsets') and ci.offsets[ax_idx] is not None:
            begin = self.transform_value(
                impl_plot, ax_idx, limits[0], inverse=True)
            end = self.transform_value(
                impl_plot, ax_idx, limits[1], inverse=True)
        else:
            begin = limits[0]
            end = limits[1]
            case=1
        logger.debug(
                        f"\tLimits {begin} to to plot {end} ax_idx: {case}")
        if ax_idx == 0:
            if begin == end and begin is not None:
                begin = end-1
            return self.set_impl_x_axis_limits(impl_plot, (begin, end))
        elif ax_idx == 1:
            return self.set_impl_y_axis_limits(impl_plot, (begin, end))
        else:
            return None

    def set_impl_x_axis_label_text(self, impl_plot: Any, text: str):
        """Implementations should set the x axis label text"""
        self.get_impl_x_axis(impl_plot).set_label_text(text)

    def set_impl_y_axis_label_text(self, impl_plot: Any, text: str):
        """Implementations should set the y axis label text"""
        self.get_impl_y_axis(impl_plot).set_label_text(text)

    def transform_value(self, impl_plot: Any, ax_idx: int, value: Any, inverse=False):
        """Adds or subtracts axis offset from value trying to preserve type of offset (ex: does not convert to
        float when offset is int)"""
        return self._impl_plot_cache_table.transform_value(impl_plot, ax_idx, value, inverse=inverse)

    def transform_data(self, impl_plot: Any, data):
        """This function post processes data if it cannot be plot with matplotlib directly.
        Currently it transforms data if it is a large integer which can cause overflow in matplotlib"""
        ret = []
        if isinstance(data, Collection):
            for i, d in enumerate(data):
                logger.debug(f"\t transform data i={i} d = {d} ")
                ci = self._impl_plot_cache_table.get_cache_item(impl_plot)
                if hasattr(ci, 'offsets') and ci.offsets[i] is None:
                    new_offset = self.create_offset(d)
                    if new_offset is not None:
                        ci.offsets[i] = d[0]

                if hasattr(ci, 'offsets') and ci.offsets[i] is not None:
                    logger.debug(
                        f"\tApplying data offsets {ci.offsets[i]} to to plot {id(impl_plot)} ax_idx: {i}")
                    if isinstance(d, Collection):
                        ret.append(BufferObject([e - ci.offsets[i] for e in d]))
                    else:
                        ret.append(d - ci.offsets[i])
                else:
                    ret.append(d)
        return ret


def get_data_range(data, axis_idx):
    """Returns first and last value from data[axis_idx] or None"""
    if data is not None and len(data) > axis_idx and len(data[axis_idx] > 0):
        return (data[axis_idx][0], data[axis_idx][-1])
    return None


class MultiCursor2(MultiCursor):

    def __init__(self, canvas: FigureCanvasBase,
                 axes: MPLAxes,
                 x_label: bool = True,
                 y_label: bool = True,
                 val_label: bool = True,
                 useblit: bool = True,
                 horizOn=False,
                 vertOn=True,
                 val_tolerance: float = 0.05,
                 text_color: str = "white",
                 font_size: int = 8,
                 cache_table: ImplementationPlotCacheTable = None,
                 **lineprops):

        super().__init__(canvas, axes, useblit, horizOn, vertOn, **lineprops)
        self.canvas = canvas
        self.axes = axes
        self.horizOn = horizOn
        self.vertOn = vertOn
        self.x_label = x_label
        self.y_label = y_label
        self.value_label = val_label
        self.text_color = text_color
        self.font_size = font_size
        self._cache_table = cache_table
        # Tolerance for showing label with value on signal in %
        self.val_tolerance = val_tolerance

        xmin, xmax = axes[-1].get_xlim()
        ymin, ymax = axes[-1].get_ylim()
        xmid = 0.5 * (xmin + xmax)
        ymid = 0.5 * (ymin + ymax)

        self.visible = True
        self.useblit = useblit and self.canvas.supports_blit
        self.background = None
        self.needclear = False

        if self.useblit:
            lineprops['animated'] = True

        self.x_arrows = []
        self.y_arrows = []
        self.value_annotations = []
        self.vlines = []

        if vertOn:
            for ax in axes:
                ymin, ymax = ax.get_ybound()
                line = Line2D([xmid, xmid], [ymin, ymax], **lineprops)
                ax.add_artist(line)
                self.vlines.append(line)

        self.hlines = []
        if horizOn:
            for ax in axes:
                xmin, xmax = ax.get_xbound()
                line = Line2D([xmin, xmax], [ymid, ymid], **lineprops)
                ax.add_artist(line)
                self.hlines.append(line)

        axis_arrow_bbox_props = dict(
            boxstyle="round", pad=0.1, fill=True, color=lineprops["color"])
        axis_arrow_props = dict(annotation_clip=False, clip_on=False, bbox=axis_arrow_bbox_props,
                                animated=self.useblit, color=self.text_color, fontsize=self.font_size)

        value_arrow_bbox_props = dict(
            boxstyle="round", pad=0.1, fill=True, color="green")
        value_arrow_props = dict(annotation_clip=False, clip_on=False, bbox=value_arrow_bbox_props,
                                 animated=self.useblit, color=self.text_color, fontsize=self.font_size)
        # value_arrow_props = dict(annotation_clip=False, animated=self.useblit, color=self.text_color, fontsize=self.font_size)

        if self.x_label:
            for ax in axes:
                xmin, xmax = ax.get_xbound()
                ymin, ymax = ax.get_ybound()
                x_arrow = Annotation("", (xmin + (xmax - xmin) / 2, ymin),
                                     verticalalignment="top", horizontalalignment="center", **axis_arrow_props)
                ax.add_artist(x_arrow)
                self.x_arrows.append(x_arrow)

        if self.y_label:
            for ax in axes:
                ymin, ymax = ax.get_ybound()
                xmin, xmax = ax.get_xbound()
                y_arrow = Annotation("", (xmin, ymin + (ymax - ymin) / 2),
                                     verticalalignment="center", horizontalalignment="right", **axis_arrow_props)
                ax.add_artist(y_arrow)
                self.y_arrows.append(y_arrow)

        if self.value_label:
            for ax in axes:
                ci = self._cache_table.get_cache_item(ax)
                if hasattr(ci, "signals") and ci.signals is not None:
                    for signal in ci.signals:
                        xmin, xmax = ax.get_xbound()
                        ymin, ymax = ax.get_ybound()
                        value_annotation = Annotation("", xy=(xmin + (xmax - xmin) / 2, ymin + (ymax - ymin) / 2), xycoords="data",  # xytext=(-200, 0),
                                                      verticalalignment="top", horizontalalignment="left", **value_arrow_props)
                        value_annotation.set_visible(False)
                        value_annotation._ipl_signal = signal
                        ax.add_artist(value_annotation)
                        self.value_annotations.append(value_annotation)

        # Needs to be done for blitting to work. As it saves current background
        self.clear(None)
        self.connect()

    def clear(self, event):
        super().clear(event)
        # In matplolib 3.6, for the MultiCursor object type,
        # the way of storing certain information such as background is changed.
        if hasattr(self, "_canvas_infos"):
            self.background = self._canvas_infos[self.canvas]["background"]
        # self.background = None
        for arrow in self.x_arrows + self.y_arrows:
            arrow.set_visible(False)

        for annotation in self.value_annotations:
            annotation.set_visible(False)

    def remove(self):
        for arrow in self.x_arrows + self.y_arrows:
            arrow.set_visible(False)

        for annotation in self.value_annotations:
            annotation.set_visible(False)

        for line in self.vlines + self.hlines:
            line.set_visible(False)

        self._update()
        self.disconnect()

    def onmove(self, event):

        if self.ignore(event):
            return
        if event.inaxes is None:
            return
        if not self.canvas.widgetlock.available(self):
            return
        self.needclear = True
        if not self.visible:
            return
        if self.vertOn:
            for line in self.vlines:
                line.set_xdata((event.xdata, event.xdata))
                line.set_visible(self.visible)

        if self.horizOn:
            for line in self.hlines:
                line.set_ydata((event.ydata, event.ydata))
                line.set_visible(self.visible)

        if self.x_label:
            for arrow, ax in zip(self.x_arrows, self.axes):
                xmin, xmax = ax.get_xbound()
                if xmin < event.xdata < xmax and ax.get_xaxis().get_visible():
                    arrow.set_position((event.xdata, arrow.get_position()[1]))
                    arrow.set_text(ax.format_xdata(event.xdata))
                    arrow.set_visible(self.visible)
                else:
                    arrow.set_visible(False)

        if self.y_label:
            for arrow, ax in zip(self.y_arrows, self.axes):
                ymin, ymax = ax.get_ybound()
                if ymin < event.ydata < ymax and ax.get_yaxis().get_visible():
                    arrow.set_position((arrow.get_position()[0], event.ydata))
                    arrow.set_text(ax.format_ydata(event.ydata))
                    arrow.set_visible(self.visible)
                else:
                    arrow.set_visible(False)

        if self.value_label:
            for annotation in self.value_annotations:
                if hasattr(annotation, "_ipl_signal"):
                    annotation.set_visible(self.visible)
                    signal = annotation._ipl_signal()
                    if signal is not None:
                        ax = annotation.axes

                        xvalue = self._cache_table.transform_value(
                            ax, 0, event.xdata)
                        values = signal.pick(xvalue)
                        logger.debug(F"Found {values} for xvalue: {xvalue}")
                        if values is not None:
                            dx = abs(xvalue - values[0])
                            xmin, xmax = ax.get_xbound()
                            if dx < (xmax - xmin) * self.val_tolerance:
                                pos_x = self._cache_table.transform_value(
                                    ax, 0, values[0], True)
                                pos_y = self._cache_table.transform_value(
                                    ax, 1, values[1], True)
                                annotation.set_position((pos_x, pos_y))
                                annotation.set_text(ax.format_ydata(values[1]))
                            else:
                                annotation.set_visible(False)

                        else:
                            annotation.set_visible(False)
                else:
                    annotation.set_visible(False)

        self._update()

    def _update(self):
        if self.useblit:
            if self.background is not None:
                self.canvas.restore_region(self.background)

            if self.vertOn:
                for ax, line in zip(self.axes, self.vlines):
                    ax.draw_artist(line)

            if self.horizOn:
                for ax, line in zip(self.axes, self.hlines):
                    ax.draw_artist(line)

            if self.x_label:
                for ax, arrow in zip(self.axes, self.x_arrows):
                    ax.draw_artist(arrow)

            if self.y_label:
                for ax, arrow in zip(self.axes, self.y_arrows):
                    ax.draw_artist(arrow)

            if self.value_label:
                for annotation in self.value_annotations:
                    annotation.axes.draw_artist(annotation)
            self.canvas.blit()
        else:
            self.canvas.draw_idle()
