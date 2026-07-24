# Changelog:
#   Jan 2023:   -Added support for legend position and layout [Alberto Luengo]
from datetime import datetime
from typing import Any, Callable, Collection, Dict, List
import pandas
import gc
import numpy as np
import matplotlib as mpl
import matplotlib.style as mplstyle
from matplotlib.axes import Axes as MPLAxes
from matplotlib.axis import Tick, YAxis, XAxis
from matplotlib.axis import Axis as MPLAxis
from matplotlib.patches import Patch
from matplotlib.contour import QuadContourSet
from matplotlib.figure import Figure
from matplotlib.gridspec import GridSpecFromSubplotSpec, SubplotSpec
from matplotlib.lines import Line2D
from matplotlib.ticker import MaxNLocator
from matplotlib.widgets import Slider
import matplotlib.pyplot as plt
from mpl_toolkits.axes_grid1 import make_axes_locatable
from pandas.plotting import register_matplotlib_converters

from iplotLogging import setupLogger
from iplotlib.core.decimation import minmax_decimate
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
from iplotlib.impl.matplotlib.dateFormatter import NanosecondDateFormatter, ExponentScalarFormatter, \
    NiceNanosecondLocator, RelativeTimeLocator, is_time_label
from iplotlib.impl.matplotlib.iplotMultiCursor import IplotMultiCursor, get_values_from_line
from iplotlib.impl.matplotlib.iplotMplRuler import iplotMplRuler

logger = setupLogger.get_logger(__name__)

STEP_MAP = {"linear": "default", "mid": "steps-mid", "post": "steps-post", "pre": "steps-pre",
            "default": None, "steps-mid": "mid", "steps-post": "post", "steps-pre": "pre"}


# Performance defaults for dense line plots (path.simplify, simplify_threshold, chunksize).
mplstyle.use('fast')

# Above this point count, streamed lines are rendered via per-bucket min/max
# decimation so the visible line preserves extremes at viewport resolution.
_STREAM_DECIMATE_THRESHOLD = 4000
_STREAM_DECIMATE_TARGET_PAIRS = 2000


