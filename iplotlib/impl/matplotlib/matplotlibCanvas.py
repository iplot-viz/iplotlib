from contextlib import ExitStack
from typing import Any, Callable, Collection, List

import numpy
from matplotlib.axes import Axes as MPLAxes
from matplotlib.axis import Tick
from matplotlib.axis import Axis as MPLAxis
from matplotlib.backend_bases import FigureCanvasBase
from matplotlib.figure import Figure
from matplotlib.gridspec import GridSpecFromSubplotSpec, SubplotSpec
from matplotlib.lines import Line2D
from matplotlib.text import Annotation, Text
from matplotlib.widgets import MultiCursor
from pandas.plotting import register_matplotlib_converters

import iplotLogging.setupLogger as sl
from iplotlib.core import (Axis,
                           LinearAxis,
                           RangeAxis,
                           Canvas,
                           IplPlotViewLimits,
                           IplotAxesRangeCmd,
                           BackendParserBase,
                           Plot,
                           Signal)
from iplotlib.core.impl_base import ImplementationPlotCacheTable
from iplotlib.impl.matplotlib.dateFormatter import NanosecondDateFormatter

logger = sl.get_logger(__name__)


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

        self.legend_size = 8
        self._cursors = []

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

        self.figure.set_size_inches(width/dpi, height/dpi)
        self.refresh()
        self.figure.savefig(filename)

    def do_mpl_line_plot(self, signal: Signal, mpl_axes: MPLAxes, x_data, y_data):
        if not isinstance(mpl_axes, MPLAxes):
            return

        lines = self._signal_impl_shape_lut.get(
            id(signal))  # type: List[List[Line2D]]
        try:
            cache_item = self._impl_plot_cache_table.get_cache_item(mpl_axes)
            plot = cache_item.plot()
        except AttributeError:
            plot = None
        style = self.get_signal_style(signal, plot)
        step = style.pop('step', None)

        if isinstance(lines, list):
            line = lines[0][0]  # type: Line2D
            line.set_xdata(x_data)
            line.set_ydata(y_data)
            style.update({'drawstyle': step})
            for k, v in style.items():
                setter = getattr(line, f"set_{k}")
                if v is None and k != "drawstyle":
                    continue
                setter(v)
            self.figure.canvas.draw_idle()
        else:
            params = dict(**style)
            draw_fn = mpl_axes.plot
            if step is not None and step != 'None':
                params.update({'where': step})
                draw_fn = mpl_axes.step

            lines = draw_fn(x_data, y_data, **params)
            self._signal_impl_shape_lut.update({id(signal): [lines]})

    def do_mpl_envelope_plot(self, signal: Signal, mpl_axes: MPLAxes, x_data, y1_data, y2_data):
        if not isinstance(mpl_axes, MPLAxes):
            return

        shapes = self._signal_impl_shape_lut.get(
            id(signal))  # type: List[List[Line2D]]
        try:
            cache_item = self._impl_plot_cache_table.get_cache_item(mpl_axes)
            plot = cache_item.plot()
        except AttributeError:
            plot = None
        style = self.get_signal_style(signal, plot)
        step = style.pop('step', None)

        if shapes is not None:
            shapes[0][0].set_xdata(x_data)
            shapes[0][0].set_ydata(y1_data)
            shapes[1][0].set_xdata(x_data)
            shapes[1][0].set_ydata(y2_data)
            shapes[2].remove()
            shapes.pop()
            style.update({'drawstyle': step})
            for k, v in style.items():
                setter = getattr(shapes[0][0], f"set_{k}")
                if v is None and k != "drawstyle":
                    continue
                setter(v)
                setter = getattr(shapes[1][0], f"set_{k}")
                setter(v)
            area = mpl_axes.fill_between(x_data, y1_data, y2_data,
                                         alpha=0.3,
                                         color=shapes[1][0].get_color(),
                                         step=step)
            shapes.append(area)
            shapes[0][0].draw()
            shapes[1][0].draw()
            shapes[2].draw()
        else:
            params = dict(**style)
            draw_fn = mpl_axes.plot
            if step is not None and step != 'None':
                params.update({'where': step})
                draw_fn = mpl_axes.step

            line_1 = draw_fn(x_data, y1_data, **params)
            line_2 = draw_fn(x_data, y2_data, **params)
            area = mpl_axes.fill_between(x_data, y1_data, y2_data,
                                         alpha=0.3,
                                         color=params.get('color'),
                                         step=step)

            self._signal_impl_shape_lut.update({id(signal): [line_1, line_2, area]})

    def clear(self):
        super().clear()
        self.figure.clear()

    def update_range_axis(self, range_axis: RangeAxis, ax_idx: int, mpl_axes: MPLAxes, which: str='current'):
        """If axis is a RangeAxis update its min and max to mpl view limits"""
        limits = NanosecondHelper.mpl_get_lim(mpl_axes, ax_idx)
        if which == 'current':
            range_axis.begin = limits[0]
            range_axis.end = limits[1]
        else: # which == 'original'
            range_axis.original_begin = range_axis.begin
            range_axis.original_end = range_axis.end
        super().update_range_axis(range_axis, ax_idx, mpl_axes)

    def set_impl_plot_limits(self, impl_plot: Any, ax_idx: int, limits: tuple) -> bool:
        if not isinstance(impl_plot, MPLAxes):
            return False
        NanosecondHelper.mpl_set_lim(impl_plot, ax_idx, limits)
        return True

    def _get_all_shared_axes(self, base_mpl_axes: MPLAxes):
        if not isinstance(self.canvas, Canvas):
            return []
        if self.canvas.shared_x_axis:
            return self.figure.axes
        else:
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
            self._layout = self.figure.add_gridspec(canvas.rows, canvas.cols)
        else:
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
            if not canvas.font_size:
                canvas.font_size = None
            self.figure.suptitle(
                canvas.title, size=canvas.font_size, color=self.canvas.font_color or 'black')

    def process_ipl_plot(self, plot: Plot, column: int, row: int):
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
                if not self._plot_impl_plot_lut.get(id(plot)):
                    self._plot_impl_plot_lut.update({id(plot): mpl_axes})
                mpl_axes_prev = mpl_axes
                # Keep references to iplotlib instances for ease of access in callbacks.
                self._impl_plot_cache_table.register(mpl_axes, self.canvas, plot, key, signals)
                mpl_axes.set_xmargin(0)
                mpl_axes.set_autoscalex_on(True)
                mpl_axes.set_autoscaley_on(True)

                # Set the plot title
                if plot.title is not None:
                    fc = self._pm.get_value(
                        'font_color', self.canvas, plot) or 'black'
                    fs = self._pm.get_value('font_size', self.canvas, plot)
                    if not fs:
                        fs = None
                    mpl_axes.set_title(plot.title, color=fc, size=fs)

                # If this is a stacked plot the X axis should be visible only on the bottom plot of the stack
                # hides an axis in a way that grid remains visible,
                # by default in matplotlib the gird is treated as part of the axis
                visible = stack_id + 1 == len(plot.signals.values())
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
                    legend_props = dict(size=self.legend_size)
                    leg = mpl_axes.legend(prop=legend_props)
                    if self.figure.get_tight_layout():
                        leg.set_in_layout(False)

        # Observe the axis limit change events
        if not self.canvas.streaming:
            for axes in mpl_axes.get_shared_x_axes().get_siblings(mpl_axes):
                axes.callbacks.connect(
                    'xlim_changed', self._axis_update_callback)
                axes.callbacks.connect(
                    'ylim_changed', self._axis_update_callback)

    def _axis_update_callback(self, axis):

        affected_axes = axis.get_shared_x_axes().get_siblings(axis)

        if self.canvas.shared_x_axis:
            other_axes = self._get_all_shared_axes(axis)
            for other_axis in other_axes:
                cur_x_limits = NanosecondHelper.mpl_get_lim(axis, 0)
                other_x_limits = NanosecondHelper.mpl_get_lim(other_axis, 0)
                if cur_x_limits[0] != other_x_limits[0] or cur_x_limits[1] != other_x_limits[1]:
                    NanosecondHelper.mpl_set_lim(other_axis, 0, cur_x_limits)

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
                if hasattr(signal, "set_ranges"):
                    signal.set_ranges([ranges[0], ranges[1]])
            self._stale_impl_plots.add(a)

    def process_ipl_axis(self, axis: Axis, ax_idx, plot: Plot, impl_plot: MPLAxes):
        super().process_ipl_axis(axis, ax_idx, plot, impl_plot)
        mpl_axis = NanosecondHelper.mpl_get_axis(
            impl_plot, ax_idx)  # type: MPLAxis
        self._axis_impl_plot_lut.update({id(axis): impl_plot})
        if isinstance(axis, Axis):
            fc = self._pm.get_value(
                'font_color', self.canvas, axis, plot) or 'black'
            fs = self._pm.get_value('font_size', self.canvas, axis, plot)

            mpl_axis._font_color = fc
            mpl_axis._font_size = fs
            mpl_axis._label = axis.label

            label_props = dict(color=fc)
            tick_props = dict(color=fc, labelcolor=fc)
            if fs is not None and fs > 0:
                label_props.update({'fontsize': fs})
                tick_props.update({'labelsize': fs})
            if axis.label is not None:
                mpl_axis.set_label_text(axis.label, **label_props)

            mpl_axis.set_tick_params(**tick_props)

        if isinstance(axis, RangeAxis) and axis.begin is not None and axis.end is not None and (axis.begin or axis.end):
            logger.debug(
                f"process_ipl_axis: setting {ax_idx} axis range to {axis.begin} and {axis.end}")
            NanosecondHelper.mpl_set_lim(impl_plot, ax_idx, [axis.begin, axis.end])

        if isinstance(axis, LinearAxis):
            if axis.is_date:
                mpl_axis.set_major_formatter(NanosecondDateFormatter())

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
        signal_data = signal.get_data()
        data = NanosecondHelper.mpl_axes_transform_data(mpl_axes, signal_data)

        if hasattr(signal, "envelope") and signal.envelope:
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

        def group_data_units(axes):
            """Function that returns axis label made from signal units"""
            units = []
            ci = self._impl_plot_cache_table.get_cache_item(axes)
            if hasattr(ci, 'signals') and ci.signals:
                for signal_ref in ci.signals:
                    s = signal_ref()
                    try:
                        assert isinstance(s.y_data.unit, str)
                        if len(s.y_data) and len(s.y_data.unit):
                            units.append(s.y_data.unit)
                    except (AttributeError, AssertionError) as e:
                        continue
            units = set(units) if len(set(units)) == 1 else units
            return '[{}]'.format(']['.join(units)) if len(units) else None

        yaxis = mpl_axes.get_yaxis()
        if hasattr(yaxis, "_label") and not yaxis._label:
            label = group_data_units(mpl_axes)
            if label:
                yaxis.set_label_text(label)
        xaxis = mpl_axes.get_xaxis()
        put_label = False
        ci = self._impl_plot_cache_table.get_cache_item(mpl_axes)
        if hasattr(ci, 'plot') and ci.plot():
            if hasattr(ci.plot(), 'axes'):
                xax = ci.plot().axes[0]
                if isinstance(xax, LinearAxis):
                    put_label |= (not xax.is_date)

        if put_label and hasattr(signal, 'x_data'):
            if hasattr(signal.x_data, 'unit'):
                label = f"[{signal.x_data.unit or '?'}]"
                if label:
                    xaxis.set_label_text(label)
        # label from preferences takes precedence.
        if hasattr(xaxis, "_label") and xaxis._label:
            xaxis.set_label_text(xaxis._label)

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
                    for plot in columns:
                        if plot != self._focus_plot:
                            logger.debug(
                                f"Setting range on plot {id(plot)} focused= {id(self._focus_plot)} begin={begin}")
                            set_x_axis_range(plot, begin, end)

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
            self._cursors.append(MultiCursor2(self.figure.canvas, axes_group, color=self.canvas.crosshair_color, lw=self.canvas.crosshair_line_width, horizOn=False or self.canvas.crosshair_horizontal,
                                              vertOn=self.canvas.crosshair_vertical, useblit=True, cache_table=self._impl_plot_cache_table))

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

        style['linewidth'] = self._pm.get_value(
            'line_size', self.canvas, plot, signal=signal) or 1
        style['linestyle'] = (self._pm.get_value(
            'line_style', self.canvas, plot, signal=signal) or "Solid").lower()
        style['marker'] = self._pm.get_value(
            'marker', self.canvas, plot, signal=signal)
        style['markersize'] = self._pm.get_value(
            'marker_size', self.canvas, plot, signal=signal) or 0
        style["step"] = self._pm.get_value(
            'step', self.canvas, plot, signal=signal)
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


