import collections
import functools
import threading
from contextlib import ExitStack
from functools import partial
from queue import Empty, Queue
from threading import Timer
from typing import Collection

import numpy
import numpy as np
from iplotlib.core.axis import LinearAxis, RangeAxis
from iplotlib.core.canvas import Canvas
from iplotlib.core.plot import Plot
from iplotlib.impl.matplotlib.dateFormatter import NanosecondDateFormatter
from matplotlib.axis import Tick
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from matplotlib.text import Annotation, Text
from matplotlib.widgets import MultiCursor
from pandas.plotting import register_matplotlib_converters


import iplotLogging.setupLogger as ls

logger = ls.get_logger(__name__)

class MatplotlibCanvas:

    def __init__(self, canvas: Canvas = None, tight_layout=True, mpl_flush_method=None, focus_plot=None):
        self.canvas = canvas
        self.cursors = []
        self.legend_size = 8  # legend font size
        self.tight_layout = tight_layout
        self.focused_plot = focus_plot

        self.axes_update_timer_delay = 2
        self.axes_update_timer = None
        self.axes_update_set = set()
        self.axes_ranges = dict()

        self.mpl_flush_method = mpl_flush_method  # If this method is not empty draw requests will be queued and then this method will be run
        self.mpl_draw_thread = threading.current_thread()
        self.mpl_task_queue = Queue()

        self.mpl_axes = dict()
        self.mpl_shapes = dict()

        register_matplotlib_converters()
        #TODO: SO:50325907 it would be better to call tight_layout manually than use this
        self.figure = Figure(tight_layout=self.tight_layout)
        self.process_iplotlib_canvas(canvas)

    def _run_in_one_thread(func):
        """
        A decorator that causes all matplotlib operations to execute in the main thread (self.mpl_draw_thread) even if these functions were called in other threads
        - if self.mpl_flush_method is None then decorated method is executed immediately
        - if self.mpl_flush_method is not None then decorated method will be executed immediately as long as current thread is the same as self.mpl_draw_thread,
          in other case it will be queued for later execution and self.mpl_flush_method should process this queue in the draw thread
        """
        @functools.wraps(func)
        def wrapper(self, *args, **kwargs):
            if threading.current_thread() == self.mpl_draw_thread or self.mpl_flush_method is None:
                return func(self, *args, **kwargs)
            else:
                self.mpl_task_queue.put(partial(func, self, *args, **kwargs))
                self.mpl_flush_method()

        return wrapper

    @_run_in_one_thread
    def activate_cursor(self):
        if not self.canvas:
            return

        if self.canvas.crosshair_per_plot:
            plots = {}
            for ax in self.figure.axes:
                if not plots.get(id(ax._plot)):
                    plots[id(ax._plot)] = [ax]
                else:
                    plots[id(ax._plot)].append(ax)
            axes = list(plots.values())
        else:
            axes = [self.figure.axes]

        for axes_group in axes:
            self.cursors.append(MultiCursor2(self.figure.canvas, axes_group, color=self.canvas.crosshair_color, lw=self.canvas.crosshair_line_width, horizOn=False or self.canvas.crosshair_horizontal,
                                             vertOn=self.canvas.crosshair_vertical, useblit=True))

    @_run_in_one_thread
    def deactivate_cursor(self):
        for cursor in self.cursors:
            cursor.remove()
        self.cursors.clear()

    def process_iplotlib_canvas(self, canvas):
        if canvas:
            self.canvas = canvas
            self.figure.clear()
            self.mpl_axes = dict()
            self.mpl_shapes = dict()

            if canvas.title:
                self.figure.suptitle(canvas.title, size=canvas.font_size, color=canvas.font_color or 'black')

            rows, cols = (1, 1) if self.focused_plot is not None else (canvas.rows, canvas.cols)
            gridspec = self.figure.add_gridspec(rows, cols)

            for i, col in enumerate(canvas.plots):
                for j, plot in enumerate(col):
                    if plot:
                        row_span = plot.row_span if hasattr(plot, "row_span") else 1
                        col_span = plot.col_span if hasattr(plot, "col_span") else 1

                        if self.focused_plot is not None:
                            if self.focused_plot == plot:
                                logger.info(F"\t**Focusing on plot: {plot}")
                                self.process_iplotlib_plot(canvas, plot, gridspec[0, 0])
                        else:
                            self.process_iplotlib_plot(canvas, plot, gridspec[j:j + row_span, i:i + col_span])


    def process_iplotlib_plot(self, canvas: Canvas, plot: Plot, griditem):

        def axis_update_callback(axis):

            affected_axes = axis.get_shared_x_axes().get_siblings(axis)

            if canvas.shared_x_axis:
                other_axes = list(set(self.figure.axes) - set(affected_axes))
                for other_axis in other_axes:
                    cur = axis.get_xlim()
                    cur2 = other_axis.get_xlim()
                    if cur[0] != cur2[0] or cur[1] != cur2[1]:
                        other_axis.set_xlim(cur)

            # print(f"Affecred axes: {affected_axes}")
            for a_idx, a in enumerate(affected_axes):
                ranges_hash = hash((*a.get_xlim(), *a.get_ylim()))
                current_hash = self.axes_ranges.get(id(a))

                if current_hash is None or ranges_hash != current_hash:
                    a._xy_lim_changes += 1
                    self.axes_ranges[id(a)] = ranges_hash

                    def update_single_range_axis(range_axis, axis_index, mpl_axes):
                        """If axis is a RangeAxis update its min and max to mpl view limits"""

                        if isinstance(range_axis, RangeAxis):
                            logger.info(F"*Axis update {id(range_axis)} xmin={a.get_xlim()[0]} xmax={a.get_xlim()[1]} delta={a.get_xlim()[1] - a.get_xlim()[0]} ")
                            range_axis.begin, range_axis.end = NanosecondHelper.mpl_get_lim(mpl_axes, axis_index)
                            return [range_axis.begin, range_axis.end]

                    def update_range_axis(range_axis, axis_index, mpl_axes):
                        """Updates RangeAxis instances begin and end to mpl_axis limits. Works also on stacked axes"""
                        if isinstance(range_axis, Collection):
                            subranges = []
                            for stack_axis in range_axis:
                                #FIXME: Use mpl_get_axis here
                                if axis_index == 0:
                                    a_min, a_max = update_single_range_axis(stack_axis, axis_index, a)
                                else:
                                    if isinstance(stack_axis, RangeAxis):
                                        a_min, a_max = NanosecondHelper.mpl_get_lim(mpl_axes, axis_index)
                                        stack_axis.begin, stack_axis.end = a_min, a_max
                                    else:
                                        a_min, a_max = None, None
                                subranges.append([a_min, a_max])
                            return subranges
                        else:
                            return update_single_range_axis(range_axis, axis_index, mpl_axes)

                    ranges = []

                    if a._plot:
                        for axis_idx, plot_axis in enumerate(a._plot.axes):
                            ranges.append(update_range_axis(plot_axis, axis_idx, a))

                    if a._xy_lim_changes > 2:
                        self.axes_update_set.add(a)

                        for signal in a._signals:
                            if hasattr(signal, "set_ranges"):
                                signal.set_ranges([ranges[0], ranges[1]])

                if self.axes_update_timer:
                    self.axes_update_timer.cancel()

                self.axes_update_timer = Timer(self.axes_update_timer_delay, self.refresh_data)
                self.axes_update_timer.start()

        if not isinstance(plot, Plot):
            raise Exception("Not a Plot instance: " + str(plot))

        subgrid = griditem.subgridspec(len(plot.signals.keys()), 1, hspace=0)

        axes = None

        for stack_idx, stack_key in enumerate(sorted(plot.signals.keys())):
            stack_signals = plot.signals.get(stack_key) or list()
            axes = self.figure.add_subplot(subgrid[stack_idx, 0], sharex=axes)
            axes._xy_lim_changes = 0
            axes._signals = []
            axes._plot = plot
            axes._canvas = canvas
            axes._signal_shapes = {}
            axes.set_xmargin(0)
            axes.set_autoscalex_on(True)
            axes.set_autoscaley_on(True)

            axes._grid = nvl(plot.grid, canvas.grid)
            toggle_grid(axes)

            if plot.title is not None:
                font_color = nvl(plot.font_color, canvas.font_color, 'black')
                font_size = nvl(plot.font_size, canvas.font_size)

                axes.set_title(plot.title, color=font_color, size=font_size)

            # If this is a stacked plot the X axis should be visible only on the bottom plot of the stack
            axes.get_xaxis()._hidden = not (True if stack_idx + 1 == len(plot.signals.values()) else False)
            toggle_axis(axes.get_xaxis())

            axes._plot_instance = plot

            for axis_idx in range(len(plot.axes)):
                if isinstance(plot.axes[axis_idx], Collection):
                    self.process_iplotlib_axis(canvas, plot, axis_idx, axes, plot.axes[axis_idx][stack_idx])
                else:
                    self.process_iplotlib_axis(canvas, plot, axis_idx, axes)

            for signal_idx, signal in enumerate(stack_signals):
                axes._signals.append(signal)
                self.mpl_axes[id(signal)] = axes
                self.refresh_signal(signal)

        # Register update callbacks after all stack signals have been created, maybe should be later extended
        if not canvas.streaming:
            for a in axes.get_shared_x_axes().get_siblings(axes):
                a.callbacks.connect('xlim_changed', axis_update_callback)
                a.callbacks.connect('ylim_changed', axis_update_callback)

        return axes.get_shared_x_axes().get_siblings(axes)

    def process_iplotlib_axis(self, canvas, plot, axis_idx, mpl_axes, axis=None):
        if axis is None:
            axis = plot.axes[axis_idx]

        font_color = nvl(axis.font_color, plot.font_color, canvas.font_color, 'black')
        font_size = nvl(axis.font_size, plot.font_size, canvas.font_size)

        mpl_axis = NanosecondHelper.mpl_get_axis(mpl_axes, axis_idx)

        if mpl_axis is not None:
            mpl_axis._font_color = font_color
            mpl_axis._font_size = font_size
            mpl_axis._label = axis.label

            label_attrs = dict(color=font_color)
            tick_attrs = dict(color=font_color, labelcolor=font_color)

            if font_size is not None:
                label_attrs['size'] = font_size
                tick_attrs['labelsize'] = font_size

            mpl_axis.set_label_text(axis.label, **label_attrs)
            mpl_axis.set_tick_params(**tick_attrs)

        if isinstance(axis, LinearAxis):
            if axis.is_date:
                mpl_axis.set_major_formatter(NanosecondDateFormatter())
                # mpl_axis.axes.tick_params(axis='x', which='major', labelrotation=5)

        if isinstance(axis, RangeAxis) and axis.begin is not None and axis.end is not None:
            logger.info(F"process_iplotlib_axis: setting {axis_idx} axis range to {axis.begin} and {axis.end}")
            NanosecondHelper.mpl_set_lim(mpl_axes, axis_idx, [axis.begin, axis.end])

    def get_signal_style(self, signal, plot=None, canvas=None):

        linestyle_lut = {"Solid": "solid", "Dashed": "dashed", "Dotted": "dotted", "None": "None"}
        styledata = dict()
        if signal.title:
            styledata['label'] = signal.title
        if hasattr(signal, "color"):
            styledata['color'] = signal.color

        styledata['linewidth'] = nvl_prop("line_size", signal, plot, canvas, default=1)
        # TODO fixme
        styledata['linestyle'] = nvl(linestyle_lut.get(signal.line_style), linestyle_lut.get(plot.line_style), linestyle_lut.get(canvas.line_style))
        styledata['marker'] = nvl_prop("marker", signal, plot, canvas)
        styledata['markersize'] = nvl_prop("marker_size", signal, plot, canvas, default=0)

        styledata["step"] = nvl_prop("step", signal, plot, canvas)
        return styledata

    def focus_plot(self, plot):
        self.focused_plot = plot
        self.process_iplotlib_canvas(self.canvas)

    def unfocus_plot(self):

        def get_x_axis_range(plot):
            if plot is not None and plot.axes is not None and len(plot.axes) > 0 and isinstance(plot.axes[0], RangeAxis):
                return plot.axes[0].begin, plot.axes[0].end

        def set_x_axis_range(plot, begin, end):
            if plot is not None and plot.axes is not None and len(plot.axes) > 0 and isinstance(plot.axes[0], RangeAxis):
                plot.axes[0].begin = begin
                plot.axes[0].end = end

        if self.focused_plot is not None:
            if self.canvas.shared_x_axis and len(self.focused_plot.axes) > 0 and isinstance(self.focused_plot.axes[0], RangeAxis):
                begin, end = get_x_axis_range(self.focused_plot)

                for columns in self.canvas.plots:
                    for plot in columns:
                        if plot != self.focused_plot:
                            logger.info(F"\t\tSetting range on plot {id(plot)} focused= {id(self.focused_plot)} begin={np.datetime64(begin, 'ns')}")
                            set_x_axis_range(plot, begin, end)

            self.focused_plot = None
            self.process_iplotlib_canvas(self.canvas)

    @_run_in_one_thread
    def process_work_queue(self):
        try:
            work_item = self.mpl_task_queue.get_nowait()
            work_item()
        except Empty:
            logger.info("Nothing to do.")

    def _redraw_in_frame_with_grid(self, a):
        """A copy of Axes.redraw_in_frame that fixes the problem of not drawing the grid since grid is treated as a part of the axes
        This function tries to hide all axis elements besides the grid itself before drawing"""
        with ExitStack() as stack:
            hide_elements = []
            for axis in [a.get_xaxis(), a.get_yaxis()]:
                hide_elements += [e for e in axis.get_children() if not (isinstance(e, Tick))]
                hide_elements += [a for e in axis.get_children() if isinstance(e, Tick) for a in e.get_children() if isinstance(a, Text)]

            for artist in [a.title, a._right_title, *hide_elements]:
                stack.callback(artist.set_visible, artist.get_visible())
                artist.set_visible(False)

            a.draw(a.figure._cachedRenderer)

    @_run_in_one_thread
    def refresh_signal(self, signal):
        """Should repaint what is needed after data for this signal has changed"""

        def group_data_units(axes, index):
            """Function that returns axis label made from signal units"""
            units = []
            if hasattr(axes, "_signals"):
                for s in axes._signals:
                    if hasattr(s, "units") and s.units is not None and len(s.units) >= index:
                        if s.units[index] is not None and len(s.units[index].strip()):
                            units.append(s.units[index] or '-')
            units = set(units) if len(set(units)) == 1 else units
            return '[{}]'.format(']['.join(units)) if len(units) else None

        def autosize_axis_from_data(axes, plot, signal, data, axis_idx):
            if all(e is not None for e in [axes, plot, data, plot.axes]):
                if len(plot.axes) > axis_idx and len(data) > axis_idx:
                    if len(data[axis_idx]) > 0:
                        if isinstance(plot.axes[axis_idx], RangeAxis):

                            new_axis_range = NanosecondHelper.mpl_get_lim(axes, axis_idx)
                            if plot.axes[axis_idx].begin is None:
                                new_axis_range = data[axis_idx][0], new_axis_range[1]
                            if plot.axes[axis_idx].end is None:
                                new_axis_range = new_axis_range[0], data[axis_idx][-1]

                            logger.info(F"AUTOSIZE axis {axis_idx} new range after data: {new_axis_range}")
                            NanosecondHelper.mpl_set_lim(axes, 0, new_axis_range)
                    else:
                        logger.info(F"AUTOSIZE: No data!")
                        if hasattr(signal, 'get_ranges'):
                            ranges = signal.get_ranges()
                            if ranges is not None and len(ranges) > axis_idx:
                                NanosecondHelper.mpl_set_lim(axes, axis_idx, ranges[axis_idx])


        def update_line(mpl_axes, signal):
            signal_data = signal.get_data()
            # autosize_axis_from_data(mpl_axes, mpl_axes._plot, signal, signal_data,0)
            # autosize_axis_from_data(mpl_axes, mpl_axes._plot, signal, signal_data, 1)
            if mpl_axes is not None:
                existing = self.mpl_shapes.get(id(signal))
                style = self.get_signal_style(signal, canvas=mpl_axes._canvas, plot=mpl_axes._plot)
                step = style.pop('step', None)
                data = NanosecondHelper.mpl_axes_transform_data(mpl_axes, signal_data)

                if existing is None:
                    params = dict(**style)
                    draw_function = mpl_axes.plot
                    if step is not None and step != "None":
                        params["where"] = step
                        draw_function = mpl_axes.step

                    line = draw_function(data[0], data[1], **params)
                    self.mpl_shapes[id(signal)] = [line]

                else:
                    existing[0][0].set_xdata(data[0])
                    existing[0][0].set_ydata(data[1])
                    mpl_axes.figure.canvas.draw()

        def update_envelope(mpl_axes, signal):
            signal_data = signal.get_data()
            # autosize_axis_from_data(mpl_axes, mpl_axes._plot, signal, signal_data)
            if mpl_axes is not None:
                existing = self.mpl_shapes.get(id(signal))
                style = self.get_signal_style(signal, canvas=mpl_axes._canvas, plot=mpl_axes._plot)
                step = style.pop('step', None)

                data = NanosecondHelper.mpl_axes_transform_data(mpl_axes, signal_data)

                if existing is None:

                    params = dict(**style)
                    draw_function = mpl_axes.plot
                    if step is not None and step != "None":
                        params["where"] = step
                        draw_function = mpl_axes.step

                    line = draw_function(data[0], data[1], **params)
                    params["color"] = params.get("color") or line[0].get_color()
                    params["label"] = '_nolegend_'
                    line2 = draw_function(data[0], data[2], **params)
                    area = mpl_axes.fill_between(data[0], data[1], data[2], alpha=0.3, color=params.get('color'), step=step)
                    self.mpl_shapes[id(signal)] = [line, line2, area]
                else:

                    existing[0][0].set_xdata(data[0])
                    existing[0][0].set_ydata(data[1])
                    existing[1][0].set_xdata(data[0])
                    existing[1][0].set_ydata(data[2])
                    existing[2].remove()
                    existing.pop()
                    existing.append(
                        mpl_axes.fill_between(data[0], data[1], data[2], alpha=0.3, color=existing[1][0].get_color(), step=step)
                    )
                    mpl_axes.figure.canvas.draw()

        if signal is None:
            return

        mpl_axes = self.mpl_axes.get(id(signal))

        if mpl_axes is not None:
            if hasattr(signal, "envelope") and signal.envelope:
                update_envelope(mpl_axes, signal)
            else:
                update_line(mpl_axes, signal)

            show_legend = nvl_prop("legend", signal, mpl_axes._plot, mpl_axes._canvas)
            if show_legend:
                #TODO: According to SO:50325907 calling legend may be delayed after tight_layout
                mpl_axes.legend(prop={'size': self.legend_size})

            if hasattr(signal, "units"):
                yaxis = mpl_axes.get_yaxis()
                if hasattr(yaxis, "_label") and not yaxis._label:
                    label = group_data_units(mpl_axes, 1)
                    if label:
                        yaxis.set_label_text(label)
        else:
            logger.error(f"Matplotlib AXES not found for signal {signal}. This should not happen. SIGNAL_ID: {id(signal)} AXES: {mpl_axes}")


    @_run_in_one_thread
    def refresh_data(self):
        for a in self.axes_update_set.copy():
            for signal in a._signals:
                self.refresh_signal(signal)
        self.axes_update_set.clear()