class MatplotlibParser(BackendParserBase):
    def __init__(self,
                 canvas: Canvas = None,
                 tight_layout: bool = True,
                 focus_plot=None,
                 focus_plot_stack_key=None,
                 impl_flush_method: Callable = None) -> None:
        """Initialize underlying matplotlib classes.
        """
        # Initialize before super().__init__() because it calls clear() via process_ipl_canvas
        self._tight_layout_requested = tight_layout
        self.map_legend_to_ax = {}
        self._legend_signal_lut = {}  # legend_line -> Signal
        self.legend_size = 8
        self._cursors = []
        self._rulers = []  # type: List[iplotMplRuler]
        self._grid_spacing_annotations = {}  # MPLAxes -> Text artist
        self._impl_plot_ranges_hash = dict()

        super().__init__(canvas=canvas, focus_plot=focus_plot, focus_plot_stack_key=focus_plot_stack_key,
                         impl_flush_method=impl_flush_method)

        register_matplotlib_converters()
        self.figure = Figure()

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
        if kwargs.get('autoscale', False):
            # Force an 'Autoscale All' on the exported image only (CLI export option).
            self.autoscale_all_plots()
        self.figure.savefig(filename)

    def legend_downsampled_signal(self, signal, mpl_axes: MPLAxes, plot_lines: Line2D):
        """
        Add or removes a '*' in the legend label to indicate if the signal is downsampled or not
        """
        legend = mpl_axes.get_legend()
        if legend is None:
            return

        # Only signal lines map to legend entries. Exclude envelope ('_child') and
        # ruler ('_RulerLine') helper lines, which would shift the index; a freshly
        # re-plotted line may be briefly absent, so guard the lookup.
        valid_lines = [line for line in mpl_axes.get_lines()
                       if not line.get_label().startswith(("_child", "_RulerLine"))]
        if plot_lines not in valid_lines:
            # The cached line does not belong to these axes (e.g. stale cache after
            # a rebuild). Skip the legend update rather than aborting the caller —
            # an exception here used to leave the shared-x sync half-applied.
            logger.warning(f"legend_downsampled_signal: line for signal {signal.label} not found on axes; skipping")
            return
        pos = valid_lines.index(plot_lines)
        legend_label = legend.get_texts()[pos]
        legend_text = legend.get_texts()[pos].get_text()

        if legend_text.endswith('*') and not signal.isDownsampled:
            legend_label.set_text(legend_text[:-1])
        elif not legend_text.endswith('*') and signal.isDownsampled:
            legend_label.set_text(legend_text + '*')

    def set_signal_visible(self, signal, visible: bool):
        """Set visibility of signal lines."""
        if hasattr(signal, 'lines') and signal.lines:
            for line in signal.lines:
                line.set_visible(visible)

    def remove_signal_lines(self, signal):
        """Remove signal lines from the plot."""
        if hasattr(signal, 'lines') and signal.lines:
            for line in signal.lines:
                line.remove()

    @staticmethod
    def _format_spacing(s, is_date=False):
        """Format tick spacing as a human-readable string (oscilloscope style)."""
        s = abs(s)
        if s == 0:
            return ""
        if is_date:
            # Snap to nearest integer unit if within 20% tolerance
            units = [(86400e9, "D"), (3600e9, "h"), (60e9, "min"), (1e9, "s"), (1e6, "ms"), (1e3, "μs"), (1, "ns")]
            for unit_ns, unit_name in units:
                if s >= unit_ns * 0.8:
                    val = s / unit_ns
                    rounded = round(val)
                    if rounded > 0 and abs(val - rounded) / rounded < 0.2:
                        val = rounded
                    return f"{val:.3g}{unit_name}/div"
            return f"{s:.3g}ns/div"
        else:
            if s >= 1e9:
                return f"{s / 1e9:.3g}G/div"
            elif s >= 1e6:
                return f"{s / 1e6:.3g}M/div"
            elif s >= 1e3:
                return f"{s / 1e3:.3g}k/div"
            elif s >= 1:
                return f"{s:.3g}/div"
            elif s >= 1e-3:
                return f"{s * 1e3:.3g}m/div"
            elif s >= 1e-6:
                return f"{s * 1e6:.3g}μ/div"
            else:
                return f"{s * 1e9:.3g}n/div"

    def _update_grid_spacing_label(self, mpl_axes: MPLAxes, plot: Plot):
        """Add or update grid spacing annotation on a matplotlib axes."""
        show = self._pm.get_value(plot, 'grid') and self._pm.get_value(plot, 'grid_spacing_label')

        if not show:
            if mpl_axes in self._grid_spacing_annotations:
                self._grid_spacing_annotations.pop(mpl_axes).remove()
            return

        def _calc_spacing(mpl_ax, pl):
            is_date = pl.axes[0].is_date if hasattr(pl.axes[0], 'is_date') else False

            x_label = ""
            x_ticks = sorted(mpl_ax.xaxis.get_ticklocs())
            x_lo, x_hi = mpl_ax.get_xlim()
            visible_x = [t for t in x_ticks if x_lo <= t <= x_hi]
            if len(visible_x) >= 2:
                x_spacing = abs(visible_x[1] - visible_x[0])
                if is_date:
                    formatter = mpl_ax.xaxis.get_major_formatter()
                    offset_ns = getattr(formatter, 'offset_ns', 0)
                    if offset_ns == 100_000:
                        x_spacing = x_spacing * offset_ns
                x_label = self._format_spacing(x_spacing, is_date)

            y_label = ""
            y_ticks = sorted(mpl_ax.yaxis.get_ticklocs())
            y_lo, y_hi = mpl_ax.get_ylim()
            visible_y = [t for t in y_ticks if y_lo <= t <= y_hi]
            if len(visible_y) >= 2:
                y_spacing = abs(visible_y[1] - visible_y[0])
                y_label = self._format_spacing(y_spacing)

            return x_label, y_label

        def _calc_and_update(mpl_ax=mpl_axes, pl=plot):
            x_label, y_label = _calc_spacing(mpl_ax, pl)
            text = f"X: {x_label}  Y: {y_label}" if x_label and y_label else x_label or y_label
            if mpl_ax in self._grid_spacing_annotations and text:
                self._grid_spacing_annotations[mpl_ax].set_text(text)
                self._grid_spacing_annotations[mpl_ax].set_fontsize(
                    self._pm.get_value(pl, 'font_size') or 8)

        fs = self._pm.get_value(plot, 'font_size') or 8

        if mpl_axes not in self._grid_spacing_annotations:
            ann = mpl_axes.annotate(" ", xy=(1, 0), xycoords='axes fraction',
                                    ha='right', va='bottom', fontsize=fs,
                                    color='black', alpha=0.8,
                                    xytext=(-5, 5), textcoords='offset points')
            self._grid_spacing_annotations[mpl_axes] = ann
            # Connect to axis limit changes and draw event for dynamic updates
            mpl_axes.callbacks.connect('xlim_changed', lambda ax: _calc_and_update())
            mpl_axes.callbacks.connect('ylim_changed', lambda ax: _calc_and_update())
            if hasattr(self, 'figure') and self.figure.canvas:
                self.figure.canvas.mpl_connect('draw_event', lambda ev: _calc_and_update())

    def rebuild_legend(self, mpl_axes: MPLAxes, plot: Plot):
        """
        Rebuild the legend for the given matplotlib axes with currently visible lines.
        """
        # Get visible lines for legend (exclude hidden and internal lines)
        visible_lines = [line for line in mpl_axes.get_lines()
                         if line.get_visible() and not line.get_label().startswith(('_', 'CrossX', 'CrossY'))]

        show_legend = self._pm.get_value(plot, 'legend')
        if show_legend and visible_lines:
            plot_leg_position = self._pm.get_value(plot, 'legend_position')
            canvas_leg_position = self._pm.get_value(self.canvas, 'legend_position')
            plot_leg_layout = self._pm.get_value(plot, 'legend_layout')
            canvas_leg_layout = self._pm.get_value(self.canvas, 'legend_layout')

            plot_leg_position = canvas_leg_position if plot_leg_position == 'same as canvas' else plot_leg_position
            plot_leg_layout = canvas_leg_layout if plot_leg_layout == 'same as canvas' else plot_leg_layout

            legend_props = dict(size=self.legend_size)
            col = len(visible_lines) if plot_leg_layout == 'horizontal' else 1

            leg = mpl_axes.legend(handles=visible_lines, prop=legend_props, loc=plot_leg_position, ncol=col)
            if self.figure.get_tight_layout():
                leg.set_in_layout(False)

            # Update map_legend_to_ax for legend click handling
            legend_lines = leg.get_lines()
            for ix, line in enumerate(visible_lines):
                if ix < len(legend_lines):
                    self.map_legend_to_ax[legend_lines[ix]] = line
                    legend_lines[ix].set_picker(3)
        elif not visible_lines:
            # No visible lines, remove legend
            existing_legend = mpl_axes.get_legend()
            if existing_legend:
                existing_legend.remove()

        self.figure.canvas.draw_idle()

    def refresh_streaming_legend(self, impl_plot: MPLAxes, plot: Plot):
        # matplotlib builds the legend once, so an envelope drawn on its first
        # streaming batch is absent until the legend is rebuilt from the axes.
        self.rebuild_legend(impl_plot, plot)

    def register_dynamic_signal(self, impl_plot: MPLAxes, plot: Plot, signal):
        """Register a dynamically added signal and update legend."""
        import weakref
        cache_item = self._impl_plot_cache_table.get_cache_item(impl_plot)
        if cache_item and hasattr(cache_item, 'signals'):
            cache_item.signals.append(weakref.ref(signal))
        self.rebuild_legend(impl_plot, plot)

    @staticmethod
    def _update_marker_by_point_count(marker_line: Line2D, signal_x_data, signal_style: dict):
        if len(signal_x_data) == 1:
            marker_line.set_marker('x')
            marker_line.set_markersize(signal_style.get('markersize') or 5)
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
        if self.figure.get_tight_layout():
            # Per-flush tight layout dominates draw cost: fit margins once and freeze them.
            try:
                self.figure.tight_layout()
            except Exception:
                logger.debug("tight_layout failed; freezing current margins")
            self.disable_tight_layout()

        ax_window = impl_plot.get_xlim()[1] - impl_plot.get_xlim()[0]

        # Time window
        now = int(datetime.now().timestamp() * 1e9)
        min_time = now - int(ax_window)

        y_chunks = []
        for signal_ref in cache_item.signals:
            signal = signal_ref()
            # An envelope awaiting its first streaming batch has no lines yet;
            # there is nothing to scale from until it is drawn.
            if signal is None or not signal.lines:
                continue
            is_envelope = getattr(signal, 'envelope', False)
            # Envelope signal.lines is nested [[line_min, line_max, line_avg, area]].
            first_artist = signal.lines[0][0] if is_envelope else signal.lines[0]
            if not first_artist.get_visible():
                continue
            # Snapshot x/y once: the receiver thread can update them between reads.
            x_data = signal.x_data
            y_lo = signal.y_data
            y_hi = signal.z_data if is_envelope else y_lo
            n = min(len(x_data), len(y_lo), len(y_hi))
            if n == 0:
                continue
            x_data = x_data[:n]
            y_lo = y_lo[:n]
            mask = (x_data >= min_time) & (x_data <= now)
            inside = y_lo[mask]
            if inside.size:
                y_chunks.append(inside)
            if is_envelope:
                inside_hi = y_hi[:n][mask]
                if inside_hi.size:
                    y_chunks.append(inside_hi)
            # Keep the projected constant line on screen when nothing falls inside the window.
            if not mask.any() and getattr(signal, '_streaming_has_live', False):
                y_chunks.append(np.array([y_lo[-1]]))
                if is_envelope:
                    y_chunks.append(np.array([y_hi[-1]]))

        # Sticky Y: re-fit only on out-of-range data or sustained underuse (regime change).
        if y_chunks:
            y_concat = np.concatenate(y_chunks)
            y_max = np.nanmax(y_concat).item()
            y_min = np.nanmin(y_concat).item()
            cur_lo, cur_hi = impl_plot.get_ylim()
            uninit = cur_hi <= cur_lo
            data_range = y_max - y_min
            view_range = cur_hi - cur_lo
            if uninit or y_min < cur_lo or y_max > cur_hi:
                # Wider initial margin (50%) absorbs early-batch underestimation.
                margin = 0.5 if uninit else 0.2
                if data_range == 0:
                    pad = abs(y_max) * margin if y_max != 0 else 0.1
                else:
                    pad = data_range * margin
                new_lo = (y_min if uninit else min(y_min, cur_lo)) - pad
                new_hi = (y_max if uninit else max(y_max, cur_hi)) + pad
                impl_plot.set_ylim(new_lo, new_hi)
                impl_plot._sticky_y_underuse = 0
            elif view_range > 0 and data_range / view_range < 0.3:
                streak = getattr(impl_plot, '_sticky_y_underuse', 0) + 1
                if streak >= 5:
                    pad = data_range * 0.2 if data_range > 0 else (abs(y_max) * 0.05 if y_max != 0 else 0.1)
                    impl_plot.set_ylim(y_min - pad, y_max + pad)
                    impl_plot._sticky_y_underuse = 0
                else:
                    impl_plot._sticky_y_underuse = streak
            else:
                impl_plot._sticky_y_underuse = 0

        # X: skip set_xlim when the shift is sub-pixel.
        begin = self.transform_value(impl_plot, 0, min_time, inverse=True)
        end = self.transform_value(impl_plot, 0, now, inverse=True)
        cur_begin, cur_end = impl_plot.get_xlim()
        if cur_end <= cur_begin:
            impl_plot.set_xlim(begin, end)
        else:
            px_per_data = impl_plot.bbox.width / (cur_end - cur_begin)
            if abs(end - cur_end) * px_per_data >= 1.0:
                impl_plot.set_xlim(begin, end)

    def set_line_data(self, line: Line2D, x_data, y_data):
        """
        Set the data for a Line2D atomically (single cache invalidation).
        """
        if self.canvas.streaming and len(x_data) > _STREAM_DECIMATE_THRESHOLD:
            x_data, y_data = minmax_decimate(
                x_data, y_data, _STREAM_DECIMATE_TARGET_PAIRS)
        line.set_data(x_data, y_data)

    def create_plot_lines_1D(self, draw_fn, x_data, y_data, style):
        return draw_fn(x_data, y_data, **style)

    def create_plot_lines_2D(self, draw_fn, signal, x_data, y_data, style):
        plot_lines = []
        for i in range(y_data.shape[1]):
            style_i = dict(**style)
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
            if (x_data.ndim == y_data.ndim == z_data.ndim == 2
                    and x_data.size and y_data.size and z_data.size):
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
            if (x_data.ndim == y_data.ndim == z_data.ndim == 2
                    and x_data.size and y_data.size and z_data.size):
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

            if (xsub_data.ndim == ysub_data.ndim == zsub_data.ndim == 2
                    and xsub_data.size and ysub_data.size and zsub_data.size):
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

            if (xsub_data.ndim == ysub_data.ndim == zsub_data.ndim == 2
                    and xsub_data.size and ysub_data.size and zsub_data.size):
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
        shapes[0][3].remove()
        shapes[0][3] = impl_plot.fill_between(x_data, y1_data, y2_data,
                                              alpha=0.3,
                                              color=shapes[0][0].get_color(),
                                              step=STEP_MAP[style['drawstyle']])
        shapes[0][3].set_visible(shapes[0][0].get_visible())
        self.figure.canvas.draw_idle()

    def create_area_envelope_1D(self, draw_fn, impl_plot: Any, signal, x_data, y1_data, y2_data, y3_data, style,
                                style2):
        line_1 = draw_fn(x_data, y1_data, **style)  # type: List[Line2D]
        signal.color = line_1[0].get_color()
        style2 = dict(style)
        style2.update(color=signal.color, label='')
        line_2 = draw_fn(x_data, y2_data, **style2)  # type: List[Line2D]

        # Average curve
        line_3 = draw_fn(x_data, y3_data, **style2)  # type: List[Line2D]

        area = impl_plot.fill_between(x_data, y1_data, y2_data,
                                      alpha=0.3,
                                      color=style2['color'],
                                      step=STEP_MAP[style['drawstyle']])

        lines = [line_1 + line_2 + line_3 + [area]]
        for new, old in zip(lines, signal.lines):
            new.set_visible(old.get_visible())

        return lines

    def clear(self):
        super().clear()

        # Undo the streaming-time layout freeze on rebuild.
        if getattr(self, 'figure', None) is not None and self._tight_layout_requested \
                and not self.figure.get_tight_layout():
            self.enable_tight_layout()

        # remove any active multi‑cursors
        for c in self._cursors:
            c.remove()
        self._cursors.clear()

        # remove any active rulers (impl artists only — Plot.rulers data is preserved)
        for r in self._rulers:
            r.remove()
        self._rulers.clear()

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
        self._grid_spacing_annotations.clear()
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

        if isinstance(plot, (PlotXYWithSlider, PlotContourWithSlider)):
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
                    mpl_axes.grid(show_grid, which='major')
                    if log_scale:
                        # The minor decade lines are what show the log spacing;
                        # keep them faint so the decades stay readable.
                        mpl_axes.grid(show_grid, which='minor', alpha=0.3)
                else:
                    mpl_axes.grid(show_grid, which='both')

                self._update_grid_spacing_label(mpl_axes, plot)

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
                    self._signal_impl_plot_lut.update({self.signal_lut_key(signal): mpl_axes})
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
                        # A signal not drawn yet (e.g. an envelope awaiting its
                        # first streaming batch) has no shapes and no legend
                        # entry; skip it so the mapping stays aligned instead of
                        # iterating over None.
                        shapes = self._signal_impl_shape_lut.get(id(signal))
                        if not shapes:
                            continue
                        for line in shapes:
                            if ix_legend >= len(legend_lines):
                                break
                            self.map_legend_to_ax[legend_lines[ix_legend]] = line
                            self._legend_signal_lut[legend_lines[ix_legend]] = signal
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
        self.refresh_rulers(current_plot)

    def _y_axis_update_callback(self, current_plot: MPLAxes):
        super()._y_axis_update_callback(current_plot)
        self.refresh_rulers(current_plot)

    def process_ipl_log_axis(self, mpl_axis: MPLAxis, plot: Plot):
        if isinstance(mpl_axis, YAxis):
            log_scale = self._pm.get_value(plot, 'log_scale')
            if log_scale:
                # The scale's own locators cover every range: decade powers,
                # the minor ticks that give the log spacing, and intermediate
                # values below one decade.
                mpl_axis.axes.set_yscale('log')

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

        # process_ipl_log_axis runs first, so the Y scale is already decided.
        is_log_y = getattr(mpl_axis, 'axis_name', None) == 'y' \
            and mpl_axis.axes.get_yscale() == 'log'
        if not axis.is_date and not is_log_y:
            mpl_axis.set_major_formatter(
                ExponentScalarFormatter(label_props=label_props))

        mpl_axis.set_tick_params(**tick_props)

        # Stash the requested tick count so the date locator built later in
        # process_ipl_axis_formatter can use it as its target.
        mpl_axis._ipl_tick_number = tick_number

        # Numeric axes: a date axis gets the time-aware NiceNanosecondLocator
        # (set in process_ipl_axis_formatter). For a non-date X axis we always
        # attach the RelativeTimeLocator, which self-gates: if the axis label is
        # 'Time' it lays ticks on round durations (1d, 12h, 5m, ...), otherwise
        # it falls back to MaxNLocator. (The 'Time' label is applied later, in
        # signal processing, so we can't decide here -- the locator and the
        # ExponentScalarFormatter both read the label live at draw time.)
        if not axis.is_date and not is_log_y:
            if getattr(mpl_axis, 'axis_name', None) == 'x':
                mpl_axis.set_major_locator(RelativeTimeLocator(tick_number))
            else:
                mpl_axis.set_major_locator(MaxNLocator(tick_number))

    def process_ipl_axis_formatter(self, impl_plot: MPLAxes, mpl_axis: MPLAxis, ax_idx: int):
        ci = self._impl_plot_cache_table.get_cache_item(impl_plot)
        # Time-aware locator that shares the per-axis offset table with the
        # formatter, so tick positions and labels always agree (UTC).
        target_ticks = getattr(mpl_axis, '_ipl_tick_number', 6)
        locator = NiceNanosecondLocator(ax_idx, offset_lut=ci.offsets, target_ticks=target_ticks)
        mpl_axis.set_major_locator(locator)
        mpl_axis.set_major_formatter(NanosecondDateFormatter(ax_idx,
                                                             offset_lut=ci.offsets,
                                                             roundh=self._pm.get_value(self.canvas, 'round_hour'),
                                                             nice_locator=locator))

    def process_ipl_signal_impl_plot(self, signal: Signal):
        mpl_axes = self._signal_impl_plot_lut.get(self.signal_lut_key(signal))  # type: MPLAxes
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
        lines = [line for line in lines if line.get_label() not in ["CrossX", "CrossY", "_RulerLine"]]
        lo, hi = impl_plot.get_xlim()
        return lines, lo, hi

    def autoscale_y_axis(self, impl_plot: MPLAxes, padding=0.1):
        """
        This function rescales the y-axis based on the data that is visible given the current xlim of the axis.
        ax -- a matplotlib axes object
        padding -- the fraction of the total height of the y-data to pad the upper and lower ylims
        """
        bot, top = super().autoscale_y_axis(impl_plot)

        if impl_plot.get_yscale() == 'log':
            # Pad multiplicatively from the smallest positive visible sample:
            # a linear margin would go non-positive and silently degrade to
            # matplotlib's global autoscale.
            pos_bot = self._min_positive_visible(impl_plot)
            if pos_bot is not None and top > 0:
                factor = (top / pos_bot) ** padding if top > pos_bot else 2.0
                self.set_oaw_axis_limits(impl_plot, 1, (pos_bot / factor, top * factor))
            else:
                impl_plot.autoscale(enable=True, axis='y')
            return

        # Compute final margin
        h = (top - bot)
        n_new_bot = bot - padding * h
        n_new_top = top + padding * h

        # Set new Y axis limits
        self.set_oaw_axis_limits(impl_plot, 1, (n_new_bot, n_new_top))

    def _min_positive_visible(self, impl_plot: MPLAxes):
        """Smallest strictly positive Y sample within the current X window, or
        None when nothing positive is visible."""
        lines, lo, hi = self.get_impl_lines(impl_plot)
        best = None
        for line in lines:
            xd, yd = self.get_impl_data(line)
            if xd is None or yd is None:
                continue
            yd = np.asarray(yd)[(np.asarray(xd) >= lo) & (np.asarray(xd) <= hi)]
            yd = yd[np.isfinite(yd) & (yd > 0)]
            if yd.size and (best is None or yd.min() < best):
                best = float(yd.min())
        return best

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
            formatter = NanosecondDateFormatter(ax_idx=0)
            start_value = slider_values[start]
            current_value = slider_values[val]
            max_value = slider_values[end]

            min_annotation.set_text(
                formatter.date_fmt(start_value, formatter.YEAR, formatter.NANOSECOND, postfix_end=True))
            current_annotation.set_text(
                formatter.date_fmt(current_value, formatter.cut_start + 3, formatter.NANOSECOND, postfix_end=True))
            max_annotation.set_text(
                formatter.date_fmt(max_value, formatter.cut_start + 3, formatter.NANOSECOND, postfix_end=True))
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
            formatter = NanosecondDateFormatter(ax_idx=0)
            start_value = slider_values[new_start]
            current_value = slider_values[val]
            max_value = slider_values[new_end]

            min_annotation.set_text(
                formatter.date_fmt(start_value, formatter.YEAR, formatter.NANOSECOND, postfix_end=True))
            current_annotation.set_text(
                formatter.date_fmt(current_value, formatter.cut_start + 3, formatter.NANOSECOND, postfix_end=True))
            max_annotation.set_text(
                formatter.date_fmt(max_value, formatter.cut_start + 3, formatter.NANOSECOND, postfix_end=True))
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
                                                        PlotXYWithSlider) and plot_temp != self._focus_plot and not isinstance(
                            plot_temp, (PlotXYWithSlider, PlotContourWithSlider)):
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
                                 font_size=int(self._pm.get_value(self.canvas, 'font_size') or 8),
                                 use_blit=True,
                                 cache_table=self._impl_plot_cache_table))

    @BackendParserBase.run_in_one_thread
    def deactivate_cursor(self):
        for cursor in self._cursors:
            cursor.remove()
        self._cursors.clear()

    def _ruler_value_lines(self, impl_plot: MPLAxes) -> list:
        """Signal line groups of *impl_plot*, one per ruler value label
        (mirrors the crosshair's value annotations)."""
        ci = self._impl_plot_cache_table.get_cache_item(impl_plot)
        groups = []
        if ci and hasattr(ci, 'signals') and ci.signals:
            for sig_ref in ci.signals:
                signal = sig_ref()
                if not signal or isinstance(signal, SignalContour):
                    continue
                for line in getattr(signal, 'lines', []):
                    groups.append(line if isinstance(line, Collection) else [line])
        return groups

    def _ruler_signal_values(self, impl_plot: MPLAxes, x: float) -> Dict[str, float]:
        """Value of each signal at the ruler X keyed by its label, matching the
        ruler's green value labels. A signal is omitted when the ruler falls off
        its data, so the table agrees with what the plot shows."""
        ci = self._impl_plot_cache_table.get_cache_item(impl_plot)
        values: Dict[str, float] = {}
        if not ci or not getattr(ci, 'signals', None):
            return values
        for sig_ref in ci.signals:
            signal = sig_ref()
            if not signal or isinstance(signal, SignalContour):
                continue
            for line in getattr(signal, 'lines', []):
                group = line if isinstance(line, Collection) else [line]
                xdata = group[0].get_xdata() if group else []
                if len(xdata) == 0:
                    continue
                x_sig, y_sig = get_values_from_line(group, x)
                span = abs(xdata[-1] - xdata[0])
                # Data-span tolerance (view-independent so the cell is stable on
                # zoom); mirrors the 5% used by the value labels.
                if span and abs(x - x_sig) <= span * 0.05:
                    values[signal.label or 'signal'] = float(y_sig)
                break
        return values

    @BackendParserBase.run_in_one_thread
    def add_ruler(self, impl_plot: MPLAxes, name: str, x: float, y: float,
                  color: str = "#FFFFFF", animated: bool = False,
                  is_echo: bool = False) -> iplotMplRuler:
        font_size = int(self._pm.get_value(self.canvas, 'font_size') or 8)
        ruler = iplotMplRuler(ax=impl_plot, name=name, xy=(x, y), color=color,
                              font_size=font_size, animated=animated,
                              value_lines=self._ruler_value_lines(impl_plot))
        ruler.abs_x = self.transform_value(impl_plot, 0, x)
        ruler.abs_y = self.transform_value(impl_plot, 1, y)
        ruler.is_echo = is_echo
        self._rulers.append(ruler)
        return ruler

    def create_ruler_echoes(self, origin_impl_plot: MPLAxes, name: str,
                            x_abs: float, y_abs: float, color: str):
        """Mirror a ruler onto every plot sharing the time axis. Each echo carries
        the same absolute X/Y and re-projects them to its own plot's offsets."""
        if not self._pm.get_value(self.canvas, 'shared_x_axis'):
            return
        for sibling in self._get_all_shared_axes(origin_impl_plot):
            if sibling is origin_impl_plot:
                continue
            x_view = self.transform_value(sibling, 0, x_abs, inverse=True)
            y_view = self.transform_value(sibling, 1, y_abs, inverse=True)
            self.add_ruler(sibling, name, x_view, y_view, color, is_echo=True)

    @BackendParserBase.run_in_one_thread
    def remove_ruler(self, impl_plot: MPLAxes, name: str):
        remaining = []
        for r in self._rulers:
            if r.ax is impl_plot and r.name == name:
                r.remove()
            else:
                remaining.append(r)
        self._rulers = remaining

    @BackendParserBase.run_in_one_thread
    def remove_ruler_by_name(self, name: str):
        """Remove a ruler and its shared-x echoes across every plot (names are
        canvas-global unique)."""
        remaining = []
        for r in self._rulers:
            if r.name == name:
                r.remove()
            else:
                remaining.append(r)
        self._rulers = remaining

    def refresh_rulers(self, impl_plot: MPLAxes = None):
        for r in self._rulers:
            if impl_plot is None or r.ax is impl_plot:
                r.xy = (self.transform_value(r.ax, 0, r.abs_x, inverse=True),
                        self.transform_value(r.ax, 1, r.abs_y, inverse=True))
                r.refresh_labels()

    def get_rulers(self, impl_plot: MPLAxes = None) -> List[iplotMplRuler]:
        if impl_plot is None:
            return list(self._rulers)
        return [r for r in self._rulers if r.ax is impl_plot]

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
        if not isinstance(impl_plot, MPLAxes):
            return None
        if impl_plot.get_yscale() == 'log':
            lo, hi = limits[0], limits[1]
            if lo is None or hi is None or lo <= 0 or hi <= 0:
                # A log axis cannot show non-positive bounds (linear padding can
                # push the bottom below zero) — fall back to autoscale, like the
                # pyqtgraph backend.
                impl_plot.autoscale(enable=True, axis='y')
                return None
        impl_plot.set_ylim(limits[0], limits[1])

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
        x_axis = self.get_impl_x_axis(impl_plot)
        x_axis.set_label_text(text, **label_props)

        # The 'Time' label is applied here, during signal processing, which is
        # the authoritative moment to decide whether this is a relative-time
        # axis. Set the flag directly on the formatter and locator so neither
        # has to re-sniff the label later (the label string/timing at draw time
        # proved unreliable).
        x_is_time = is_time_label(text)
        fmt = x_axis.get_major_formatter()
        if isinstance(fmt, ExponentScalarFormatter):
            fmt._is_time = x_is_time
        loc = x_axis.get_major_locator()
        if isinstance(loc, RelativeTimeLocator):
            loc._force_time = x_is_time

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
        y_axis = self.get_impl_y_axis(impl_plot)
        if self._tight_layout_requested and not self.figure.get_tight_layout() \
                and y_axis.get_label_text() != text:
            # Stream units arrive after the layout freeze in do_impl_streaming;
            # refit once so the new label gets its own margin space.
            self.enable_tight_layout()
        y_axis.set_label_text(text, **label_props)

    def transform_value(self, impl_plot: Any, ax_idx: int, value: Any, inverse=False):
        """Adds or subtracts axis offset from value trying to preserve type of offset (ex: does not convert to
        float when offset is int)"""
        return self._impl_plot_cache_table.transform_value(impl_plot, ax_idx, value, inverse=inverse)


def get_data_range(data, axis_idx):
    """Returns first and last value from data[axis_idx] or None"""
    if data is not None and len(data) > axis_idx and len(data[axis_idx] > 0):
        return data[axis_idx][0], data[axis_idx][-1]
    return None