def get_data_range(data, axis_idx):
    """Returns first and last value from data[axis_idx] or None"""
    if data is not None and len(data) > axis_idx and len(data[axis_idx] > 0):
        return (data[axis_idx][0], data[axis_idx][-1])
    return None


class MultiCursor2(MultiCursor):

    def __init__(self, canvas: FigureCanvasBase,
                 axes: MPLAxes,
                 useblit: bool = True,
                 horizOn=False,
                 vertOn=True,
                 x_label=True,
                 y_label=True,
                 val_label: bool = True,
                 val_tolerance: float = 0.05,
                 text_color: str = "white",
                 font_size: int = 8,
                 cache_table: ImplementationPlotCacheTable = None,
                 **lineprops):

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
                if hasattr(ci, "signals") and ci.signals():
                    for signal in ci.signals():
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

                        xvalue = NanosecondHelper.mpl_transform_value(
                            ax.get_xaxis(), event.xdata)
                        values = signal.pick(xvalue)
                        logger.debug(F"Found {values} for xvalue: {xvalue}")
                        if values is not None:
                            dx = abs(xvalue - values[0])
                            xmin, xmax = ax.get_xbound()
                            if dx < (xmax - xmin) * self.val_tolerance:
                                pos_x = NanosecondHelper.mpl_transform_value(
                                    ax.get_xaxis(), values[0], True)
                                pos_y = NanosecondHelper.mpl_transform_value(
                                    ax.get_yaxis(), values[1], True)
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