def get_data_range(data, axis_idx):
    """Returns first and last value from data[axis_idx] or None"""
    if data is not None and len(data) > axis_idx and len(data[axis_idx]>0):
        return (data[axis_idx][0], data[axis_idx][-1])
    return None

class MultiCursor2(MultiCursor):

    def __init__(self, canvas, axes, useblit=True, horizOn=False, vertOn=True, x_label=True, y_label=True, val_label=True, val_tolerance=0.05, text_color="white", font_size=8, **lineprops):

        self.canvas = canvas
        self.axes = axes
        self.horizOn = horizOn
        self.vertOn = vertOn
        self.x_label = x_label
        self.y_label = y_label
        self.value_label = val_label
        self.text_color = text_color
        self.font_size = font_size
        self.val_tolerance = val_tolerance  # Tolerance for showing label with value on signal in %

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

        axis_arrow_bbox_props = dict(boxstyle="round", pad=0.1, fill=True, color=lineprops["color"])
        axis_arrow_props = dict(annotation_clip=False, clip_on=False, bbox=axis_arrow_bbox_props, animated=self.useblit, color=self.text_color, fontsize=self.font_size)

        value_arrow_bbox_props = dict(boxstyle="round", pad=0.1, fill=True, color="green")
        value_arrow_props = dict(annotation_clip=False, clip_on=False, bbox=value_arrow_bbox_props, animated=self.useblit, color=self.text_color, fontsize=self.font_size)
        # value_arrow_props = dict(annotation_clip=False, animated=self.useblit, color=self.text_color, fontsize=self.font_size)

        if self.x_label:
            for ax in axes:
                xmin, xmax = ax.get_xbound()
                ymin, ymax = ax.get_ybound()
                x_arrow = Annotation("", (xmin + (xmax - xmin) / 2, ymin), verticalalignment="top", horizontalalignment="center", **axis_arrow_props)
                ax.add_artist(x_arrow)
                self.x_arrows.append(x_arrow)

        if self.y_label:
            for ax in axes:
                ymin, ymax = ax.get_ybound()
                xmin, xmax = ax.get_xbound()
                y_arrow = Annotation("", (xmin, ymin + (ymax - ymin) / 2), verticalalignment="center", horizontalalignment="right", **axis_arrow_props)
                ax.add_artist(y_arrow)
                self.y_arrows.append(y_arrow)

        if self.value_label:
            for ax in axes:
                if hasattr(ax, "_signals"):
                    for signal in ax._signals:
                        xmin, xmax = ax.get_xbound()
                        ymin, ymax = ax.get_ybound()
                        value_annotation = Annotation("", xy=(xmin + (xmax - xmin) / 2, ymin + (ymax - ymin) / 2), xycoords="data", # xytext=(-200, 0),
                                                      verticalalignment="top", horizontalalignment="left", **value_arrow_props)
                        value_annotation.set_visible(False)
                        value_annotation._signal = signal
                        ax.add_artist(value_annotation)
                        self.value_annotations.append(value_annotation)

        self.clear(None)  # Needs to be done for blitting to work. As it saves current background
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
                if hasattr(annotation, "_signal"):
                    annotation.set_visible(self.visible)
                    signal = annotation._signal
                    if signal is not None:
                        ax = annotation.axes

                        xvalue = NanosecondHelper.mpl_transform_value(ax.get_xaxis(), event.xdata)
                        values = signal.pick(xvalue)
                        logger.info(F"Found {values} for xvalue: {xvalue}")
                        if values is not None:
                            dx = abs(xvalue - values[0])
                            xmin, xmax = ax.get_xbound()
                            if dx < (xmax - xmin) * self.val_tolerance:
                                pos_x = NanosecondHelper.mpl_transform_value(ax.get_xaxis(), values[0], True)
                                pos_y = NanosecondHelper.mpl_transform_value(ax.get_yaxis(), values[1], True)
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


