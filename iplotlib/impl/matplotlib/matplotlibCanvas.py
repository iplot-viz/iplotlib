# Changelog:
#   Jan 2023:   -Added support for legend position and layout [Alberto Luengo]

from typing import Any, Callable, Collection, List
import pandas
import numpy as np
from matplotlib.axes import Axes as MPLAxes
from matplotlib.axis import Tick, YAxis
from matplotlib.axis import Axis as MPLAxis
from matplotlib.contour import QuadContourSet
from matplotlib.figure import Figure
from matplotlib.gridspec import GridSpecFromSubplotSpec, SubplotSpec
from matplotlib.lines import Line2D
from matplotlib.ticker import MaxNLocator, LogLocator
from matplotlib.widgets import Slider
import matplotlib.pyplot as plt
from pandas.plotting import register_matplotlib_converters

from iplotLogging import setupLogger
from iplotProcessing.core import BufferObject
from iplotlib.core import (Axis,
                           LinearAxis,
                           RangeAxis,
                           Canvas,
                           BackendParserBase,
                           Plot,
                           PlotXY,
                           PlotContour,
                           PlotXYWithSlider,
                           Signal,
                           SignalXY,
                           SignalContour)
from iplotlib.impl.matplotlib.dateFormatter import NanosecondDateFormatter
from iplotlib.impl.matplotlib.iplotMultiCursor import IplotMultiCursor

logger = setupLogger.get_logger(__name__)
STEP_MAP = {"linear": "default", "mid": "steps-mid", "post": "steps-post", "pre": "steps-pre",
            "default": None, "steps-mid": "mid", "steps-post": "post", "steps-pre": "pre"}