# def nvl(*objs):
#     """Returns first non-None value"""

#     for o in objs:
#         if o is not None:
#             return o
#     return None


# def nvl_prop(prop_name, *objs, default=None):
#     """Returns first not None property value from list of objects"""

#     for o in objs:
#         if hasattr(o, prop_name) and getattr(o, prop_name) is not None:
#             return getattr(o, prop_name)
#     return default


class NanosecondHelper:

    @staticmethod
    def mpl_create_offset(vals):
        """Given a collection of values determine if creting offset is necessary and return it
        Returns None otherwise"""
        if isinstance(vals, Collection) and len(vals) > 0:
            if ((hasattr(vals, 'dtype') and vals.dtype.name == 'int64')
                    or (type(vals[0]) == int)
                    or isinstance(vals[0], numpy.int64)) and vals[0] > 10**15:
                return vals[0]
        if isinstance(vals, Collection) and len(vals) > 0:
            if ((hasattr(vals, 'dtype') and vals.dtype.name == 'uint64')
                    or (type(vals[0]) == int)
                    or isinstance(vals[0], numpy.uint64)) and vals[0] > 10**15:
                return vals[0]
        return None

    @staticmethod
    def mpl_transform_value(mpl_axis, value, inverse=False):
        """Adds or subtracts axis offset from value trying to preserve type of offset (ex: does not convert to
        float when offset is int)"""
        base = 0
        if mpl_axis is not None and hasattr(mpl_axis, '_offset'):
            base = mpl_axis._offset
            if isinstance(mpl_axis._offset, int) or mpl_axis._offset.dtype.name == 'int64':
                value = int(value)
        return value - base if inverse else value + base

    @staticmethod
    def mpl_axis_get_value(mpl_axis, data_sample):
        """Offset-aware get axis value"""
        return NanosecondHelper.mpl_transform_value(mpl_axis, data_sample)

    @staticmethod
    def mpl_get_axis(mpl_axes, axis_idx):
        """Convenience method that gets matplotlib axis by index instead of using separate methods get_xaxis/get_yaxis"""
        if 0 <= axis_idx <= 1:
            return [mpl_axes.get_xaxis, mpl_axes.get_yaxis][axis_idx]()
        return None

    @staticmethod
    def mpl_get_lim(mpl_axes, axis_idx):
        """Offset-aware version of mpl_axis.get_xlim()/get_ylim()"""
        begin, end = (None, None)
        if 0 <= axis_idx <= 1:
            begin, end = [mpl_axes.get_xlim, mpl_axes.get_ylim][axis_idx]()

        mpl_axis = NanosecondHelper.mpl_get_axis(mpl_axes, axis_idx)
        if hasattr(mpl_axis, '_offset'):
            begin = NanosecondHelper.mpl_transform_value(mpl_axis, begin)
            end = NanosecondHelper.mpl_transform_value(mpl_axis, end)

        return begin, end

    @staticmethod
    def mpl_set_lim(mpl_axes, axis_idx, limits):
        mpl_axis = NanosecondHelper.mpl_get_axis(mpl_axes, axis_idx)

        if not hasattr(mpl_axis, '_offset'):
            new_offset = NanosecondHelper.mpl_create_offset(limits)
            if new_offset is not None:
                mpl_axis._offset = new_offset

        if hasattr(mpl_axis, '_offset'):
            begin = NanosecondHelper.mpl_transform_value(
                mpl_axis, limits[0], inverse=True)
            end = NanosecondHelper.mpl_transform_value(
                mpl_axis, limits[1], inverse=True)
        else:
            begin = limits[0]
            end = limits[1]

        if axis_idx == 0:
            if begin == end and begin is not None:
                begin = end-1
            return mpl_axes.set_xlim([begin, end])
        elif axis_idx == 1:
            return mpl_axes.set_ylim([begin, end])
        else:
            return None

    @staticmethod
    def mpl_axes_transform_data(mpl_axes, data):
        """This function post processes data if it cannot be plot with matplotlib directly.
        Currently it transforms data if it is a large integer which can cause overflow in matplotlib"""
        ret = []
        if isinstance(data, Collection):
            for i, d in enumerate(data):
                mpl_axis = NanosecondHelper.mpl_get_axis(mpl_axes, i)
                if not hasattr(mpl_axis, '_offset'):
                    new_offset = NanosecondHelper.mpl_create_offset(d)
                    if new_offset is not None:
                        mpl_axis._offset = d[0]

                if hasattr(mpl_axis, '_offset'):
                    logger.debug(
                        F"\tAPPLY DATA OFFSET {mpl_axis._offset} to axis {id(mpl_axis)} idx: {i}")
                    if isinstance(d, Collection):
                        ret.append([e - mpl_axis._offset for e in d])
                    else:
                        ret.append(d - mpl_axis._offset)
                else:
                    ret.append(d)
        return ret