def nvl(*objs):
    """Returns first non-None value"""

    for o in objs:
        if o is not None:
            return o
    return None


def nvl_prop(prop_name, *objs, default=None):
    """Returns first not None property value from list of objects"""

    for o in objs:
        if hasattr(o, prop_name) and getattr(o, prop_name) is not None:
            return getattr(o, prop_name)
    return default


def toggle_axis(axis):
    """A function that hides an axis in a way that grid remains visible, by default in matplotlib the gird is treated as part of the axis
    :param axis: an axis instance ex: axes.get_xaxis()"""

    visible = not axis._hidden
    for e in axis.get_children():
        if not (isinstance(e, Tick)):
            e.set_visible(visible)
        else:
            e.tick1line.set_visible(visible)
            # e.tick2line.set_visible(visible)
            e.label1.set_visible(visible)  # e.label2.set_visible(visible)


def toggle_grid(axes):
    """A function that enables or disables grid according to the _grid attr. prepared for changing also other grid attrs in the future
    :param axes - an Axes instance"""

    if axes is not None and hasattr(axes, "_grid"):
        axes.grid(axes._grid)

class NanosecondHelper:


    @staticmethod
    def mpl_create_offset(vals):
        """Given a collection of values determine if creting offset is necessary and return it
        Returns None otherwise"""

        if isinstance(vals, Collection) and len(vals) > 0:
            if (hasattr(vals, 'dtype') and vals.dtype.name == 'int64') \
                    or (type(vals[0]) == int) \
                    or isinstance(vals[0], numpy.int64):
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
            begin = NanosecondHelper.mpl_transform_value(mpl_axis, limits[0], inverse=True)
            end = NanosecondHelper.mpl_transform_value(mpl_axis, limits[1], inverse=True)
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
                    logger.info(F"\tAPPLY DATA OFFSET {mpl_axis._offset} to axis {id(mpl_axis)} idx: {i}")
                    if isinstance(d, Collection):
                        ret.append([e - mpl_axis._offset for e in d])
                    else:
                        ret.append(d - mpl_axis._offset)
                else:
                    ret.append(d)
        return ret


class ConversionHelper:

    @staticmethod
    def toInt(value):
        return ConversionHelper.toNumber(value, int)

    @staticmethod
    def toFloat(value):
        return ConversionHelper.toNumber(value, float)

    @staticmethod
    def toNumber(value, type_func):
        if isinstance(value, type_func):
            return value
        if isinstance(value, str):
            return type_func(value)
        if type(value).__module__ == 'numpy':
            return type_func(value.item())

    @staticmethod
    def asType(value, to_type):
        if to_type is not None and hasattr(to_type, '__name__'):
            if to_type == type(value):
                return value
            if to_type.__name__ == 'float64' or to_type.__name__ == 'float':
                return ConversionHelper.toFloat(value)
            if to_type.__name__ == 'int64' or to_type.__name__ == 'int':
                return ConversionHelper.toInt(value)

        return value
