# Changelog:
#   Jan 2023:   -Added support for legend position and layout [Alberto Luengo]

from typing import Any, Callable, Collection, List
import pandas
import numpy as np
from matplotlib.axes import Axes as MPLAxes
from matplotlib.axis import Tick, YAxis
from matplotlib.axis import Axis as MPLAxis
import matplotlib.dates as mdates
from matplotlib.patches import Patch
from matplotlib.contour import QuadContourSet
from matplotlib.figure import Figure
from matplotlib.gridspec import GridSpecFromSubplotSpec, SubplotSpec
from matplotlib.lines import Line2D
from matplotlib.text import Annotation
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
import warnings

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
        self._crosshairs = {}

        # Sync all the sliders for shared time
        self._slider_plots: List[PlotXYWithSlider] = []

        register_matplotlib_converters()
        # Use constrained_layout by default; switch to tight only if explicitly requested
        self.figure = Figure(constrained_layout=True)
        if canvas and getattr(canvas, 'tight_layout', False):
            self.enable_tight_layout()
        else:
            self.disable_tight_layout()

        self._impl_plot_ranges_hash = dict()

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

    def do_mpl_line_plot_xy_slider(self, signal: SignalXY, mpl_axes: MPLAxes,
                                   plot: PlotXYWithSlider, cache_item,
                                   x_data, y_data, z_data):
        """
        Draw or update an XY plot driven by a slider.
        Creates Line2D objects only on first call, then updates their data.
        """
        # retrieve existing line groups if any
        existing = getattr(signal, 'lines', None)
        # determine current frame index, default to zero
        idx = int(plot.slider.val) if getattr(plot, 'slider', None) else 0
        y_slice = y_data[idx]

        # assign color on initial creation
        if signal.color is None:
            signal.color = plot.get_next_color()

        if existing:
            # update stored lines rather than creating new ones
            if x_data.ndim == 1 and y_slice.ndim == 1:
                ln = existing[0][0]
                ln.set_xdata(x_data)
                ln.set_ydata(y_slice)
            else:
                # for multi-column data, update each group
                for grp, arr in zip(existing, y_slice.T if y_slice.ndim == 2 else [y_slice]):
                    line = grp[0]
                    line.set_xdata(x_data)
                    line.set_ydata(arr)

            # preserve previous visibility settings
            for new_grp, old_grp in zip(existing, signal.lines):
                for new_ln, old_ln in zip(new_grp, old_grp):
                    new_ln.set_visible(old_ln.get_visible())
            signal.lines = existing

            # adjust zoomed X region dynamically in streaming mode
            if self.canvas.streaming:
                span = mpl_axes.get_xlim()[1] - mpl_axes.get_xlim()[0]
                vals = []
                for s in plot.signals[cache_item.stack_key]:
                    if s.lines[0][0].get_visible() and s.x_data.size:
                        max_x = s.x_data.max()[0]
                        for xv, yv in zip(s.x_data, s.y_data):
                            if max_x - span <= xv <= max_x:
                                vals.append(yv)
                if vals:
                    pad = (max(vals) - min(vals)) / 15
                    mpl_axes.set_ylim(min(vals) - pad, max(vals) + pad)
                mpl_axes.set_xlim(max(x_data) - span, max(x_data))

            # auto-rescale Y axis so that any peaks remain visible
            self.autoscale_y_axis(mpl_axes)

            # if the plot is in log scale, recompute limits and minor ticks
            if mpl_axes.get_yscale() == 'log':
                try:
                    mpl_axes.relim()  # recompute data limits
                    mpl_axes.autoscale_view(scalex=False, scaley=True)  # autoscale only the Y axis
                    mpl_axes.yaxis.set_minor_locator(LogLocator(base=10, subs=(1.0,)))
                except ValueError:
                    # skip if data has no positive values
                    pass

            # trigger a non-blocking redraw
            self.figure.canvas.draw_idle()

        else:
            # create lines on first draw and store them for updates
            params = dict(**self.get_signal_style(signal))
            drawer = mpl_axes.plot

            if x_data.ndim == 1 and y_slice.ndim == 1:
                lines = [drawer(x_data, y_slice, **params)]
            else:
                raw = drawer(x_data, y_slice, **params)
                lines = [[ln] for ln in raw]
                for i, grp in enumerate(lines):
                    grp[0].set_label(f"{signal.label}[{i}]")

            # cache the new lines and update signal.lines
            self._signal_impl_shape_lut.update({id(signal): lines})
            signal.lines = lines

            # if the plot is in log scale on first draw, apply log autoscaling
            if mpl_axes.get_yscale() == 'log':
                try:
                    mpl_axes.relim()
                    mpl_axes.autoscale_view(scalex=False, scaley=True)
                    mpl_axes.yaxis.set_minor_locator(LogLocator(base=10, subs=(1.0,)))
                except ValueError:
                    pass

        return signal.lines

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

    def _get_all_shared_axes(self, base_mpl_axes: MPLAxes, slider: bool = False):
        if not isinstance(self.canvas, Canvas):
            return []

        cache_item = self._impl_plot_cache_table.get_cache_item(base_mpl_axes)
        if not hasattr(cache_item, 'plot'):
            return
        base_plot = cache_item.plot()
        if not isinstance(base_plot, Plot):
            return
        if isinstance(base_plot, PlotXYWithSlider) and not slider:
            return []
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
                # Need to differentiate if it is absolute or relative
                if plot.axes[0].is_date or isinstance(plot, PlotXYWithSlider):
                    max_diff_ns = self.canvas.max_diff * 1e9
                else:
                    max_diff_ns = self.canvas.max_diff
                if ((begin, end) == (base_begin, base_end) or (
                        abs(begin - base_begin) <= max_diff_ns and abs(end - base_end) <= max_diff_ns)):
                    shared.append(axes)
        return shared

    def process_ipl_canvas(self, canvas: Canvas):
        """
        Process/redraw the entire canvas, including layout and slider state.
        Depending on focus state, either redraws the full grid or a single plot.
        """
        super().process_ipl_canvas(canvas)
        self.canvas = canvas

        if canvas is None:
            self.clear()
            return

        self.clear()

        # Explicitly set layout engine based on canvas attribute
        if getattr(canvas, 'tight_layout', False):
            self.enable_tight_layout()
        else:
            self.disable_tight_layout()

        # === CASE 1: Full grid (no focus) ===
        if self._focus_plot is None:
            self._layout = self.figure.add_gridspec(canvas.rows, canvas.cols)

            for col_idx, col in enumerate(canvas.plots):
                for row_idx, plot in enumerate(col):
                    self.process_ipl_plot(plot, col_idx, row_idx)

                    # Ensure slider axes don't hide avxspan
                    if isinstance(plot, PlotXYWithSlider) and getattr(plot, 'slider', None):
                        plot.slider.ax.set_facecolor('none')
                        plot.slider.ax.patch.set_alpha(0.0)

            if canvas.title:
                self.figure.suptitle(
                    canvas.title,
                    size=self._pm.get_value(canvas, 'font_size') or None,
                    color=self._pm.get_value(canvas, 'font_color') or 'black'
                )


            # Tight layout for canvas
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                self.figure.tight_layout()
            self.figure.canvas.draw_idle()

            return

        # === CASE 2: Focus mode ===
        self._layout = self.figure.add_gridspec(1, 1)

        if isinstance(self._focus_plot, PlotXYWithSlider):
            self._focus_plot._slider_initialized = False

        self.process_ipl_plot(self._focus_plot, 0, 0)

        if self._focus_plot and isinstance(self._focus_plot, PlotXYWithSlider):
            if getattr(self._focus_plot, 'slider', None):
                self._focus_plot.slider.ax.set_facecolor('none')
                self._focus_plot.slider.ax.patch.set_alpha(0.0)

        if canvas.title:
            self.figure.suptitle(
                canvas.title,
                size=self._pm.get_value(canvas, 'font_size') or None,
                color=self._pm.get_value(canvas, 'font_color') or 'black'
            )

        self.figure.canvas.draw_idle()

    def process_ipl_plot_xy(self):
        pass

    def process_ipl_plot_contour(self):
        pass

    def process_ipl_plot(self, plot: Plot, column: int, row: int):
        """Map an iplotlib Plot to one or more matplotlib Axes."""
        logger.debug(f"process_ipl_plot: step={self._pm.get_value(self.canvas, 'step')}")
        super().process_ipl_plot(plot, column, row)
        if not isinstance(plot, Plot):
            return

        # Determine number of signal rows above the slider
        stack_sz = 1 if (not self.canvas.full_mode_all_stack and self._focus_plot_stack_key) else len(plot.signals)
        grid_cell = self._layout[row:row + plot.row_span, column:column + plot.col_span]

        if isinstance(plot, PlotXYWithSlider):
            # Remove old slider only on full redraw (not in focus mode)
            if self._focus_plot is None:
                self._remove_existing_slider(plot)

            # Choose height ratios and spacing for home vs focus
            if plot is self._focus_plot:
                # Focused slider: allocate more vertical space to the plot
                height_ratios = [0.95] * stack_sz + [0.05]
                hspace = 0.15
            else:
                # Standard slider layout for home
                height_ratios = [1.0] * stack_sz + [0.05]
                hspace = 0.4

            # Create a subgrid: stack_sz plot rows + 1 slider row
            subgrid = grid_cell.subgridspec(
                nrows=stack_sz + 1,
                ncols=1,
                height_ratios=height_ratios,
                hspace=hspace
            )

            # 1) Add stacked axes and get the last axes object
            mpl_axes_list, last_axes = self._add_stack_axes(plot, subgrid, stack_sz, slider_mode=True)
            plot._mpl_axes_list = mpl_axes_list

            # 2) Initialize Y-axis limits for slider-driven plots
            self.update_multi_range_axis(plot.axes[1], 1, last_axes)

            # 3) Draw legend on the last axes if enabled
            if self._pm.get_value(plot, 'legend') and last_axes.get_lines():
                self._draw_plot_legend(plot, last_axes, signals=sum(plot.signals.values(), []))

            # 4) Create or update the slider widget
            self._initialize_slider(plot, subgrid[stack_sz, 0])

            # 5) Fine-tune X-label and slider positions
            slider_ax = plot.slider.ax
            x0, y0, w, h = slider_ax.get_position().bounds

            # Shift the slider down so the label can sit just above it
            slider_ax.set_position([x0, y0 - 0.02, w, h])

            # Shift X label just above the slider in a smart way
            y_offset = -0.03 if plot is self._focus_plot else -0.08
            last_axes.xaxis.set_label_coords(0.5, y_offset)
            last_axes.xaxis.labelpad = 4

        else:
            # Standard (no-slider) plot: single grid row, no slider
            subgrid = grid_cell.subgridspec(nrows=stack_sz, ncols=1, hspace=0.0)
            mpl_axes_list, last_axes = self._add_stack_axes(plot, subgrid, stack_sz, slider_mode=False)

            # Draw legend if enabled
            if self._pm.get_value(plot, 'legend') and last_axes.get_lines():
                self._draw_plot_legend(plot, last_axes, signals=sum(plot.signals.values(), []))


        # Connect x-limits callback for shared-axis synchronization
        self._connect_limit_callbacks(last_axes)

        # Restore red-highlight range for shared X if needed
        if isinstance(plot, PlotXYWithSlider) and self.canvas.shared_x_axis:
            x_axis = plot.axes[0]
            if isinstance(x_axis, RangeAxis) and x_axis.begin is not None and x_axis.end is not None:
                self.update_slider_limits(plot, x_axis.begin, x_axis.end)

    def _remove_existing_slider(self, plot: PlotXYWithSlider):
        """
        Remove the slider axes and event handler without deleting
        the Slider object itself, so that history or preferences
        can still refer to plot.slider afterward.
        """
        # Only remove if we had initialized it antes y realmente hay slider
        if not getattr(plot, '_slider_initialized', False):
            return
        slider = getattr(plot, 'slider', None)
        if slider is None:
            return

        # disconnect the click event so we don’t accumulate multiple handlers
        cid = getattr(slider, '_cid_click', None)
        if cid is not None:
            self.figure.canvas.mpl_disconnect(cid)
            del plot._cid_click

        # remove from our list of active sliders
        if plot in self._slider_plots:
            self._slider_plots.remove(plot)

        slider_ax = slider.ax
        for child in list(slider_ax.get_children()):
            if isinstance(child, Slider):
                child.remove()
            elif isinstance(child, Patch) and child.get_label() == 'slider_red_range':
                child.remove()
            elif isinstance(child, plt.Annotation):
                child.remove()
            elif isinstance(child, Line2D):
                child.remove()

        # mark as uninitialized for future recreation
        plot._slider_initialized = False

    def _add_stack_axes(self, plot, subgrid, stack_sz, slider_mode):
        """
        Always create fresh stacked axes (one row per signal stack), clear any old
        shape‐LUT entries, and draw every signal anew. Returns (axes_list, last_ax).
        """
        axes_list = []
        prev_ax = None  # for shared x-axis

        # Create one axes per signal‐stack
        for stack_id, key in enumerate(sorted(plot.signals.keys())):
            # skip non‐focused stacks if not full_mode
            if not (self.canvas.full_mode_all_stack or self._focus_plot_stack_key in (None, key)):
                continue

            # row 0 if focused single‐stack, else incremental
            row = 0 if (self._focus_plot_stack_key and not self.canvas.full_mode_all_stack) else stack_id

            # always fresh subplot, sharing x if prev_ax
            ax = self.figure.add_subplot(subgrid[row, 0], sharex=prev_ax)
            ax.set_navigate(True)
            axes_list.append(ax)
            prev_ax = ax

            # register this axes
            signals = plot.signals.get(key, []) or []
            self._plot_impl_plot_lut[id(plot)].append(ax)
            self._impl_plot_cache_table.register(ax, self.canvas, plot, key, signals)

            # clear any old line‐cache for each signal and draw it
            for sig in signals:
                sig.lines = None
                self._signal_impl_shape_lut.pop(id(sig), None)
                self._signal_impl_plot_lut[sig.uid] = ax
                self.process_ipl_signal(sig)

            # apply title, grid, colors, ticks…
            self._configure_axes_properties(plot, ax, stack_id, signals)

        # store for future reference (not reuse)
        plot._mpl_axes_list = axes_list
        last_ax = axes_list[-1] if axes_list else None
        return axes_list, last_ax

    def _configure_axes_properties(self, plot, mpl_axes, stack_id, signals):
        """Apply title, facecolor, tick visibility, grid, and process axes."""
        # title only on first stack
        if plot.plot_title and stack_id == 0:
            mpl_axes.set_title(plot.plot_title,
                               color=self._pm.get_value(plot, 'font_color'),
                               size=self._pm.get_value(plot, 'font_size') or None)

        # facecolor and grid
        mpl_axes.set_facecolor(self._pm.get_value(plot, 'background_color'))
        show_grid = self._pm.get_value(plot, 'grid')
        log_scale = self._pm.get_value(plot, 'log_scale')
        mpl_axes.grid(show_grid, which='both' if log_scale else 'major')

        # ensure data touches the left border: remove extra horizontal padding
        mpl_axes.set_xmargin(0)

        # X-axis tick visibility
        last_row = (stack_id + 1 == len(plot.signals.values()))
        visible = last_row or (stack_id == self._focus_plot_stack_key and not self.canvas.full_mode_all_stack)
        for child in mpl_axes.get_xaxis().get_children():
            child.set_visible(visible)

        # process each Axis object (labels, formatting, etc.)
        x_axis = None
        for ax_idx, ax in enumerate(plot.axes):
            if isinstance(ax, Collection):
                self.process_ipl_axis(ax[stack_id], ax_idx, plot, mpl_axes)
            else:
                x_axis = ax
                self.process_ipl_axis(ax, ax_idx, plot, mpl_axes)
                if isinstance(plot, PlotXYWithSlider):
                    mpl_axes.xaxis.set_label_coords(0.5, -0.1)
                    mpl_axes.xaxis.labelpad = 3

        # initialize x-limits if needed
        if isinstance(x_axis, RangeAxis) and x_axis.begin is None and x_axis.end is None:
            self.update_range_axis(x_axis, 0, mpl_axes, which='current')
            orig = plot.signals[1][0].z_data
            x_axis.set_limits(orig[0], orig[-1], 'original')

        # initialize Y-limits for slider type
        if isinstance(plot, PlotXYWithSlider):
            self.update_multi_range_axis(plot.axes[1], 1, mpl_axes)

    def _draw_plot_legend(self, plot, mpl_axes, signals: List[SignalXY]):
        """Common legend creation logic, mapping legend entries to lines."""
        pos = self._pm.get_value(plot, 'legend_position')
        layout = self._pm.get_value(plot, 'legend_layout')
        canvas_layout = self._pm.get_value(self.canvas, 'legend_layout')
        pos = self._pm.get_value(self.canvas, 'legend_position') if pos == 'same as canvas' else pos
        layout = canvas_layout if layout == 'same as canvas' else layout

        # Determine the range of columns to try depending on the layout orientation
        ver = (1, 3)
        hor = (len(signals), 1)
        case = ver if layout == 'vertical' else hor

        for ncol in range(case[0], case[1] + (1 if case[0] < case[1] else -1), (1 if case[0] < case[1] else -1)):
            leg = mpl_axes.legend(prop=dict(size=self.legend_size), loc=pos, ncol=ncol)

            # If using tight_layout, exclude the legend from layout calculation
            if self.figure.get_layout_engine().__class__.__name__.lower() == "tightlayoutengine":
                leg.set_in_layout(False)

            # Break once the legend fully fits inside the axes area
            bb_leg = leg.get_window_extent().transformed(self.figure.transFigure.inverted())
            bb_ax = mpl_axes.get_window_extent().transformed(self.figure.transFigure.inverted())
            if not (
                    bb_leg.xmin < bb_ax.xmin or
                    bb_leg.xmax > bb_ax.xmax or
                    bb_leg.ymin < bb_ax.ymin or
                    bb_leg.ymax > bb_ax.ymax
            ):
                break

        # Escape dollar signs for LaTeX-like strings
        for txt in leg.texts:
            txt.set_text(txt.get_text().replace("$", r"\$"))

        # Map legend lines to corresponding signals for click handling
        legend_lines = leg.get_lines()
        for idx, sig in enumerate(signals):
            for line in self._signal_impl_shape_lut.get(id(sig), []):
                proxy = legend_lines[idx]
                self.map_legend_to_ax[proxy] = [line, sig]
                proxy.set_picker(3)
                proxy.set_alpha(1.0 if proxy.get_visible() else 0.2)

    def _initialize_slider(self, plot: PlotXYWithSlider, slider_spec, axes_list=None):
        """Add slider axes, widget, formatter and callbacks."""
        from matplotlib.backend_bases import MouseButton

        # skip if already initialized
        if getattr(plot, '_slider_initialized', False):
            return

        # create slider axes and disable pan/zoom on them
        slider_ax = self.figure.add_subplot(slider_spec)
        slider_ax.set_label("slider")
        slider_ax.text(
            0.5, 0.5, "",
            color="black", fontsize=12, ha="center", va="center",
            transform=slider_ax.transAxes
        )
        # Ensure the slider axis is rendered above other plots and background is transparent
        slider_ax.set_zorder(10)
        slider_ax.patch.set_alpha(0.0)

        slider_ax.set_navigate(False)

        # build time labels for min, current and max
        times = plot.signals[1][0].z_data
        formatter = NanosecondDateFormatter(ax_idx=0)
        labels = [
            formatter.date_fmt(
                t.value,
                formatter.YEAR if i == 0 else formatter.cut_start + 3,
                formatter.NANOSECOND,
                postfix_end=True
            )
            for i, t in enumerate([
                pandas.Timestamp(times[0]),
                pandas.Timestamp(times[0]),
                pandas.Timestamp(times[-1])
            ])
        ]

        # draw the annotations on the slider track
        slider_ax.annotate(labels[0],
                           xy=(0, -0.3), xycoords='axes fraction',
                           ha='left', va='center', fontsize=8)
        current_label = slider_ax.annotate(labels[1],
                                           xy=(0.425, -0.3), xycoords='axes fraction',
                                           ha='left', va='center', fontsize=8)
        slider_ax.annotate(labels[2],
                           xy=(0.85, -0.3), xycoords='axes fraction',
                           ha='left', va='center', fontsize=8)

        # instantiate the Slider widget
        plot.slider = Slider(
            slider_ax,
            '',
            0,
            len(times) - 1,
            valinit=(plot.slider_last_val or 0),
            valstep=1
        )

        # patch its internal _update so we always release any prior grab
        original_update = plot.slider._update
        def patched_update(event):
            """
            Ensure no stale grab remains before calling the real update.
            If grabbing still fails, log it but do not interrupt the loop.
            """
            ax = event.inaxes
            if ax is not None:
                try:
                    event.canvas.release_mouse(ax)
                except Exception:
                    pass

            try:
                original_update(event)
            except RuntimeError as e:
                logger.warning(f"Slider update grab error: {e}")
                try:
                    original_update(event)
                except RuntimeError:
                    pass

        plot.slider._update = patched_update

        # allow click as well as drag on the slider track
        def slider_click(event):
            if event.inaxes == slider_ax and event.button == MouseButton.LEFT:
                idx = int(round(event.xdata))
                # clamp to the red‐zone limits
                idx = max(int(plot.slider.valmin), min(idx, int(plot.slider.valmax)))
                plot.slider.set_val(idx)

        cid = self.figure.canvas.mpl_connect('button_press_event', slider_click)
        plot._cid_click = cid

        # capture axes for callback
        axes_list = list(getattr(plot, '_mpl_axes_list', []))

        # Align slider horizontally with the primary axes
        if axes_list:
            main_ax = axes_list[0]
            # get positions: [x0, y0, width, height]
            mx0, my0, mwidth, mheight = main_ax.get_position().bounds
            sx0, sy0, swidth, sheight = slider_ax.get_position().bounds
            # keep slider's y0 and height, but adopt main_ax's x0 and width
            slider_ax.set_position([mx0, sy0, mwidth, sheight])

        # connect change handler
        plot.slider.on_changed(
            lambda v, t=times, lbl=current_label, axlist=axes_list:
            self._on_slider_change(plot, t, lbl, v, axes_list)
        )

        # remember this slider for shared‐axis sync
        self._slider_plots.append(plot)

        # begin added for persisting red range on focus/unfocus
        if self.canvas.shared_x_axis:
            x_axis = plot.axes[0]
            if isinstance(x_axis, RangeAxis) and x_axis.begin is not None and x_axis.end is not None:
                self.update_slider_limits(plot, x_axis.begin, x_axis.end)

        slider_bounds = slider_ax.get_position().bounds
        if axes_list:
            main_ax_bounds = axes_list[0].get_position().bounds

        # mark as initialized so _remove_existing_slider will act correctly next time
        plot._slider_initialized = True

    # Slider updater!
    def _on_slider_change(self, plot, times, label, val, axes_list):
        """Handle slider movement and update both real and pseudo crosshairs."""
        # Prevent re-entry into this handler
        if getattr(plot, "_in_slider_update", False):
            return
        plot._in_slider_update = True

        try:
            # 1) Redraw this plot's signals
            for signal in sum(plot.signals.values(), []):
                self.process_ipl_signal(signal)

            # 2) Propagate to other sliders if Shared Time is active
            if self.canvas.shared_x_axis:
                for other in self._slider_plots:
                    if other is not plot and getattr(other, "slider", None):
                        if other.slider.val != val:
                            other.slider.set_val(val)
                        other.slider_last_val = val

            # 3) Restore user zoom, etc
            primary_ax = axes_list[0]
            try:
                x0, x1 = plot.axes[0].begin, plot.axes[0].end
                if x0 is not None and x1 is not None:
                    primary_ax.set_xlim(x0, x1)
                    self.update_multi_range_axis(plot.axes[1], 1, primary_ax)
            except Exception:
                pass

            # 4) Update timestamp label on the slider itself
            ts = pandas.Timestamp(times[int(val)])
            fmt = NanosecondDateFormatter(ax_idx=0)
            label.set_text(fmt.date_fmt(ts.value, fmt.cut_start + 3, fmt.NANOSECOND, postfix_end=True))
            plot.slider_last_val = val

            x_num = mdates.date2num(ts.round('us').to_pydatetime())

        finally:
            plot._in_slider_update = False

    def _connect_limit_callbacks(self, mpl_axes):
        """Attach xlim_changed to synchronize shared axes (except streaming mode)."""
        if not self.canvas.streaming:
            for ax in mpl_axes.get_shared_x_axes().get_siblings(mpl_axes):
                ax.callbacks.connect('xlim_changed', self._axis_update_callback)

    def _axis_update_callback(self, mpl_axes):

        affected_axes = mpl_axes.get_shared_x_axes().get_siblings(mpl_axes)
        if self.canvas.shared_x_axis and not self.canvas.undo_redo:
            other_axes = self._get_all_shared_axes(mpl_axes)
            for other_axis in other_axes:
                cur_x_limits = self.get_oaw_axis_limits(mpl_axes, 0)
                other_x_limits = self.get_oaw_axis_limits(other_axis, 0)
                if cur_x_limits[0] != other_x_limits[0] or cur_x_limits[1] != other_x_limits[1]:
                    # In case of PlotXYWithSlider, update the slider limits
                    ci = self._impl_plot_cache_table.get_cache_item(other_axis)
                    if not hasattr(ci, 'plot'):
                        continue
                    if isinstance(ci.plot(), PlotXYWithSlider):
                        self.update_slider_limits(ci.plot(), *cur_x_limits)
                    else:
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
            if isinstance(ci.plot(), PlotXYWithSlider):
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

        # Once all the normal x-limits sync has run, we also force-clamp every slider
        if self.canvas.shared_x_axis:
            # Iterate over every PlotXYWithSlider we track
            for slider_plot in self._slider_plots:
                # Get the current zoom on the corresponding RangeAxis
                x_begin, x_end = slider_plot.axes[0].begin, slider_plot.axes[0].end
                if x_begin is None or x_end is None:
                    continue
                # Clamp and redraw the red highlight span
                self.update_slider_limits(slider_plot, x_begin, x_end)
            # Finally, trigger a redraw so the red spans actually se vean
            self.figure.canvas.draw_idle()


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
        mpl_axes = self._signal_impl_plot_lut.get(signal.uid)  # type: MPLAxes
        if not isinstance(mpl_axes, MPLAxes):
            return

        # draw the line data
        signal_data = signal.get_data()
        data = self.transform_data(mpl_axes, signal_data)
        if hasattr(signal, 'envelope') and signal.envelope:
            self.do_mpl_envelope_plot(signal, mpl_axes, *data)
        else:
            self.do_mpl_line_plot(signal, mpl_axes, data)

        # apply axis labels
        self.update_axis_labels_with_units(mpl_axes, signal)

        # remove only previous marker annotations, not other slider/cursor elements
        for ann in mpl_axes.texts:
            if getattr(ann, "_is_marker_annotation", False):
                ann.remove()

        # draw markers if any, regardless of line count
        for marker in signal.markers_list:
            if marker.visible:
                existing = [child.get_text() for child in mpl_axes.get_children()
                            if isinstance(child, plt.Annotation)]
                if marker.name not in existing:
                    x = self.transform_value(mpl_axes, 0, marker.xy[0], inverse=True)
                    y = marker.xy[1]
                    annot = mpl_axes.annotate(
                        text=marker.name,
                        xy=(x, y), xytext=(x, y),
                        bbox=dict(boxstyle="round,pad=0.3", edgecolor="black", facecolor=marker.color)
                    )
                    annot._is_marker_annotation = True

    def autoscale_y_axis(self, impl_plot, margin=0.1):
        """This function rescales the y-axis based on the data that is visible given the current xlim of the axis."""

        def get_bottom_top(x_line):
            # Convert data to numpy arrays to support boolean masking
            xd = np.asarray(x_line.get_xdata())
            yd = np.asarray(x_line.get_ydata())
            lo, hi = impl_plot.get_xlim()
            # Create mask for points within current x limits
            mask = (xd > lo) & (xd < hi)
            # Filter y values using mask
            y_displayed = yd[mask] if mask.any() else np.array([])
            if y_displayed.size > 0:
                # Remove NaN values
                y_clean = y_displayed[~np.isnan(y_displayed)]
                # Compute padded bounds
                height = np.max(y_clean) - np.min(y_clean)
                return np.min(y_clean) - margin * height, np.max(y_clean) + margin * height
            else:
                # Default bounds when no data in view
                return 0, 1

        # Gather all visible data lines except crosshair artifacts
        lines = impl_plot.get_lines()
        lines = [ln for ln in lines if ln.get_label() not in ["CrossX", "CrossY"]]

        bot, top = np.inf, -np.inf
        # Compute overall min/max across all lines
        for line in lines:
            new_bot, new_top = get_bottom_top(line)
            bot, top = min(bot, new_bot), max(top, new_top)

        # Apply the new limits if any lines exist
        if lines:
            self.set_oaw_axis_limits(impl_plot, 1, (bot, top))

    def set_impl_plot_slider_limits(self, plot, start, end):
        """
        Update the slider's min/max bounds and its annotations.
        Also re-set the slider position AND trigger redraw.
        """
        slider = getattr(plot, 'slider', None)
        if slider is None:
            return

        slider.valmin = start
        slider.valmax = end

        # Clamp and update the current value
        val = int(plot.slider_last_val or 0)
        val = max(start, min(val, end))
        plot.slider_last_val = val

        # Prevent recursive update during set_val
        plot._in_slider_update = True
        try:
            slider.set_val(val)
        finally:
            plot._in_slider_update = False

        # Update min/current/max timestamp annotations
        annotations = [label for label in slider.ax.get_children()
                       if isinstance(label, plt.Annotation)]
        if len(annotations) >= 3:
            ts_array = plot.signals[1][0].z_data
            annotations[0].set_text(f'{pandas.Timestamp(ts_array[start])}')
            annotations[1].set_text(f'{pandas.Timestamp(ts_array[val])}')
            annotations[2].set_text(f'{pandas.Timestamp(ts_array[end])}')

        # Remove old red lines
        for child in slider.ax.lines:
            if child.get_color() == 'red':
                child.remove()

        # Draw a single vertical red line at current slider value
        slider.ax.axvline(val, color='red', linewidth=1.5)

        # Force full signal redraw using current slider state
        if hasattr(plot, '_mpl_axes_list') and plot._mpl_axes_list:
            label = annotations[1]
            axes_list = plot._mpl_axes_list
            times = plot.signals[1][0].z_data
            self._on_slider_change(plot, times, label, val, axes_list)

    def update_slider_limits(self, plot, begin, end):
        """
        Update the slider's minimum and maximum values and create a red rectangle
        to indicate the zoomed time range.
        """
        # Prevent recursive re-entry
        if getattr(plot, "_updating_range", False):
            return
        plot._updating_range = True

        try:
            # If timestamp values are large (nanoseconds)
            if bool(begin > (1 << 53)):
                # Find the index range matching the new begin and end values
                new_start = np.searchsorted(plot.signals[1][0].z_data, begin)
                new_end = np.searchsorted(plot.signals[1][0].z_data, end)

                # Clamp indices within the valid range
                new_start = max(0, min(new_start, len(plot.signals[1][0].z_data) - 1))
                new_end = max(0, min(new_end, len(plot.signals[1][0].z_data) - 1))

                # Set slider range limits
                plot.slider.valmin = new_start
                plot.slider.valmax = new_end

                # Clamp current value if outside limits
                val = int(plot.slider.val)
                if val < new_start:
                    val = new_start
                elif val > new_end:
                    val = new_end
                plot.slider_last_val = val

                # Temporarily prevent slider event firing
                plot._in_slider_update = True
                try:
                    plot.slider.set_val(val)  # Move slider to clamped value
                finally:
                    plot._in_slider_update = False

                # Update the min/current/max timestamp annotations
                annotations = [
                    label for label in plot.slider.ax.get_children()
                    if isinstance(label, plt.Annotation)
                ]
                if len(annotations) >= 3:
                    min_annotation, current_annotation, max_annotation = annotations[:3]
                    min_annotation.set_text(f'{pandas.Timestamp(plot.signals[1][0].z_data[new_start])}')
                    current_annotation.set_text(f'{pandas.Timestamp(plot.signals[1][0].z_data[val])}')
                    max_annotation.set_text(f'{pandas.Timestamp(plot.signals[1][0].z_data[new_end])}')

                # Remove old red patches (if any)
                for child in plot.slider.ax.get_children():
                    if isinstance(child, Patch) and getattr(child, "get_label", lambda: None)() == 'slider_red_range':
                        child.remove()

                # Set x-limits explicitly in slider axis
                plot.slider.ax.set_xmargin(0)
                plot.slider.ax.set_xlim(0, len(plot.signals[1][0].z_data) - 1)

                # Draw the red highlight area with higher zorder
                plot.slider.ax.axvspan(
                    float(new_start), float(new_end),
                    color='red', alpha=0.3, label='slider_red_range', zorder=6)

                # Final redraw to make sure patch appears
                plot.slider.ax.figure.canvas.draw_idle()

        finally:
            # Restore flag to allow future updates
            plot._updating_range = False

    def update_slider_limits_undo_redo(self):
        pass

    def enable_tight_layout(self):
        self.figure.set_layout_engine("tight")

    def disable_tight_layout(self):
        self.figure.set_layout_engine("constrained")

    def set_focus_plot(self, mpl_axes):
        """
        Handle focus/unfocus transitions for slider synchronization,
        ensuring the red zoomed slider range persists across redraws.
        """

        # Identify the new focus target
        new_plot, new_key = None, None
        if isinstance(mpl_axes, MPLAxes):
            ci = self._impl_plot_cache_table.get_cache_item(mpl_axes)
            new_plot, new_key = ci.plot(), ci.stack_key

        # Store red zone limits before redraw
        red_zones = {}
        if self.canvas.shared_x_axis:
            for plot in self._slider_plots:
                x_axis = plot.axes[0]
                if isinstance(x_axis, RangeAxis) and x_axis.begin is not None and x_axis.end is not None:
                    red_zones[id(plot)] = (x_axis.begin, x_axis.end)

        # If unfocusing, propagate current slider value to all other sliders
        if self._focus_plot is not None and new_plot is None and self.canvas.shared_x_axis:
            last_val = getattr(self._focus_plot, 'slider_last_val', None)
            if last_val is not None:
                for other in self._slider_plots:
                    if other is not self._focus_plot and getattr(other, 'slider', None):
                        other.slider.set_val(last_val)
                        other.slider_last_val = last_val

                        # Actualizar etiqueta de timestamp
                        annotations = [
                            child for child in other.slider.ax.get_children()
                            if isinstance(child, Annotation)
                        ]
                        if len(annotations) >= 3:
                            timestamps = other.signals[1][0].z_data
                            annotations[1].set_text(str(pandas.Timestamp(timestamps[last_val])))

        # Reset slider init flag to force full redraw
        for slider_plot in self._slider_plots:
            slider_plot._slider_initialized = False

        # Redraw using superclass logic
        super().set_focus_plot(mpl_axes)
        self._focus_plot = new_plot
        self._focus_plot_stack_key = new_key

        # Re-apply red zones safely after sliders are recreated
        self.reapply_red_zones(red_zones)

    def reapply_red_zones(self, red_zones: dict):
        """
        Reapply red highlight zones directly after sliders are recreated.
        This avoids relying on draw_event, which may be too early or too late.
        """
        if not self.canvas.shared_x_axis:
            return

        for plot in self._slider_plots:
            if id(plot) in red_zones:
                begin, end = red_zones[id(plot)]
                self.update_slider_limits(plot, begin, end)

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

            # Exclude slider axes
            filtered_axes_group = [ax for ax in axes_group if ax.get_label() != "slider"]

            self._cursors.append(
                IplotMultiCursor(self.figure.canvas, filtered_axes_group,
                                 x_label=self.canvas.enable_x_label_crosshair,
                                 y_label=self.canvas.enable_y_label_crosshair,
                                 val_label=self.canvas.enable_val_label_crosshair,
                                 color=self.canvas.crosshair_color,
                                 lw=self.canvas.crosshair_line_width,
                                 horiz_on=False or self.canvas.crosshair_horizontal,
                                 vert_on=self.canvas.crosshair_vertical,
                                 use_blit=True,
                                 cache_table=self._impl_plot_cache_table,
                                 slider=False))

    @BackendParserBase.run_in_one_thread
    def activate_cursor_slider(self):
        if self.canvas.shared_x_axis:
            axes = self.figure.axes
            for ax in axes:
                ci = self._impl_plot_cache_table.get_cache_item(ax)
                if not hasattr(ci, 'plot'):
                    continue
                plt = ci.plot()
                if isinstance(plt, PlotXYWithSlider):
                    other_axes = self._get_all_shared_axes(ax, True) or []
                    # Solo eliminamos si está
                    if ax in other_axes:
                        other_axes.remove(ax)
                    # Solo si hay ejes válidos
                    if other_axes:
                        self._cursors.append(
                            IplotMultiCursor(self.figure.canvas, other_axes,
                                             x_label=self.canvas.enable_x_label_crosshair,
                                             y_label=False,
                                             val_label=False,
                                             color=self.canvas.crosshair_color,
                                             lw=self.canvas.crosshair_line_width,
                                             horiz_on=False,
                                             vert_on=self.canvas.crosshair_vertical,
                                             use_blit=True,
                                             cache_table=self._impl_plot_cache_table,
                                             slider=True))
                else:
                    continue

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

    def add_marker_scaled(self, mpl_axes: MPLAxes, plot: PlotXY, x_coord, y_coord):
        """
        Function that returns the nearest point of the plot to create the corresponding marker.
        As the scale of the axes is very different, a normalization of the data is done to adjust the data to a
        common scale.
        """

        ranges = []
        marker_signal = None
        nearest_point = None
        minor_dist = float('inf')

        for ax_idx, ax in enumerate(plot.axes):
            if isinstance(ax, RangeAxis):
                ranges = ax.get_limits()

        # With the new X axis limits, we obtain the points within that range
        for stack in plot.signals.values():
            for signal in stack:
                idx1 = np.searchsorted(signal.x_data, ranges[0])
                idx2 = np.searchsorted(signal.x_data, ranges[1])

                x_zoom = signal.data_store[0][idx1:idx2]
                y_zoom = signal.data_store[1][idx1:idx2]

                # If the number of samples per signal is less than 50 we continue, if not the user shall keep zooming
                if len(x_zoom) > 50:
                    return None, len(x_zoom)

                # Get the points (x,y) for each signal
                points = list(zip(x_zoom, y_zoom))

                # Normalization of the points
                x_min, x_max = min(x_zoom), max(x_zoom)
                y_min, y_max = min(y_zoom), max(y_zoom)

                x_range = x_max - x_min if x_max != x_min else 1
                y_range = y_max - y_min if y_max != y_min else 1
                scaled_points = [((px - x_min) / x_range, (py - y_min) / y_range) for px, py in points]

                # Normalization of the coordinates where the user clicked
                x_coord_transform = self.transform_value(mpl_axes, 0, x_coord)
                scaled_x = (x_coord_transform - x_min) / x_range
                scaled_y = (y_coord - y_min) / y_range

                # Get the nearest point using the Euclidian distance
                distances = [np.sqrt((px - scaled_x) ** 2 + (py - scaled_y) ** 2) for px, py in scaled_points]
                idx_result = np.argmin(distances)

                if distances[idx_result] < minor_dist:
                    minor_dist = distances[idx_result]
                    nearest_point = points[idx_result]
                    marker_signal = signal

        return nearest_point, marker_signal

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
