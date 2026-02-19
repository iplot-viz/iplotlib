# Changelog:
#   Jan 2023:   -Added support for legend position and layout [Alberto Luengo]
from datetime import datetime
from typing import Any, Callable, Collection, List
import pandas
import gc
import numpy as np
import matplotlib as mpl
from matplotlib.axes import Axes as MPLAxes
from matplotlib.axis import Tick, YAxis
from matplotlib.axis import Axis as MPLAxis
from matplotlib.patches import Patch
from matplotlib.contour import QuadContourSet
from matplotlib.figure import Figure
from matplotlib.gridspec import GridSpecFromSubplotSpec, SubplotSpec
from matplotlib.lines import Line2D
from matplotlib.ticker import MaxNLocator, LogLocator
from matplotlib.widgets import Slider
import matplotlib.pyplot as plt
from mpl_toolkits.axes_grid1 import make_axes_locatable
from pandas.plotting import register_matplotlib_converters

from iplotLogging import setupLogger
from iplotlib.core import (Axis,
                           RangeAxis,
                           Canvas,
                           BackendParserBase,
                           Plot,
                           PlotXY,
                           PlotContour,
                           PlotXYWithSlider,
                           PlotContourWithSlider,
                           PlotImage,
                           Signal,
                           SignalXY,
                           SignalContour)
from iplotlib.impl.matplotlib.dateFormatter import NanosecondDateFormatter
from iplotlib.impl.matplotlib.iplotMultiCursor import IplotMultiCursor

logger = setupLogger.get_logger(__name__)

STEP_MAP = {"linear": "default", "mid": "steps-mid", "post": "steps-post", "pre": "steps-pre",
            "default": None, "steps-mid": "mid", "steps-post": "post", "steps-pre": "pre"}