class MatplotlibParser(BackendParserBase):
    def __init__(self,
                 canvas: Canvas = None,
                 tight_layout: bool = True,
                 focus_plot=None,
                 focus_plot_stack_key=None,
                 impl_flush_method: Callable = None) -> None:
        """Initialize underlying matplotlib classes.
        """
        super().__init__(canvas=canvas, focus_plot=focus_plot, focus_plot_stack_key=focus_plot_stack_key,
                         impl_flush_method=impl_flush_method)

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

        self.figure.set_size_inches(width / dpi, height / dpi)
        self.process_ipl_canvas(kwargs.get('canvas'))
        self.figure.savefig(filename)

    def do_mpl_line_plot(self, signal: Signal, mpl_axes: MPLAxes, data: List[BufferObject]):
        try:
            cache_item = self._impl_plot_cache_table.get_cache_item(mpl_axes)
            plot = cache_item.plot()
        except AttributeError:
            cache_item = None
            plot = None

        plot_lines = None
        if isinstance(signal, SignalXY):
            if isinstance(plot, PlotXYWithSlider):
                plot_lines = self.do_mpl_line_plot_xy_slider(signal, mpl_axes, plot, cache_item, data[0], data[1],
                                                             data[2])
            else:
                plot_lines = self.do_mpl_line_plot_xy(signal, mpl_axes, plot, cache_item, data[0], data[1])
        elif isinstance(signal, SignalContour):
            plot_lines = self.do_mpl_line_plot_contour(signal, mpl_axes, plot, data[0], data[1], data[2])

        self._signal_impl_shape_lut.update({id(signal): plot_lines})

    def do_mpl_line_plot_xy(self, signal: SignalXY, mpl_axes: MPLAxes, plot: PlotXY, cache_item, x_data, y_data):
        plot_lines = self._signal_impl_shape_lut.get(id(signal))  # type: List[List[Line2D]]

        # Review to implement directly in PlotXY class
        if signal.color is None:
            # It means that the color has been reset but must keep the original color
            signal.color = signal.original_color

        if isinstance(plot_lines, list):
            if x_data.ndim == 1 and y_data.ndim == 1:
                line = plot_lines[0][0]
                line.set_xdata(x_data)
                line.set_ydata(y_data)
            elif x_data.ndim == 1 and y_data.ndim == 2:
                for i, line in enumerate(plot_lines):
                    line[0].set_xdata(x_data)
                    line[0].set_ydata(y_data[:, i])

            # Put this out in a method only for streaming
            if self.canvas.streaming:
                ax_window = mpl_axes.get_xlim()[1] - mpl_axes.get_xlim()[0]
                all_y_data = []
                for signal in plot.signals[cache_item.stack_key]:
                    if signal.lines[0][0].get_visible() and len(signal.x_data) > 0:
                        max_x_data = signal.x_data.max()[0]
                        for x_temp, y_temp in zip(signal.x_data, signal.y_data):
                            if max_x_data - ax_window <= x_temp <= max_x_data:
                                all_y_data.append(y_temp)
                if all_y_data:
                    diff = (max(all_y_data) - min(all_y_data)) / 15
                    mpl_axes.set_ylim(min(all_y_data) - diff, max(all_y_data) + diff)
                mpl_axes.set_xlim(max(x_data) - ax_window, max(x_data))
            self.figure.canvas.draw_idle()
            # Preserve visible status for lines
            for new, old in zip(plot_lines, signal.lines):
                for n, o in zip(new, old):
                    n.set_visible(o.get_visible())
        else:
            style = self.get_signal_style(signal)
            params = dict(**style)
            draw_fn = mpl_axes.plot
            if x_data.ndim == 1 and y_data.ndim == 1:
                plot_lines = [draw_fn(x_data, y_data, **params)]
            elif x_data.ndim == 1 and y_data.ndim == 2:
                lines = draw_fn(x_data, y_data, **params)
                plot_lines = [[line] for line in lines]
                for i, line in enumerate(plot_lines):
                    line[0].set_label(f"{signal.label}[{i}]")

        signal.lines = plot_lines

        return plot_lines

    def do_mpl_line_plot_xy_slider(self, signal: SignalXY, mpl_axes: MPLAxes, plot: PlotXYWithSlider, cache_item,
                                   x_data, y_data, z_data):
        plot_lines = self._signal_impl_shape_lut.get(id(signal))  # type: List[List[Line2D]]

        plot.slider.valtext.set_text(pandas.Timestamp(z_data[plot.slider.val]))
        ysub_data = y_data[plot.slider.val]

        # Review to implement directly in PlotXY class
        if signal.color is None:
            signal.color = plot.get_next_color()

        if isinstance(plot_lines, list):
            if x_data.ndim == 1 and ysub_data.ndim == 1:
                line = plot_lines[0][0]
                line.set_xdata(x_data)
                line.set_ydata(ysub_data)
            elif x_data.ndim == 1 and ysub_data.ndim == 2:
                for i, line in enumerate(plot_lines):
                    line[0].set_xdata(x_data)
                    line[0].set_ydata(ysub_data[:, i])

            # Put this out in a method only for streaming
            if self.canvas.streaming:
                ax_window = mpl_axes.get_xlim()[1] - mpl_axes.get_xlim()[0]
                all_y_data = []
                for signal in plot.signals[cache_item.stack_key]:
                    if signal.lines[0][0].get_visible() and len(signal.x_data) > 0:
                        max_x_data = signal.x_data.max()[0]
                        for x_temp, y_temp in zip(signal.x_data, signal.y_data):
                            if max_x_data - ax_window <= x_temp <= max_x_data:
                                all_y_data.append(y_temp)
                if all_y_data:
                    diff = (max(all_y_data) - min(all_y_data)) / 15
                    mpl_axes.set_ylim(min(all_y_data) - diff, max(all_y_data) + diff)
                mpl_axes.set_xlim(max(x_data) - ax_window, max(x_data))
            self.figure.canvas.draw_idle()
        else:
            style = self.get_signal_style(signal)
            params = dict(**style)
            draw_fn = mpl_axes.plot
            if x_data.ndim == 1 and ysub_data.ndim == 1:
                plot_lines = [draw_fn(x_data, ysub_data, **params)]
            elif x_data.ndim == 1 and ysub_data.ndim == 2:
                lines = draw_fn(x_data, ysub_data, **params)
                plot_lines = [[line] for line in lines]
                for i, line in enumerate(plot_lines):
                    line[0].set_label(f"{signal.label}[{i}]")

        for new, old in zip(plot_lines, signal.lines):
            for n, o in zip(new, old):
                n.set_visible(o.get_visible())
            signal.lines = plot_lines

        return plot_lines

    def do_mpl_line_plot_contour(self, signal: SignalContour, mpl_axes: MPLAxes, plot: PlotContour, x_data, y_data,
                                 z_data):
        plot_lines = self._signal_impl_shape_lut.get(id(signal))  # type: QuadContourSet
        contour_filled = self._pm.get_value(plot, 'contour_filled')
        legend_format = self._pm.get_value(plot, "legend_format")
        equivalent_units = self._pm.get_value(plot, "equivalent_units")
        contour_levels = self._pm.get_value(signal, 'contour_levels')
        color_map = self._pm.get_value(signal, 'color_map')

        if isinstance(plot_lines, QuadContourSet):
            for tp in plot_lines.collections:
                tp.remove()
            if contour_filled:
                draw_fn = mpl_axes.contourf
            else:
                draw_fn = mpl_axes.contour
            if x_data.ndim == y_data.ndim == z_data.ndim == 2:
                plot_lines = draw_fn(x_data, y_data, z_data, levels=contour_levels, cmap=color_map)
                if legend_format == 'in_lines':
                    if not contour_filled:
                        plt.clabel(plot_lines, inline=1, fontsize=10)
            if equivalent_units:
                mpl_axes.set_aspect('equal', adjustable='box')
            self.figure.canvas.draw_idle()
        else:
            if contour_filled:
                draw_fn = mpl_axes.contourf
            else:
                draw_fn = mpl_axes.contour
            if x_data.ndim == y_data.ndim == z_data.ndim == 2:
                plot_lines = draw_fn(x_data, y_data, z_data, levels=contour_levels, cmap=color_map)
                if legend_format == 'color_bar':
                    color_bar = self.figure.colorbar(plot_lines, ax=mpl_axes, location='right')
                    color_bar.set_label(z_data.unit, size=self.legend_size)
                else:
                    if not contour_filled:
                        plt.clabel(plot_lines, inline=1, fontsize=10)
                # 2 Legend in line for multiple signal contour in one plot contour
                # plt.clabel(plot_lines, inline=True)
                # self.proxies = [Line2D([], [], color=c) for c in ['viridis']]
            if equivalent_units:
                mpl_axes.set_aspect('equal', adjustable='box')

        return plot_lines

    def do_mpl_envelope_plot(self, signal: Signal, mpl_axes: MPLAxes, x_data, y1_data, y2_data):
        shapes = self._signal_impl_shape_lut.get(id(signal))  # type: List[List[Line2D]]
        try:
            cache_item = self._impl_plot_cache_table.get_cache_item(mpl_axes)
            plot = cache_item.plot()
        except AttributeError:
            plot = None

        style = dict()
        if isinstance(signal, SignalXY):
            style = self.get_signal_style(signal)

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
                                                     step=STEP_MAP[style['drawstyle']])
                shapes[0][2].set_visible(shapes[0][0].get_visible())

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
                                             step=STEP_MAP[style['drawstyle']])
                lines = [line_1 + line_2 + [area]]
                for new, old in zip(lines, signal.lines):
                    for n, o in zip(new, old):
                        n.set_visible(o.get_visible())
                signal.lines = lines
                self._signal_impl_shape_lut.update({id(signal): lines})
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
                # Check if it is date and the max difference is 1 second
                max_diff_ns = self.canvas.max_diff * 1e9
                if ((begin, end) == (base_begin, base_end) or
                        ((5e17 < begin < 1e19) and abs(begin - base_begin) <= max_diff_ns and
                         abs(end - base_end) <= max_diff_ns)):
                    shared.append(axes)
        return shared

    def process_ipl_canvas(self, canvas: Canvas):
        """This method analyzes the iplotlib canvas data structure and maps it
        onto an internal matplotlib.figure.Figure instance.

        """
        if canvas is not None:
            logger.debug(f"ipl_canvas 1: {self._pm.get_value(canvas, 'step')}")
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

        # 4. Update the title at the top of canvas.
        if canvas.title is not None:
            if not self._pm.get_value(self.canvas, 'font_size'):
                canvas.font_size = None
            self.figure.suptitle(canvas.title, size=self._pm.get_value(self.canvas, 'font_size'),
                                 color=self._pm.get_value(self.canvas, 'font_color') or 'black')

    def process_ipl_plot_xy(self):
        pass

    def process_ipl_plot_contour(self):
        pass

    def process_ipl_plot(self, plot: Plot, column: int, row: int):
        logger.debug(f"process_ipl_plot AA: {self._pm.get_value(self.canvas, 'step')}")
        super().process_ipl_plot(plot, column, row)
        if not isinstance(plot, Plot):
            return

        grid_item = self._layout[row: row + plot.row_span, column: column + plot.col_span]  # type: SubplotSpec

        if not self.canvas.full_mode_all_stack and self._focus_plot_stack_key is not None:
            stack_sz = 1
            heights = [0.03, 1.0]
        else:
            stack_sz = len(plot.signals.keys())
            heights = [0.03 * self.canvas.rows] + [1.0] * stack_sz

        if isinstance(plot, PlotXYWithSlider):
            plot_with_slider: PlotXYWithSlider = plot
            # Create a vertical layout with `stack_sz` rows and 1 column inside grid_item
            subgrid_item = grid_item.subgridspec(stack_sz + 1, 1, hspace=0, height_ratios=heights)
            sub_subgrid_item = subgrid_item[0, 0].subgridspec(1, 2, hspace=0, width_ratios=[0.9, 0.15])
            # Add Slider
            slider_ax = self.figure.add_subplot(sub_subgrid_item[0, 0])

            def update_slider(val):
                for c_row in plot.signals.values():
                    for c_signal in c_row:
                        self.process_ipl_signal(c_signal)
                plot_with_slider.slider.valtext.set_text(pandas.Timestamp(plot_with_slider.signals[1][0].z_data[val]))

            plot_with_slider.slider = Slider(slider_ax, '', 0, plot_with_slider.signals[1][0].y_data.shape[0] - 1,
                                             valinit=0, valstep=1)
            plot_with_slider.slider.on_changed(update_slider)
            add_slider = 1
        else:
            subgrid_item = grid_item.subgridspec(stack_sz, 1, hspace=0)  # type: GridSpecFromSubplotSpec
            add_slider = 0

        mpl_axes = None
        mpl_axes_prev = None
        for stack_id, key in enumerate(sorted(plot.signals.keys())):
            is_stack_plot_focused = self._focus_plot_stack_key == key

            if self.canvas.full_mode_all_stack or self._focus_plot_stack_key is None or is_stack_plot_focused:
                signals = plot.signals.get(key) or list()

                if not self.canvas.full_mode_all_stack and self._focus_plot_stack_key is not None:
                    row_id = 0
                else:
                    row_id = stack_id

                mpl_axes = self.figure.add_subplot(subgrid_item[row_id + add_slider:, 0], sharex=mpl_axes_prev)
                mpl_axes_prev = mpl_axes
                self._plot_impl_plot_lut[id(plot)].append(mpl_axes)
                # Keep references to iplotlib instances for ease of access in callbacks.
                self._impl_plot_cache_table.register(mpl_axes, self.canvas, plot, key, signals)
                mpl_axes.set_xmargin(0)
                mpl_axes.set_autoscalex_on(True)
                mpl_axes.set_autoscaley_on(True)

                # Set the plot title
                if plot.plot_title is not None and stack_id == 0:
                    fc = self._pm.get_value(plot, 'font_color')
                    fs = self._pm.get_value(plot, 'font_size')
                    if not fs:
                        fs = None
                    mpl_axes.set_title(plot.plot_title, color=fc, size=fs)

                # Set the background color
                mpl_axes.set_facecolor(self._pm.get_value(plot, 'background_color'))

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
                show_grid = self._pm.get_value(plot, 'grid')
                log_scale = self._pm.get_value(plot, 'log_scale')

                if show_grid:
                    if log_scale:
                        mpl_axes.grid(show_grid, which='both')
                    else:
                        mpl_axes.grid(show_grid, which='major')
                else:
                    mpl_axes.grid(show_grid, which='both')

                x_axis = None
                # Update properties of the plot axes
                for ax_idx in range(len(plot.axes)):
                    if isinstance(plot.axes[ax_idx], Collection):
                        y_axis = plot.axes[ax_idx][stack_id]
                        self.process_ipl_axis(y_axis, ax_idx, plot, mpl_axes)
                    else:
                        x_axis = plot.axes[ax_idx]
                        self.process_ipl_axis(x_axis, ax_idx, plot, mpl_axes)

                for signal in signals:
                    self._signal_impl_plot_lut.update({id(signal): mpl_axes})
                    self.process_ipl_signal(signal)

                # Set limits for processed signals
                if isinstance(x_axis, RangeAxis) and x_axis.begin is None and x_axis.end is None:
                    self.update_range_axis(x_axis, 0, mpl_axes, which='current')
                    self.update_range_axis(x_axis, 0, mpl_axes, which='original')

                # Show the plot legend if enabled
                show_legend = self._pm.get_value(plot, 'legend')
                if show_legend and mpl_axes.get_lines():
                    plot_leg_position = self._pm.get_value(plot, 'legend_position')
                    canvas_leg_position = self._pm.get_value(self.canvas, 'legend_position')
                    plot_leg_layout = self._pm.get_value(plot, 'legend_layout')
                    canvas_leg_layout = self._pm.get_value(self.canvas, 'legend_layout')

                    plot_leg_position = canvas_leg_position if plot_leg_position == 'same as canvas' \
                        else plot_leg_position
                    plot_leg_layout = canvas_leg_layout if plot_leg_layout == 'same as canvas' \
                        else plot_leg_layout

                    legend_props = dict(size=self.legend_size)

                    # Legend creation process:
                    #   - Vertical legend: it has one column, which will be increased until there is no overlapping of
                    #   lines up to a maximum of 3 columns, (1, 3).
                    #   - Horizontal legend: the number of columns corresponds to the number of signals contained in the
                    #   plot. If there is line overlapping, the number of columns will be reduced, (len(signals), 1).
                    leg_ver = (1, 3)
                    leg_hor = (len(signals), 1)
                    # The case is established as follows
                    case = leg_ver if plot_leg_layout == 'vertical' else leg_hor
                    start, stop = case
                    step = 1 if start < stop else -1
                    leg = None
                    for col in range(start, stop + step, step):
                        leg = mpl_axes.legend(prop=legend_props, loc=plot_leg_position, ncol=col)
                        if self.figure.get_tight_layout():
                            leg.set_in_layout(False)
                        # Check if the legend's edges are outside the axes' bounds in the figure
                        legend_bbox = leg.get_window_extent()
                        axes_bbox = mpl_axes.get_window_extent()
                        legend_bbox = legend_bbox.transformed(self.figure.transFigure.inverted())
                        axes_bbox = axes_bbox.transformed(self.figure.transFigure.inverted())
                        legend_outside = (
                                legend_bbox.xmin < axes_bbox.xmin or
                                legend_bbox.xmax > axes_bbox.xmax or
                                legend_bbox.ymin < axes_bbox.ymin or
                                legend_bbox.ymax > axes_bbox.ymax
                        )
                        if not legend_outside:
                            break

                    # Check the text of the legend lines in case there is a '$' to be escaped
                    for line in leg.texts:
                        current_text = line.get_text()
                        if '$' in current_text:
                            new_text = current_text.replace("$", r"\$")
                            line.set_text(new_text)

                    legend_lines = leg.get_lines()
                    ix_legend = 0
                    for signal in signals:
                        for line in self._signal_impl_shape_lut.get(id(signal)):
                            self.map_legend_to_ax[legend_lines[ix_legend]] = [line, signal]
                            alpha = 1 if legend_lines[ix_legend].get_visible() else 0.2
                            legend_lines[ix_legend].set_picker(3)
                            legend_lines[ix_legend].set_visible(True)
                            legend_lines[ix_legend].set_alpha(alpha)
                            ix_legend += 1

        # Observe the axis limit change events
        if not self.canvas.streaming and not isinstance(plot, PlotXYWithSlider):
            for axes in mpl_axes.get_shared_x_axes().get_siblings(mpl_axes):
                axes.callbacks.connect('xlim_changed', self._axis_update_callback)
                # axes.callbacks.connect('ylim_changed', self._axis_update_callback)

    def _axis_update_callback(self, mpl_axes):

        affected_axes = mpl_axes.get_shared_x_axes().get_siblings(mpl_axes)
        if self.canvas.shared_x_axis and not self.canvas.undo_redo:
            other_axes = self._get_all_shared_axes(mpl_axes)
            for other_axis in other_axes:
                cur_x_limits = self.get_oaw_axis_limits(mpl_axes, 0)
                other_x_limits = self.get_oaw_axis_limits(other_axis, 0)
                if cur_x_limits[0] != other_x_limits[0] or cur_x_limits[1] != other_x_limits[1]:
                    self.set_oaw_axis_limits(other_axis, 0, cur_x_limits)

        for a in affected_axes:
            ranges_hash = hash((*a.get_xlim(), *a.get_ylim()))
            current_hash = self._impl_plot_ranges_hash.get(id(a))

            if current_hash is not None and (ranges_hash == current_hash):
                continue

            self._impl_plot_ranges_hash[id(a)] = ranges_hash

            ci = self._impl_plot_cache_table.get_cache_item(a)
            if not hasattr(ci, 'plot'):
                continue
            if not isinstance(ci.plot(), Plot):
                continue
            ranges = []

            for ax_idx, ax in enumerate(ci.plot().axes):
                if isinstance(ax, Collection):
                    self.update_multi_range_axis(ax, ax_idx, a)
                elif isinstance(ax, RangeAxis):
                    self.update_range_axis(ax, ax_idx, a)
                    ranges = ax.get_limits()
            if ci not in self._stale_citems:
                self._stale_citems.append(ci)
            if self.canvas.undo_redo:
                continue
            if not hasattr(ci, 'signals'):
                continue
            if not ci.signals:
                continue
            for signal_ref in ci.signals:
                signal = signal_ref()
                if hasattr(signal, "set_xranges"):
                    if signal.x_expr != '${self}.time' and len(signal.data_store[0]) > 0 and len(signal.x_data) > 0:
                        idx1 = np.searchsorted(signal.x_data, ranges[0])
                        idx2 = np.searchsorted(signal.x_data, ranges[1])

                        if idx1 != 0:
                            idx1 -= 1
                        if idx2 != len(signal.x_data):
                            idx2 += 1

                        signal_begin = signal.data_store[0][idx1:idx2][0]
                        signal_end = signal.data_store[0][idx1:idx2][-1]

                        signal.set_xranges([signal_begin, signal_end])
                    else:
                        signal.set_xranges(ranges)

                    logger.debug(f"callback update {ranges[0]} axis range to {ranges[1]}")

    def process_ipl_axis(self, axis: Axis, ax_idx, plot: Plot, impl_plot: MPLAxes):
        super().process_ipl_axis(axis, ax_idx, plot, impl_plot)
        mpl_axis = self.get_impl_axis(impl_plot, ax_idx)  # type: MPLAxis
        self._axis_impl_plot_lut.update({id(axis): impl_plot})

        if isinstance(axis, Axis):

            if isinstance(mpl_axis, YAxis):
                log_scale = self._pm.get_value(plot, 'log_scale')
                if log_scale:
                    mpl_axis.axes.set_yscale('log')
                    # Format for minor ticks
                    y_minor = LogLocator(base=10, subs=(1.0,))
                    mpl_axis.set_minor_locator(y_minor)

            fc = self._pm.get_value(axis, 'font_color')
            fs = self._pm.get_value(axis, 'font_size')

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

        if isinstance(axis, RangeAxis) and axis.begin is not None and axis.end is not None:
            # autoscale = self._pm.get_value('autoscale', axis)
            if self._pm.get_value(axis, 'autoscale') and ax_idx == 1:
                self.autoscale_y_axis(impl_plot)
            else:
                logger.debug(f"process_ipl_axis: setting {ax_idx} axis range to {axis.begin} and {axis.end}")
                self.set_oaw_axis_limits(impl_plot, ax_idx, [axis.begin, axis.end])
        if isinstance(axis, LinearAxis) and axis.is_date:
            ci = self._impl_plot_cache_table.get_cache_item(impl_plot)
            mpl_axis.set_major_formatter(
                NanosecondDateFormatter(ax_idx, offset_lut=ci.offsets, roundh=self.canvas.round_hour))

        # Configurate number of ticks and labels
        tick_number = self._pm.get_value(axis, 'tick_number')
        mpl_axis.set_major_locator(MaxNLocator(tick_number))

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
            logger.error(f"MPLAxes not found for signal {signal}. Unexpected error. signal_id: {id(signal)}")
            return

        # All good, make a data access request.
        # logger.debug(f"\tprocessipsignal before ts_start {signal.ts_start} ts_end {signal.ts_end}
        # status: {signal.status_info.result} ")
        signal_data = signal.get_data()

        data = self.transform_data(mpl_axes, signal_data)

        if hasattr(signal, 'envelope') and signal.envelope:
            if len(data) != 3:
                logger.error(f"Requested to draw envelope for sig({id(signal)}), but it does not have sufficient data"
                             f" arrays (==3). {signal}")
                return
            self.do_mpl_envelope_plot(signal, mpl_axes, data[0], data[1], data[2])
        else:
            if len(data) < 2:
                logger.error(f"Requested to draw line for sig({id(signal)}), but it does not have sufficient data "
                             f"arrays (<2). {signal}")
                return
            self.do_mpl_line_plot(signal, mpl_axes, data)

        self.update_axis_labels_with_units(mpl_axes, signal)

    def autoscale_y_axis(self, impl_plot, margin=0.1):
        """This function rescales the y-axis based on the data that is visible given the current xlim of the axis.
        ax -- a matplotlib axes object
        margin -- the fraction of the total height of the y-data to pad the upper and lower ylims"""

        def get_bottom_top(x_line):
            xd = x_line.get_xdata()
            yd = x_line.get_ydata()
            lo, hi = impl_plot.get_xlim()
            y_displayed = yd[((xd > lo) & (xd < hi))]
            if len(y_displayed) > 0:
                # Check if there exist NaN values in the y_displayed array
                if np.isnan(y_displayed).any():
                    y_displayed = y_displayed[~np.isnan(y_displayed)]
                h = np.max(y_displayed) - np.min(y_displayed)
                min_bot = np.min(y_displayed) - margin * h
                max_top = np.max(y_displayed) + margin * h
            else:
                min_bot = 0
                max_top = 1
            return min_bot, max_top

        lines = impl_plot.get_lines()
        lines = [line for line in lines if line.get_label() not in ["CrossX", "CrossY"]]
        bot, top = np.inf, -np.inf

        for line in lines:
            new_bot, new_top = get_bottom_top(line)
            if new_bot < bot:
                bot = new_bot
            if new_top > top:
                top = new_top
        if lines:
            self.set_oaw_axis_limits(impl_plot, 1, (bot, top))

    def enable_tight_layout(self):
        self.figure.set_layout_engine("tight")

    def disable_tight_layout(self):
        self.figure.set_layout_engine("constrained")

    def set_focus_plot(self, mpl_axes):

        def get_x_axis_range(focus_plot):
            if focus_plot is not None and focus_plot.axes is not None and len(focus_plot.axes) > 0 and \
                    isinstance(focus_plot.axes[0], RangeAxis):
                return focus_plot.axes[0].begin, focus_plot.axes[0].end

        def set_x_axis_range(focus_plot, x_begin, x_end):
            if focus_plot is not None and focus_plot.axes is not None and len(focus_plot.axes) > 0 and \
                    isinstance(focus_plot.axes[0], RangeAxis):
                focus_plot.axes[0].begin = x_begin
                focus_plot.axes[0].end = x_end

        if isinstance(mpl_axes, MPLAxes):
            ci = self._impl_plot_cache_table.get_cache_item(mpl_axes)
            plot = ci.plot()
            stack_key = ci.stack_key
        else:
            plot = None
            stack_key = None

        logger.debug(f"Focusing on plot: {id(plot)}, stack_key: {stack_key}")

        if self._focus_plot is not None and plot is None:
            if self.canvas.shared_x_axis and len(self._focus_plot.axes) > 0 and isinstance(self._focus_plot.axes[0],
                                                                                           RangeAxis):
                begin, end = get_x_axis_range(self._focus_plot)

                for columns in self.canvas.plots:
                    for plot_temp in columns:
                        if plot_temp and plot_temp != self._focus_plot:  # Avoid None plots
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
                IplotMultiCursor(self.figure.canvas, axes_group,
                                 x_label=self.canvas.enable_x_label_crosshair,
                                 y_label=self.canvas.enable_y_label_crosshair,
                                 val_label=self.canvas.enable_val_label_crosshair,
                                 color=self.canvas.crosshair_color,
                                 lw=self.canvas.crosshair_line_width,
                                 horiz_on=False or self.canvas.crosshair_horizontal,
                                 vert_on=self.canvas.crosshair_vertical,
                                 use_blit=True,
                                 cache_table=self._impl_plot_cache_table))

    @BackendParserBase.run_in_one_thread
    def deactivate_cursor(self):
        for cursor in self._cursors:
            cursor.remove()
        self._cursors.clear()

    def get_signal_style(self, signal: SignalXY) -> dict:
        style = dict()
        if signal.label:
            style['label'] = signal.label
        if hasattr(signal, "color"):
            style['color'] = self._pm.get_value(signal, 'color')
        style['linewidth'] = self._pm.get_value(signal, 'line_size')
        style['linestyle'] = (self._pm.get_value(signal, 'line_style')).lower()
        style['marker'] = self._pm.get_value(signal, 'marker')
        style['markersize'] = self._pm.get_value(signal, 'marker_size')
        step = self._pm.get_value(signal, 'step')
        if step is None:
            step = 'linear'
        style["drawstyle"] = STEP_MAP[step]

        return style

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

    def get_oaw_axis_limits(self, impl_plot, ax_idx: int):
        """Offset-aware version of implementation's get_x_limit, get_y_limit"""
        begin, end = (None, None)
        if ax_idx == 0:
            begin, end = self.get_impl_x_axis_limits(impl_plot)
        elif ax_idx == 1:
            begin, end = self.get_impl_y_axis_limits(impl_plot)
        return self.transform_value(impl_plot, ax_idx, begin), self.transform_value(impl_plot, ax_idx, end)

    def set_impl_x_axis_limits(self, impl_plot: Any, limits: tuple):
        if isinstance(impl_plot, MPLAxes):
            impl_plot.set_xlim(limits[0], limits[1])

    def set_impl_y_axis_limits(self, impl_plot: Any, limits: tuple):
        if isinstance(impl_plot, MPLAxes):
            impl_plot.set_ylim(limits[0], limits[1])
        else:
            return None

    def set_oaw_axis_limits(self, impl_plot: Any, ax_idx: int, limits) -> None:
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

    def set_impl_x_axis_label_text(self, impl_plot: Any, text: str):
        """Implementations should set the x_axis label text"""
        self.get_impl_x_axis(impl_plot).set_label_text(text)

    def set_impl_y_axis_label_text(self, impl_plot: Any, text: str):
        """Implementations should set the y_axis label text"""
        self.get_impl_y_axis(impl_plot).set_label_text(text)

    def transform_value(self, impl_plot: Any, ax_idx: int, value: Any, inverse=False):
        """Adds or subtracts axis offset from value trying to preserve type of offset (ex: does not convert to
        float when offset is int)"""
        return self._impl_plot_cache_table.transform_value(impl_plot, ax_idx, value, inverse=inverse)

    def transform_data(self, impl_plot: Any, data):
        """This function post processes data if it cannot be plotted with matplotlib directly.
        Currently, it transforms data if it is a large integer which can cause overflow in matplotlib"""
        ret = []
        if isinstance(data, Collection):
            for i, d in enumerate(data):
                logger.debug(f"\t transform data i={i} d = {d} ")
                ci = self._impl_plot_cache_table.get_cache_item(impl_plot)
                if ci and ci.offsets[i] is None and i == 0:
                    ci.offsets[i] = self.create_offset(d)

                if ci and ci.offsets[i] is not None:
                    logger.debug(f"\tApplying data offsets {ci.offsets[i]} to to plot {id(impl_plot)} ax_idx: {i}")
                    if isinstance(d, Collection):
                        ret.append(BufferObject([np.int64(e) - ci.offsets[i] for e in d]))
                    else:
                        ret.append(np.int64(d) - ci.offsets[i])
                else:
                    ret.append(d)
        return ret


def get_data_range(data, axis_idx):
    """Returns first and last value from data[axis_idx] or None"""
    if data is not None and len(data) > axis_idx and len(data[axis_idx] > 0):
        return data[axis_idx][0], data[axis_idx][-1]
    return None