# mpl.rcParams['path.simplify'] = True
# mpl.rcParams['path.simplify_threshold'] = 1.0


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

    def legend_downsampled_signal(self, signal, mpl_axes: MPLAxes, plot_lines: Line2D):
        """
        Add or removes a '*' in the legend label to indicate if the signal is downsampled or not
        """
        legend = mpl_axes.get_legend()
        if legend is None:
            return

        # Filter out '_child' lines from mpl_axes, which are added in envelope plots
        # These lines should not be considered when matching lines to legend entries
        valid_lines = [line for line in mpl_axes.get_lines() if not line.get_label().startswith("_child")]
        pos = valid_lines.index(plot_lines)
        legend_label = legend.get_texts()[pos]
        legend_text = legend.get_texts()[pos].get_text()

        if legend_text.endswith('*') and not signal.isDownsampled:
            legend_label.set_text(legend_text[:-1])
        elif not legend_text.endswith('*') and signal.isDownsampled:
            legend_label.set_text(legend_text + '*')

    @staticmethod
    def _update_marker_by_point_count(marker_line: Line2D, signal_x_data, signal_style: dict):
        if len(signal_x_data) == 1:
            marker_line.set_marker('x')
            marker_line.set_markersize(5)
        else:
            marker_line.set_marker(signal_style.get('marker') or "")
            marker_line.set_markersize(signal_style.get('markersize'))

    def visible_status(self, plot_lines, signal):
        self.figure.canvas.draw_idle()

        # Preserve visible status for lines
        for new, old in zip(plot_lines, signal.lines):
            # for n, o in zip(new, old):
            new.set_visible(old.get_visible())

    def do_impl_streaming(self, impl_plot: MPLAxes, plot: Plot, cache_item):
        """
        Updates the X and Y view ranges of the Axes based on the most recent data received from the Streaming
        """
        ax_window = impl_plot.get_xlim()[1] - impl_plot.get_xlim()[0]

        # Time window
        now = int(datetime.now().timestamp() * 1e9)
        min_time = now - int(ax_window)

        all_y_data = []
        for signal_ref in cache_item.signals:
            signal = signal_ref()
            if signal.lines[0].get_visible() and len(signal.x_data) > 0:
                mask = (signal.x_data >= min_time) & (signal.x_data <= now)
                all_y_data.extend(signal.y_data[mask])

        if all_y_data:
            y_max = np.nanmax(all_y_data).item()
            y_min = np.nanmin(all_y_data).item()
            if y_max == y_min:
                diff = y_max * 0.05
            else:
                diff = (y_max - y_min) * 0.1
            impl_plot.set_ylim(y_min - diff, y_max + diff)

        begin = self.transform_value(impl_plot, 0, min_time, inverse=True)
        end = self.transform_value(impl_plot, 0, now, inverse=True)
        impl_plot.set_xlim(begin, end)

    def set_line_data(self, line: Line2D, x_data, y_data):
        """
        Set the data for a Line2D
        """
        line.set_xdata(x=x_data)
        line.set_ydata(y=y_data)

    def create_plot_lines_1D(self, draw_fn, x_data, y_data, style):
        return draw_fn(x_data, y_data, **style)

    def create_plot_lines_2D(self, draw_fn, signal, x_data, y_data, style):
        plot = signal.parent()
        plot_lines = []
        for i in range(y_data.shape[1]):
            style_i = dict(**style)
            if hasattr(plot, "get_next_color"):
                style_i['color'] = plot.get_next_color()
            else:
                style_i['color'] = PlotXY._color_cycle[i % len(PlotXY._color_cycle)]
            line = draw_fn(x_data, y_data[:, i], **style_i)  # List[Line2D]
            line[0].set_label(f"{signal.label}[{i}]")
            self._update_marker_by_point_count(line[0], x_data, style)
            plot_lines.append(line[0])

        return plot_lines

    def get_ysub_data(self, plot: PlotXYWithSlider, y_data):
        return y_data[plot.slider.val]

    def create_slider_plot_lines_1D(self, draw_fn, x_data, ysub_data, style) -> List[Line2D]:
        return draw_fn(x_data, ysub_data, **style)

    def create_slider_plot_lines_2D(self, draw_fn, x_data, ysub_data, style):
        pass
        # lines = draw_fn(x_data, ysub_data, **style)
        # plot_lines = [[line] for line in lines]
        # for i, line in enumerate(plot_lines):
        #     line[0].set_label(f"{signal.label}[{i}]")
        #
        # return plot_lines

    def slider_visible_status(self, plot_lines, signal):
        for new, old in zip(plot_lines, signal.lines):
            # for n, o in zip(new, old):
            new.set_visible(old.get_visible())

    def set_image_limits(self, ax_idx, signal, impl_plot: MPLAxes):
        data = np.arange(0, len(signal.x_data)).astype(float)
        data[0] -= 0.5
        data[-1] += 0.5

        return data

    def create_image(self, impl_plot: MPLAxes, plot: PlotImage, cache_item, data):
        interpolation = self._pm.get_value(plot, 'interpolation')
        origin = self._pm.get_value(plot, 'origin')

        img = impl_plot.imshow(data,
                               origin=origin,
                               interpolation=interpolation)  # type: AxesImage

        divider = make_axes_locatable(impl_plot)

        cax = divider.append_axes(
            position='right',
            size='5%',
            pad=0.2
        )

        self.figure.colorbar(img, cax=cax)

        return img

    def do_impl_line_plot_contour(self, signal: SignalContour, mpl_axes: MPLAxes, plot: PlotContour, x_data, y_data,
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

    def do_impl_line_plot_contour_slider(self, signal: SignalContour, mpl_axes: MPLAxes, plot: PlotContourWithSlider,
                                         x_data, y_data, z_data):
        plot_lines = self._signal_impl_shape_lut.get(id(signal))  # type: QuadContourSet

        xsub_data = x_data[plot.slider.val]
        ysub_data = y_data[plot.slider.val]
        zsub_data = z_data[plot.slider.val]

        contour_filled = self._pm.get_value(plot, 'contour_filled')
        legend_format = self._pm.get_value(plot, "legend_format")
        equivalent_units = self._pm.get_value(plot, "equivalent_units")
        contour_levels = self._pm.get_value(signal, 'contour_levels')
        color_map = self._pm.get_value(signal, 'color_map')

        if isinstance(plot_lines, QuadContourSet):
            for tp in plot_lines.collections:
                tp.remove()
            """    
            if plot.contour_legend:
                if isinstance(plot.contour_legend, list):
                    for clabel in plot.contour_legend:
                        clabel.remove()
                else:
                    plot.contour_legend.remove()
            """
            if contour_filled:
                draw_fn = mpl_axes.contourf
            else:
                draw_fn = mpl_axes.contour

            if xsub_data.ndim == ysub_data.ndim == zsub_data.ndim == 2:
                plot_lines = draw_fn(xsub_data, ysub_data, zsub_data, levels=contour_levels, cmap=color_map)
                if legend_format == 'in_lines':
                    if not contour_filled:
                        plt.clabel(plot_lines, inline=1, fontsize=10)
                        # plot.contour_legend = clabels
                # else:
                # color_bar = self.figure.colorbar(plot_lines, ax=mpl_axes, location='right')
                # color_bar.set_label(zsub_data.unit, size=self.legend_size)
                # plot.contour_legend = color_bar
            if equivalent_units:
                mpl_axes.set_aspect('equal', adjustable='box')
            self.figure.canvas.draw_idle()
        else:
            if contour_filled:
                draw_fn = mpl_axes.contourf
            else:
                draw_fn = mpl_axes.contour

            if xsub_data.ndim == ysub_data.ndim == zsub_data.ndim == 2:
                plot_lines = draw_fn(xsub_data, ysub_data, zsub_data, levels=contour_levels, cmap=color_map)
                if legend_format == 'color_bar':
                    color_bar = self.figure.colorbar(plot_lines, ax=mpl_axes, location='right')
                    color_bar.set_label(zsub_data.unit, size=self.legend_size)
                    # plot.contour_legend = color_bar
                else:
                    if not contour_filled:
                        plt.clabel(plot_lines, inline=1, fontsize=10)
                        # plot.contour_legend = clabels
            if equivalent_units:
                mpl_axes.set_aspect('equal', adjustable='box')

        return plot_lines

    def update_area_envelope_1D(self, shapes, impl_plot: MPLAxes, x_data, y1_data, y2_data, style):
        shapes[0][2].remove()
        shapes[0][2] = impl_plot.fill_between(x_data, y1_data, y2_data,
                                              alpha=0.3,
                                              color=shapes[0][0].get_color(),
                                              step=STEP_MAP[style['drawstyle']])
        shapes[0][2].set_visible(shapes[0][0].get_visible())
        self.figure.canvas.draw_idle()

    def create_area_envelope_1D(self, draw_fn, impl_plot: Any, signal, x_data, y1_data, y2_data, style, style2):
        line_1 = draw_fn(x_data, y1_data, **style)  # type: List[Line2D]
        signal.color = line_1[0].get_color()
        style2 = dict(style)
        style2.update(color=signal.color, label='')
        line_2 = draw_fn(x_data, y2_data, **style2)  # type: List[Line2D]

        area = impl_plot.fill_between(x_data, y1_data, y2_data,
                                      alpha=0.3,
                                      color=style2['color'],
                                      step=STEP_MAP[style['drawstyle']])

        lines = [line_1 + line_2 + [area]]
        for new, old in zip(lines, signal.lines):
            new.set_visible(old.get_visible())

        return lines

    def clear(self):
        super().clear()

        # remove any active multi‑cursors
        for c in self._cursors:
            c.remove()
        self._cursors.clear()

        # drop cache items and remove each Axes to release all artists and callbacks
        # for ax in list(self.figure.axes):
        #     self.figure.delaxes(ax)
        self.figure.clear()
        if self.canvas:
            for col in self.canvas.plots:
                for plot in col:
                    if not plot:
                        continue
                    for signal in [elem for sublist in plot.signals.values() for elem in sublist]:
                        signal.lines.clear()

        self.map_legend_to_ax.clear()
        self._impl_plot_ranges_hash.clear()

        gc.collect()

    def set_impl_plot_limits(self, impl_plot: Any, ax_idx: int, limits: tuple) -> bool:
        if not isinstance(impl_plot, MPLAxes):
            return False
        self.set_oaw_axis_limits(impl_plot, ax_idx, limits)
        return True

    def get_canvas_plots(self):
        return list(self.figure.axes)

    def set_canvas_gridspec(self, rows: int, cols: int):
        """Set the canvas gridspec to the given rows and columns."""
        self._layout = self.figure.add_gridspec(rows, cols)

    def set_suptitle(self, title: str, font_size: int = None, font_color: str = 'black'):

        self.figure.suptitle(title, fontsize=font_size, color=font_color)

    def process_ipl_plot_xy(self):
        pass

    def process_ipl_plot_contour(self):
        pass

    def process_ipl_plot_xy_slider(self, plot_with_slider: PlotXYWithSlider | PlotContourWithSlider,
                                   grid_item: SubplotSpec, stack_sz: int, h_space: float):
        # Configure slider height and calculate the space for plot
        slider_height = 0.06
        plot_height = 1.0 - slider_height
        heights = [plot_height] * stack_sz + [slider_height]

        # In case of PlotXYWithSlider, create a vertical layout with `stack_sz` + 1 (slider) rows and 1 column
        # inside grid_item
        subgrid_item = grid_item.subgridspec(stack_sz + 1, 1, height_ratios=heights, hspace=h_space)
        sub_subgrid_item = subgrid_item[1, 0].subgridspec(1, 1, hspace=0)

        # Add Slider
        slider_ax = self.figure.add_subplot(sub_subgrid_item[0, 0])
        slider_ax.set_label("slider")

        # Case for PlotContourWithSlider
        if isinstance(plot_with_slider, PlotContourWithSlider):
            # Get data for the slider
            slider_values = plot_with_slider.signals[1][0].time
            min_value = slider_values[0]
            max_value = slider_values[-1]

            formatter = NanosecondDateFormatter(ax_idx=0)
            is_date = bool(min(slider_values) > (1 << 53) and max(slider_values) < (1 << 62))
            if is_date:
                min_value = pandas.Timestamp(min_value).value
                max_value = pandas.Timestamp(max_value).value

                # Format start, current and end timestamps
                # Reduced format for current value and end value
                start_format = formatter.date_fmt(min_value, formatter.YEAR, formatter.NANOSECOND, postfix_end=True)
                current_format = formatter.date_fmt(min_value, formatter.cut_start + 3, formatter.NANOSECOND,
                                                    postfix_end=True)
                end_format = formatter.date_fmt(max_value, formatter.cut_start + 3, formatter.NANOSECOND,
                                                postfix_end=True)
            else:
                start_format = min_value
                current_format = min_value
                end_format = max_value

            # Font size for slider labels
            fs = self._pm.get_value(plot_with_slider, 'font_size')

            # Annotate labels along the slider axis
            slider_ax.annotate(start_format, xy=(0, -0.3), xycoords='axes fraction', ha='left', va='center',
                               fontsize=fs)
            current_label = slider_ax.annotate(current_format, xy=(0.425, -0.3), xycoords='axes fraction', ha='left',
                                               va='center', fontsize=fs)
            slider_ax.annotate(end_format, xy=(0.85, -0.3), xycoords='axes fraction', ha='left', va='center',
                               fontsize=fs)

            # Check if there was a previous plot_with_slider with a value
            if plot_with_slider.slider_last_val is not None:
                value = plot_with_slider.slider_last_val
                if is_date:
                    current_value = pandas.Timestamp(slider_values[int(value)]).value
                    current_label.set_text(
                        formatter.date_fmt(current_value, formatter.cut_start + 3, formatter.NANOSECOND,
                                           postfix_end=True))
                else:
                    current_value = slider_values[int(value)]
                    current_label.set_text(str(current_value))
            else:
                value = 0

            # Maximum index value for the slider based on the y-data length
            val_max = plot_with_slider.signals[1][0].time.shape[0] - 1

            # Slider creation
            plot_with_slider.slider = Slider(slider_ax, '', 0, val_max, valinit=value, valstep=1)
            plot_with_slider.slider.valtext.set_visible(False)  # Hide slider value text

            # Register the callback function to update the plot when the slider value changes
            plot_with_slider.slider.on_changed(
                lambda val: self._update_slider_contour(val, plot_with_slider, slider_values, current_label))

        # Case for PlotXYWithSlider
        else:
            # Get data for the slider
            slider_values = plot_with_slider.signals[1][0].time
            formatter = NanosecondDateFormatter(ax_idx=0)
            is_date = bool(min(slider_values) > (1 << 53) and max(slider_values) < (1 << 62))
            if is_date:
                min_value = pandas.Timestamp(slider_values[0]).value
                max_value = pandas.Timestamp(slider_values[-1]).value

                # Format start, current and end timestamps
                # Reduced format for current value and end value
                start_format = formatter.date_fmt(min_value, formatter.YEAR, formatter.NANOSECOND, postfix_end=True)
                current_format = formatter.date_fmt(min_value, formatter.cut_start + 3, formatter.NANOSECOND,
                                                    postfix_end=True)
                end_format = formatter.date_fmt(max_value, formatter.cut_start + 3, formatter.NANOSECOND,
                                                postfix_end=True)
            else:
                min_value = slider_values[0]
                max_value = slider_values[-1]

                start_format = min_value
                current_format = min_value
                end_format = max_value

            # Font size for slider labels
            fs = self._pm.get_value(plot_with_slider, 'font_size')

            # Annotate labels along the slider axis
            slider_ax.annotate(start_format, xy=(0, -0.3), xycoords='axes fraction', ha='left', va='center',
                               fontsize=fs)
            current_label = slider_ax.annotate(current_format, xy=(0.425, -0.3), xycoords='axes fraction', ha='left',
                                               va='center', fontsize=fs)
            slider_ax.annotate(end_format, xy=(0.85, -0.3), xycoords='axes fraction', ha='left', va='center',
                               fontsize=fs)

            # Check if there was a previous plot_with_slider with a value
            if plot_with_slider.slider_last_val is not None:
                value = plot_with_slider.slider_last_val
                # Update current value label
                if is_date:
                    current_value = pandas.Timestamp(slider_values[int(value)]).value
                    current_label.set_text(
                        formatter.date_fmt(current_value, formatter.cut_start + 3, formatter.NANOSECOND,
                                           postfix_end=True))
                else:
                    current_value = slider_values[int(value)]
                    current_label.set_text(str(current_value))
            else:
                value = 0
                plot_with_slider.slider_last_val = value

            # Maximum index value for the slider based on the y-data length
            val_max = plot_with_slider.signals[1][0].y_data.shape[0] - 1

            # Slider creation
            plot_with_slider.slider = Slider(slider_ax, '', 0, val_max, valinit=value, valstep=1)
            plot_with_slider.slider.valtext.set_visible(False)  # Hide slider value text

            # Register the callback function to update the plot when the slider value changes
            plot_with_slider.slider.on_changed(
                lambda val: self._update_slider(val, plot_with_slider, slider_values, current_label, formatter)
            )

            # Check if the PlotXYWithSlider had a previously defined min/max range for the slider
            slider_min = plot_with_slider.slider_last_min
            slider_max = plot_with_slider.slider_last_max

            if slider_min is not None and slider_max is not None:
                # If the minimum and maximum values of a PlotXYWithSlider differ from their original values, it means
                # they were modified due to a zoom action performed on a PlotXY that shares the same shared time.
                # Therefore, when the PlotXYWithSlider is processed again, the red highlighted area should continue
                # to be displayed, provided that the shared time is still active.
                if (slider_min != 0 or slider_max != val_max) and self._pm.get_value(self.canvas, 'shared_x_axis'):
                    # Highlight the selected area in the slider
                    plot_with_slider.slider.ax.axvspan(slider_min, slider_max, color='red', alpha=0.3)

                    # Update the slider range based on previous limits
                    plot_with_slider.slider.valmin = slider_min
                    plot_with_slider.slider.valmax = slider_max

                    # Set current value according to slider limits
                    val = plot_with_slider.slider.val
                    if val < slider_min:
                        val = slider_min
                    elif val > slider_max:
                        val = slider_max

                    plot_with_slider.slider.set_val(val)
                else:
                    plot_with_slider.slider_last_min = 0
                    plot_with_slider.slider_last_max = val_max
            else:
                # Initialize the PlotXYWithSlider range when no previous limits are set
                plot_with_slider.slider_last_min = 0
                plot_with_slider.slider_last_max = val_max

        return subgrid_item

    def get_slider_val(self, plot: PlotXYWithSlider):
        return plot.slider.val

    def process_ipl_plot(self, plot: Plot, column: int, row: int):
        logger.debug(f"process_ipl_plot AA: {self._pm.get_value(self.canvas, 'step')}")
        super().process_ipl_plot(plot, column, row)
        if not isinstance(plot, Plot):
            return

        grid_item = self._layout[row: row + plot.row_span, column: column + plot.col_span]  # type: SubplotSpec
        full_mode_all_stack = self._pm.get_value(self.canvas, 'full_mode_all_stack')

        if not full_mode_all_stack and self._focus_plot_stack_key is not None:
            stack_sz = 1
            h_space = 0.1
        else:
            stack_sz = len(plot.signals.keys())
            h_space = 0.3

        if isinstance(plot, PlotXYWithSlider) or isinstance(plot, PlotContourWithSlider):
            subgrid_item = self.process_ipl_plot_xy_slider(plot, grid_item, stack_sz, h_space)
        else:
            # Create a vertical layout with `stack_sz` rows and 1 column inside grid_item
            subgrid_item = grid_item.subgridspec(stack_sz, 1, hspace=0)  # type: GridSpecFromSubplotSpec

        mpl_axes = None
        for stack_id, key in enumerate(sorted(plot.signals.keys())):
            is_stack_plot_focused = self._focus_plot_stack_key == key

            if full_mode_all_stack or self._focus_plot_stack_key is None or is_stack_plot_focused:
                signals = plot.signals.get(key) or list()

                if not full_mode_all_stack and self._focus_plot_stack_key is not None:
                    row_id = 0
                else:
                    row_id = stack_id

                mpl_axes = self.figure.add_subplot(subgrid_item[row_id, 0])
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
                           (is_stack_plot_focused and not full_mode_all_stack))
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

                # Update properties of the plot axes
                x_axis = None
                for ax_idx in range(len(plot.axes)):
                    if isinstance(plot.axes[ax_idx], Collection):
                        y_axis = plot.axes[ax_idx][stack_id]
                        self.process_ipl_axis(y_axis, ax_idx, plot, mpl_axes)
                    else:
                        x_axis = plot.axes[ax_idx]
                        self.process_ipl_axis(x_axis, ax_idx, plot, mpl_axes)

                for signal in signals:
                    self._signal_impl_plot_lut.update({signal.uid: mpl_axes})
                    self.process_ipl_signal(signal)

                # Show the plot legend if enabled
                show_legend = self._pm.get_value(plot, 'legend')
                if show_legend and mpl_axes.get_lines():  # TODO improve
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

                    fs = self._pm.get_value(plot, 'font_size')  # Font size fot legend lines
                    legend_lines = leg.get_lines()
                    ix_legend = 0
                    for signal in signals:
                        for line in self._signal_impl_shape_lut.get(id(signal)):
                            self.map_legend_to_ax[legend_lines[ix_legend]] = line
                            alpha = 1 if legend_lines[ix_legend].get_visible() else 0.2
                            legend_lines[ix_legend].set_picker(3)
                            legend_lines[ix_legend].set_visible(True)
                            legend_lines[ix_legend].set_alpha(alpha)
                            # Check if signal is downsampled at the start
                            if signal.isDownsampled:
                                legend_label = leg.texts[ix_legend].get_text() + '*'
                                leg.texts[ix_legend].set_text(legend_label)
                            leg.get_texts()[ix_legend].set_fontsize(fs)
                            ix_legend += 1

            # Observe the axis limit change events
            if not self.canvas.streaming:
                mpl_axes.callbacks.connect('xlim_changed', self._x_axis_update_callback)
                mpl_axes.callbacks.connect('ylim_changed', self._y_axis_update_callback)

    def _update_slider(self, val, plot, slider_values, current_label, formatter):
        for c_row in plot.signals.values():
            for c_signal in c_row:
                self.process_ipl_signal(c_signal)

        # Refresh current label value
        is_date = bool(min(slider_values) > (1 << 53) and max(slider_values) < (1 << 62))
        if is_date:
            current_value = pandas.Timestamp(slider_values[int(val)]).value
            current_label.set_text(
                formatter.date_fmt(current_value, formatter.cut_start + 3, formatter.NANOSECOND,
                                   postfix_end=True))
        else:
            current_value = slider_values[int(val)]
            current_label.set_text(str(current_value))

        plot.slider_last_val = val

        if self._pm.get_value(plot, 'sync_slider'):
            return

        if self._pm.get_value(self.canvas, 'shared_x_axis'):
            plot_with_slider_shared = self.get_shared_plot_xy_slider(plot)
            for plot_with_slider in plot_with_slider_shared:
                if not self.canvas.focus_plot:
                    plot_with_slider.sync_slider = True
                    plot_with_slider.slider.set_val(val)
                    plot_with_slider.sync_slider = False
                else:
                    plot_with_slider.slider_last_val = val

    def _update_slider_contour(self, val, plot, slider_values, current_label):
        for c_row in plot.signals.values():
            for c_signal in c_row:
                self.process_ipl_signal(c_signal)

        current_value = slider_values[int(val)]
        current_label.set_text(str(current_value))

        plot.slider_last_val = val

        if self._pm.get_value(plot, 'sync_slider'):
            return

        if self._pm.get_value(self.canvas, 'shared_x_axis'):
            plot_with_slider_shared = self.get_shared_plot_xy_slider(plot)
            for plot_with_slider in plot_with_slider_shared:
                if not self.canvas.focus_plot:
                    plot_with_slider.sync_slider = True
                    plot_with_slider.slider.set_val(val)
                    plot_with_slider.sync_slider = False
                else:
                    plot_with_slider.slider_last_val = val

    def _x_axis_update_callback(self, current_plot: MPLAxes):
        super()._x_axis_update_callback(current_plot)

    def _y_axis_update_callback(self, current_plot: MPLAxes):
        super()._y_axis_update_callback(current_plot)

    def process_ipl_log_axis(self, mpl_axis: MPLAxis, plot: Plot):
        if isinstance(mpl_axis, YAxis):
            log_scale = self._pm.get_value(plot, 'log_scale')
            if log_scale:
                mpl_axis.axes.set_yscale('log')
                # Format for minor ticks
                y_minor = LogLocator(base=10, subs=(1.0,))
                mpl_axis.set_minor_locator(y_minor)

    def process_ipl_axis_params(self, fc, fs, tick_number, axis: Axis, mpl_axis: MPLAxis):
        label_props = dict(color=fc)

        # Set ticks on the top and right axis
        if self._pm.get_value(self.canvas, 'ticks_position'):
            tick_props = dict(color=fc, labelcolor=fc, tick1On=True, tick2On=True, direction='in')
        else:
            tick_props = dict(color=fc, labelcolor=fc, tick1On=True, tick2On=False)

        if fs is not None and fs > 0:
            label_props.update({'fontsize': fs})
            tick_props.update({'labelsize': fs})
        if axis.label is not None:
            mpl_axis.set_label_text(axis.label, **label_props)

        # Font size for UTC label
        mpl_axis.get_offset_text().set_fontsize(fs)

        mpl_axis.set_tick_params(**tick_props)

        # Set number of ticks and labels
        mpl_axis.set_major_locator(MaxNLocator(tick_number))

    def process_ipl_axis_formatter(self, impl_plot: MPLAxes, mpl_axis: MPLAxis, ax_idx: int):
        ci = self._impl_plot_cache_table.get_cache_item(impl_plot)
        mpl_axis.set_major_formatter(NanosecondDateFormatter(ax_idx,
                                                             offset_lut=ci.offsets,
                                                             roundh=self._pm.get_value(self.canvas, 'round_hour')))

    def process_ipl_signal_impl_plot(self, signal: Signal):
        mpl_axes = self._signal_impl_plot_lut.get(signal.uid)  # type: MPLAxes
        if not isinstance(mpl_axes, MPLAxes):
            logger.error(f"MPLAxes not found for signal {signal}. Unexpected error. signal_id: {id(signal)}")
            return
        return mpl_axes

    def process_ipl_signal_annotations(self, signal: Signal, impl_plot: MPLAxes):
        if not isinstance(signal, SignalXY) or isinstance(signal.parent(), PlotImage):
            return

        if impl_plot.get_lines()[0].get_marker() == 'None':
            return

        if signal.markers_list:
            annotations_names = [child.get_text() for child in impl_plot.get_children() if
                                 isinstance(child, plt.Annotation)]
            for marker in signal.markers_list:
                if marker.visible:
                    # Draw marker with correct offset to right display
                    x = self.transform_value(impl_plot, 0, marker.xy[0], inverse=True)
                    y = marker.xy[1]

                    # Create annotation if not present (import case)
                    if marker.name not in annotations_names:
                        impl_plot.annotate(text=marker.name,
                                           xy=(x, y),
                                           xytext=(x, y),
                                           bbox=dict(boxstyle="round,pad=0.3",
                                                     edgecolor="black",
                                                     facecolor=marker.color))
                    else:
                        # Update position if annotation already exists
                        prev_annotation = [child for child in impl_plot.get_children() if isinstance(child,
                                                                                                     plt.Annotation) and child.get_text() == marker.name]  # type: List[plt.Annotation]

                        prev_annotation[0].xy = (x, y)
                        prev_annotation[0].set_position((x, y))

    def get_impl_data(self, line: Line2D):
        return line.get_xdata(), line.get_ydata()

    def get_impl_lines(self, impl_plot: MPLAxes):
        lines = impl_plot.get_lines()
        lines = [line for line in lines if line.get_label() not in ["CrossX", "CrossY"]]
        lo, hi = impl_plot.get_xlim()
        return lines, lo, hi

    def autoscale_y_axis(self, impl_plot: MPLAxes, padding=0.1):
        """
        This function rescales the y-axis based on the data that is visible given the current xlim of the axis.
        ax -- a matplotlib axes object
        padding -- the fraction of the total height of the y-data to pad the upper and lower ylims
        """
        bot, top = super().autoscale_y_axis(impl_plot)

        # Compute final margin
        h = (top - bot)
        n_new_bot = bot - padding * h
        n_new_top = top + padding * h

        # Set new Y axis limits
        self.set_oaw_axis_limits(impl_plot, 1, (n_new_bot, n_new_top))

    def set_impl_plot_slider_limits(self, plot: PlotXYWithSlider, start, end):
        """
            Apply slider limit changes to a PlotXYWithSlider instance (used in UNDO/REDO operations)
        """
        if plot.slider is None:
            return

        # Update internal and actual slider limits
        plot.slider.valmin = plot.slider_last_min = start
        plot.slider.valmax = plot.slider_last_max = end

        # Adjust the current slider value
        val = plot.slider.val
        if val < start:
            val = start
        elif val > end:
            val = end

        plot.slider.set_val(val)

        # Update the annotations labels for the slider limits
        annotations = [label for label in plot.slider.ax.get_children() if isinstance(label, plt.Annotation)]
        min_annotation, current_annotation, max_annotation = annotations[:3]
        slider_values = plot.signals[1][0].z_data
        is_date = bool(min(slider_values) > (1 << 53) and max(slider_values) < (1 << 62))
        if is_date:
            min_annotation.set_text(f'{pandas.Timestamp(slider_values[start])}')
            current_annotation.set_text(f'{pandas.Timestamp(slider_values[val])}')
            max_annotation.set_text(f'{pandas.Timestamp(slider_values[end])}')
        else:
            min_annotation.set_text(f'{slider_values[start]}')
            current_annotation.set_text(f'{slider_values[val]}')
            max_annotation.set_text(f'{slider_values[end]}')

        # Remove any previously highlighted region from the slider axis
        for child in plot.slider.ax.get_children():
            if isinstance(child, Patch) and child.get_facecolor()[:3] == (1.0, 0.0, 0.0):
                child.remove()

        # Highlight the selected area in the slider, avoiding drawing a region if start and end span the full range
        if not (start == 0 and end == plot.signals[1][0].y_data.shape[0] - 1):
            plot.slider.ax.axvspan(start, end, color='red', alpha=0.3)

    def update_slider_limits(self, plot: PlotXYWithSlider, begin, end):
        """
            Updates the slider's minimum and maximum values based on Zoom or Draw with shared time.
            Highlight the selected area in the slider.
        """

        # Convert time-based 'begin' and 'end' values to corresponding indices in z_data
        new_start = np.searchsorted(plot.signals[1][0].z_data, begin)
        new_end = np.searchsorted(plot.signals[1][0].z_data, end)

        # Ensure indices are within the valid range of the signal's time data
        max_len = len(plot.signals[1][0].z_data) - 1
        new_start = max(0, min(new_start, max_len))
        new_end = max(0, min(new_end, max_len))

        # Adjust current slider value
        if plot.slider.val < new_start:
            val = new_start
        elif plot.slider.val > new_end:
            val = new_end
        else:
            val = plot.slider.val

        # Update slider limits
        plot.slider.valmin = plot.slider_last_min = new_start
        plot.slider.valmax = plot.slider_last_max = new_end
        plot.slider.val = val
        plot.slider.set_val(val)

        # Update the annotations labels for the slider limits
        annotations = [label for label in plot.slider.ax.get_children() if isinstance(label, plt.Annotation)]
        min_annotation, current_annotation, max_annotation = annotations[:3]

        slider_values = plot.signals[1][0].z_data
        is_date = bool(min(slider_values) > (1 << 53) and max(slider_values) < (1 << 62))
        if is_date:
            min_annotation.set_text(f'{pandas.Timestamp(slider_values[new_start])}')
            current_annotation.set_text(f'{pandas.Timestamp(slider_values[val])}')
            max_annotation.set_text(f'{pandas.Timestamp(slider_values[new_end])}')
        else:
            min_annotation.set_text(f'{slider_values[new_start]}')
            current_annotation.set_text(f'{slider_values[val]}')
            max_annotation.set_text(f'{slider_values[new_end]}')

        # Remove any previously highlighted region from the slider axis
        for child in plot.slider.ax.get_children():
            if isinstance(child, Patch) and child.get_facecolor()[:3] == (1.0, 0.0, 0.0):
                child.remove()

        # Highlight the selected area in the slider, avoiding drawing a region if start and end span the full range
        if plot.slider_last_min != 0 or plot.slider_last_max != max_len:
            plot.slider.ax.axvspan(new_start, new_end, color='red', alpha=0.3)

    def enable_tight_layout(self):
        self.figure.set_tight_layout("True")

    def disable_tight_layout(self):
        self.figure.set_tight_layout("")

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
            if self._pm.get_value(self.canvas, 'shared_x_axis') and len(self._focus_plot.axes) > 0 and isinstance(
                    self._focus_plot.axes[0], RangeAxis):
                begin, end = get_x_axis_range(self._focus_plot)

                for columns in self.canvas.plots:
                    for plot_temp in columns:
                        if plot_temp and not isinstance(self._focus_plot,
                                                        PlotXYWithSlider) and plot_temp != self._focus_plot and not isinstance(plot_temp, (PlotXYWithSlider, PlotContourWithSlider)):
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

            # Check for slider axes
            filtered_axes_group = [ax for ax in axes_group if ax.get_label() != "slider"]

            self._cursors.append(
                IplotMultiCursor(self.figure.canvas, filtered_axes_group,
                                 x_label=self._pm.get_value(self.canvas, 'enable_x_label_crosshair'),
                                 y_label=self._pm.get_value(self.canvas, 'enable_y_label_crosshair'),
                                 val_label=self._pm.get_value(self.canvas, 'enable_val_label_crosshair'),
                                 color=self._pm.get_value(self.canvas, 'crosshair_color'),
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
        if style['marker'] == 'None':
            style['marker'] = None
        style['markersize'] = self._pm.get_value(signal, 'marker_size')
        step = self._pm.get_value(signal, 'step')
        if step is None:
            step = 'linear'
        style["drawstyle"] = STEP_MAP[step]

        return style

    def get_line_label(self, line: Line2D):
        return line.get_label()

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

    def set_impl_x_axis_limits(self, impl_plot: MPLAxes, limits: tuple):
        if isinstance(impl_plot, MPLAxes):
            impl_plot.set_xlim(limits[0], limits[1])

    def set_impl_y_axis_limits(self, impl_plot: MPLAxes, limits: tuple):
        if isinstance(impl_plot, MPLAxes):
            impl_plot.set_ylim(limits[0], limits[1])
        else:
            return None

    def set_impl_x_axis_label_text(self, impl_plot: MPLAxes, text: str):
        ci = self._impl_plot_cache_table.get_cache_item(impl_plot)
        i_plot = ci.plot() if ci else None
        fc = self._pm.get_value(i_plot, 'font_color') if i_plot else None
        fs = self._pm.get_value(i_plot, 'font_size') if i_plot else None
        label_props = {}
        if fc:
            label_props['color'] = fc
        if fs and fs > 0:
            label_props['fontsize'] = fs
        self.get_impl_x_axis(impl_plot).set_label_text(text, **label_props)

    def set_impl_y_axis_label_text(self, impl_plot: Any, text: str):
        if not isinstance(impl_plot, MPLAxes):
            return
        ci = self._impl_plot_cache_table.get_cache_item(impl_plot)
        i_plot = ci.plot() if ci else None
        fc = self._pm.get_value(i_plot, 'font_color') if i_plot else None
        fs = self._pm.get_value(i_plot, 'font_size') if i_plot else None
        label_props = {}
        if fc:
            label_props['color'] = fc
        if fs and fs > 0:
            label_props['fontsize'] = fs
        self.get_impl_y_axis(impl_plot).set_label_text(text, **label_props)

    def transform_value(self, impl_plot: Any, ax_idx: int, value: Any, inverse=False):
        """Adds or subtracts axis offset from value trying to preserve type of offset (ex: does not convert to
        float when offset is int)"""
        return self._impl_plot_cache_table.transform_value(impl_plot, ax_idx, value, inverse=inverse)


def get_data_range(data, axis_idx):
    """Returns first and last value from data[axis_idx] or None"""
    if data is not None and len(data) > axis_idx and len(data[axis_idx] > 0):
        return data[axis_idx][0], data[axis_idx][-1]
    return None
