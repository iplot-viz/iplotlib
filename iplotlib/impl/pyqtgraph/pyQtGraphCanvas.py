# Changelog:
#   Jan 2023:   -Added support for legend position and layout [Alberto Luengo]

from typing import Any, Callable, Collection, List, Tuple
import pyqtgraph as pg
from pyqtgraph.Qt import QtCore

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

from iplotlib.impl.matplotlib.iplotMultiCursor import IplotMultiCursor
from pyqtgraph import PlotItem, AxisItem, PlotDataItem

logger = setupLogger.get_logger(__name__)
# Mapa de estilos de línea de matplotlib → QtCore.Qt.PenStyle
LINESTYLE_MAP = {
    'solid': QtCore.Qt.PenStyle.SolidLine,
    'dashed': QtCore.Qt.PenStyle.DashLine,
    'dashdot': QtCore.Qt.PenStyle.DashDotLine,
    'dotted': QtCore.Qt.PenStyle.DotLine,
}

# Mapa de pasos a stepMode de PlotDataItem
STEP_MAP_PG = {
    'linear': False,
    'post': True
}


class PyQtGraphParser(BackendParserBase):
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

        self.figure = pg.GraphicsLayoutWidget()
        self._layout = {}
        self._impl_plot_ranges_hash = dict()

        if tight_layout:
            self.enable_tight_layout()
        else:
            self.disable_tight_layout()

    def export_image(self, filename: str, **kwargs):
        super().export_image(filename, **kwargs)

    def legend_downsampled_signal(self, signal, mpl_axes, plot_lines):
        """
        Add or removes a '*' in the legend label to indicate if the signal is downsampled or not
        """
        pass

    def do_line_plot_xy(self, signal: SignalXY, plot: PlotItem, i_plot: PlotXY, cache_item, x_data, y_data):
        def _get_visible_data(xd, yd, lo, hi):
            x_displayed = xd[((xd > lo) & (xd < hi))]
            y_displayed = yd[((xd > lo) & (xd < hi))]
            return x_displayed, y_displayed

        def _update_marker_by_point_count(marker_line: Any, signal_x_data, signal_style: dict):
            if len(signal_x_data) == 1:
                marker_line.set_marker('x')
                marker_line.set_markersize(5)
            else:
                marker_line.set_marker(signal_style.get('marker') or "")
                marker_line.set_markersize(signal_style.get('markersize'))

        plot_lines = self._signal_impl_shape_lut.get(id(signal))  # type: List[List[PlotDataItem]]
        style = self.get_signal_style(signal)
        draw_fn = plot.plot
        # Reflect downsampling in legend
        self.legend_downsampled_signal(signal, plot, plot_lines)

        # Review to implement directly in PlotXY class
        if signal.color is None:
            # It means that the color has been reset but must keep the original color
            signal.color = signal.original_color

        # Visible data is adjusted based on extremities, but only for unprocessed signals.
        # Processed signals already use the visible range.
        # Skip this step in case of streaming mode, as x_data and y_data may be empty and lead to errors.
        # TODO if not signal.extremities and signal.x_expr == "${self}.time" and not self.canvas.streaming:
        #     x_data, y_data = _get_visible_data(x_data, y_data, *self.get_impl_x_axis_limits(plot))

        if isinstance(plot_lines, list):
            if x_data.ndim == 1 and y_data.ndim == 1:
                line = plot_lines[0][0]
                self.set_line_data(style, line, x_data, y_data)
                self.set_line_style(style, line)
                # _update_marker_by_point_count(line, x_data, style)
            elif x_data.ndim == 1 and y_data.ndim == 2:
                for i, line in enumerate(plot_lines):
                    line[0].setData(x=x_data, y=y_data[:, i])
                    line[0].setPen(style['pen'])
                    # _update_marker_by_point_count(line[0], x_data, style)

            # Put this out in a method only for streaming
            if self.canvas.streaming:
                ax_window = plot.get_xlim()[1] - plot.get_xlim()[0]
                all_y_data = []
                for signal in i_plot.signals[cache_item.stack_key]:
                    if signal.lines[0][0].get_visible() and len(signal.x_data) > 0:
                        max_x_data = signal.x_data.max()[0]
                        for x_temp, y_temp in zip(signal.x_data, signal.y_data):
                            if max_x_data - ax_window <= x_temp <= max_x_data:
                                all_y_data.append(y_temp)
                if all_y_data:
                    diff = (max(all_y_data) - min(all_y_data)) / 15
                    plot.set_ylim(min(all_y_data) - diff, max(all_y_data) + diff)
                plot.set_xlim(max(x_data) - ax_window, max(x_data))
            # Preserve visible status for lines
            for new, old in zip(plot_lines, signal.lines):
                for n, o in zip(new, old):
                    n.setVisible(o.isVisible())
        else:
            if x_data.ndim == 1 and y_data.ndim == 1:
                plot_lines = [[draw_fn(x_data, y_data, **style)]]
                # _update_marker_by_point_count(plot_lines[0], x_data, style)
            elif x_data.ndim == 1 and y_data.ndim == 2:
                lines = draw_fn(x_data, y_data, **style)
                plot_lines = [[line] for line in lines]
                for i, line in enumerate(plot_lines):
                    line[0].set_label(f"{signal.label}[{i}]")
                    # _update_marker_by_point_count(line[0], x_data, style)

        signal.lines = plot_lines

        return plot_lines

    def set_line_data(self, style: dict, line: PlotDataItem, x_data, y_data):
        """
        Set the data for a PlotDataItem based on the attributes of SignalXY.
        """
        line.setData(x=x_data, y=y_data, stepMode=style['stepMode'])

        # Update the line style after setting the data
        self.set_line_style(style, line)

    @staticmethod
    def set_line_style(style: dict, line: PlotDataItem):
        """
        Set the line style for a PlotDataItem based on the attributes of SignalXY.
        """
        line.setPen(style['pen'])
        if 'symbol' in style and style['symbol'] is not None:
            # Set the symbol and size if specified
            line.setSymbol(style['symbol'])
            line.setSymbolSize(style['symbolSize'])

    def get_signal_style(self, signal: SignalXY) -> dict:
        """
        Retorna un dict de argumentos para PlotDataItem en PyQtGraph
        a partir de los atributos de SignalXY.
        """
        style = {'name': signal.label}

        color = self._pm.get_value(signal, 'color')
        line_size = self._pm.get_value(signal, 'line_size')
        line_style = (self._pm.get_value(signal, 'line_style') or 'solid').lower()
        if line_size == 0 or line_style == 'none':
            pen = None
        else:
            pen = pg.mkPen(
                color=color,
                width=line_size,
                style=LINESTYLE_MAP.get(line_style, QtCore.Qt.PenStyle.SolidLine)
            )
        style['pen'] = pen

        marker = self._pm.get_value(signal, 'marker')
        if marker:
            style['symbol'] = self._pm.get_value(signal, 'marker')
            style['symbolSize'] = self._pm.get_value(signal, 'marker_size')

        step = self._pm.get_value(signal, 'step') or 'linear'
        step_mode = STEP_MAP_PG.get(step)
        style['stepMode'] = step_mode

        return style

    def do_line_plot_xy_slider(self, signal: SignalXY, mpl_axes: PlotItem, plot: PlotXYWithSlider, cache_item,
                               x_data, y_data, z_data):
        pass

    def do_line_plot_contour(self, signal: SignalContour, mpl_axes: PlotItem, plot: PlotContour, x_data, y_data,
                             z_data):
        pass

    def do_envelope_plot(self, signal: Signal, mpl_axes: PlotItem, x_data, y1_data, y2_data):
        pass

    def set_suptitle(self, title: str, font_size: int = None, font_color: str = 'black'):
        suptitle = pg.LabelItem(justify='center')
        self.figure.addItem(suptitle, row=0, col=0, colspan=3)
        suptitle.setText("Título general (suptitle)", size='16pt', bold=True)

    def set_impl_plot_limits(self, impl_plot: Any, ax_idx: int, limits: tuple) -> bool:
        pass

    def _get_all_shared_axes(self, base_mpl_axes: PlotItem):
        pass

    def process_ipl_plot_xy(self):
        pass

    def process_ipl_plot_contour(self):
        pass

    def process_ipl_plot_xy_slider(self, plot_with_slider: PlotXYWithSlider, grid_item: Any, stack_sz: int,
                                   h_space: float):
        pass

    def process_ipl_plot(self, i_plot: Plot, col: int, row: int):
        if not isinstance(i_plot, Plot):
            return

        full_mode_all_stack = self._pm.get_value(self.canvas, 'full_mode_all_stack')

        plot = None
        prev_plot = None
        for stack_id, key in enumerate(sorted(i_plot.signals.keys())):
            is_stack_plot_focused = self._focus_plot_stack_key == key

            if not full_mode_all_stack and self._focus_plot_stack_key is not None and not is_stack_plot_focused:
                continue
            signals = i_plot.signals.get(key) or list()

            if not full_mode_all_stack and self._focus_plot_stack_key is not None:
                row_id = 0
            else:
                row_id = stack_id
            key = (row, col)
            if key not in self._layout:
                plot = pg.PlotItem()
                self.figure.addItem(plot, row=row, col=col, rowspan=i_plot.row_span, colspan=i_plot.col_span)
                self._layout[key] = plot
            plot = self._layout[key]
            prev_plot = plot
            self._plot_impl_plot_lut[id(i_plot)].append(plot)
            # Keep references to iplotlib instances for ease of access in callbacks.
            self._impl_plot_cache_table.register(plot, self.canvas, i_plot, key, signals)
            plot.enableAutoRange(x=True, y=True)

            # Set the plot title
            self.set_plot_title(i_plot, plot, stack_id)

            # Set the grid
            grid = self._pm.get_value(i_plot, 'grid')
            self.set_grid(plot, grid)

            # Set the background color
            self.set_background_color(i_plot, plot)

            self.process_legend_plot(plot, i_plot, signals)
            # Update properties of the plot axes
            for ax_idx in range(len(i_plot.axes)):
                if isinstance(i_plot.axes[ax_idx], Collection):
                    y_axis = i_plot.axes[ax_idx][stack_id]
                    self.process_ipl_axis(y_axis, ax_idx, i_plot, plot)
                else:
                    x_axis = i_plot.axes[ax_idx]
                    self.process_ipl_axis(x_axis, ax_idx, i_plot, plot)

            for signal in signals:
                # self._signal_impl_plot_lut.update({id(signal): mpl_axes})
                self._signal_impl_plot_lut.update({signal.uid: plot})
                self.process_ipl_signal(signal)

    def set_plot_title(self, i_plot: Plot, plot: PlotItem, stack_id: int):
        if i_plot.plot_title is None or stack_id != 0:
            return
        fc = self._pm.get_value(i_plot, 'font_color')
        fs = self._pm.get_value(i_plot, 'font_size')
        plot.setTitle(i_plot.plot_title, color=fc, size=fs)

    def set_background_color(self, i_plot: Plot, plot: PlotItem):
        background_color = self._pm.get_value(i_plot, 'background_color')
        plot.getViewBox().setBackgroundColor(background_color)

    def process_legend_plot(self, plot: PlotItem, i_plot: Plot, signals):
        def set_legend_position(legend, position):
            pos_map = {
                'upper left': ((0, 0), (0, 0)),
                'upper center': ((0.5, 0), (0.5, 0)),
                'upper right': ((1, 0), (1, 0)),
                'center left': ((0, 0.5), (0, 0.5)),
                'center': ((0.5, 0.5), (0.5, 0.5)),
                'center right': ((1, 0.5), (1, 0.5)),
                'lower left': ((0, 1), (0, 1)),
                'lower center': ((0.5, 1), (0.5, 1)),
                'lower right': ((1, 1), (1, 1)),
            }
            legend.anchor(pos_map[position][0], pos_map[position][1])

        def set_legend_layout(legend, layout_type: str):
            grid = legend.layout
            items = []
            for row in range(grid.rowCount()):
                for col in range(grid.columnCount()):
                    item = grid.itemAtPosition(row, col)
                    if item:
                        items.append(item)
            # limpiar
            for item in items:
                grid.removeItem(item)
            # recolocar
            if layout_type.lower() == 'vertical':
                for i, item in enumerate(items):
                    grid.addItem(item, i, 0)
            else:  # horizontal
                for i, item in enumerate(items):
                    grid.addItem(item, 0, i)

        # Show the plot legend if enabled
        show_legend = self._pm.get_value(i_plot, 'legend')
        if not show_legend:
            plot.legend = None
            return

        plot.addLegend()
        legend = plot.legend

        leg_position = self._pm.get_value(i_plot, 'legend_position')
        set_legend_position(legend, leg_position)
        # leg_layout = self._pm.get_value(plot, 'legend_layout')
        # set_legend_layout(legend, leg_layout)

    def _update_slider(self, val, plot, slider_values, current_label, formatter):
        pass

    def _axis_update_callback(self, mpl_axes):
        pass

    def process_ipl_axis(self, axis: Axis, ax_idx, plot: Plot, impl_plot: PlotItem):
        pass

    @BackendParserBase.run_in_one_thread
    def process_ipl_signal(self, signal: Signal):
        if not isinstance(signal, Signal):
            return

            # plot = self._signal_impl_plot_lut.get(id(signal))  # type: PlotItem
        plot = self._signal_impl_plot_lut.get(signal.uid)  # type: PlotItem
        if not isinstance(plot, PlotItem):
            logger.error(f"MPLAxes not found for signal {signal}. Unexpected error. signal_id: {id(signal)}")
            return

        # All good, make a data access request.
        # logger.debug(f"\tprocessipsignal before ts_start {signal.ts_start} ts_end {signal.ts_end}
        # status: {signal.status_info.result} ")
        signal_data = signal.get_data()

        data = self.transform_data(plot, signal_data)

        if hasattr(signal, 'envelope') and signal.envelope:
            if len(data) != 3:
                logger.error(f"Requested to draw envelope for sig({id(signal)}), but it does not have sufficient data"
                             f" arrays (==3). {signal}")
                return
            self.do_envelope_plot(signal, plot, data[0], data[1], data[2])
        else:
            if len(data) < 2:
                logger.error(f"Requested to draw line for sig({id(signal)}), but it does not have sufficient data "
                             f"arrays (<2). {signal}")
                return
            self.do_line_plot(signal, plot, data)

        self.update_axis_labels_with_units(plot, signal)

        # Check for annotations if the marker labels are visible
        return  # TODO remove
        if isinstance(signal, SignalXY):
            if plot.dataItems[0].scatter.opts.get('symbol') == 'None':
                return
            if signal.markers_list:
                annotations_names = [child.get_text() for child in plot.get_children() if
                                     isinstance(child, plt.Annotation)]
                for marker in signal.markers_list:
                    if marker.visible:
                        # Check if the marker is already drawn
                        if marker.name not in annotations_names:
                            x = self.transform_value(plot, 0, marker.xy[0], inverse=True)
                            y = marker.xy[1]
                            plot.annotate(text=marker.name,
                                          xy=(x, y),
                                          xytext=(x, y),
                                          bbox=dict(boxstyle="round,pad=0.3", edgecolor="black",
                                                    facecolor=marker.color))

    def do_line_plot(self, signal: Signal, plot: PlotItem, data: List[BufferObject]):

        cache_item = self._impl_plot_cache_table.get_cache_item(plot)
        i_plot = cache_item.plot()
        plot_lines = None
        if isinstance(signal, SignalXY):
            if isinstance(i_plot, PlotXYWithSlider):
                plot_lines = self.do_line_plot_xy_slider(signal, plot, i_plot, cache_item, data[0], data[1],
                                                         data[2])
            else:
                plot_lines = self.do_line_plot_xy(signal, plot, i_plot, cache_item, data[0], data[1])
        elif isinstance(signal, SignalContour):
            plot_lines = self.do_line_plot_contour(signal, plot, i_plot, data[0], data[1], data[2])

        self._signal_impl_shape_lut.update({id(signal): plot_lines})

    def clear(self):
        """
        Set the canvas gridspec for the figure.
        """
        self._layout = {}
        # TODO improve this
        for item in self.figure.items()[:]:
            try:
                # Solo intentar remover PlotItems y LegendItems
                if isinstance(item, (pg.PlotItem, pg.LegendItem)):
                    self.figure.removeItem(item)
            except Exception:
                pass

    @staticmethod
    def set_grid(plot: PlotItem, grid: bool = True):
        """
        Enable or disable the grid for the given plot.
        """
        plot.showGrid(x=grid, y=grid)

    def autoscale_y_axis(self, impl_plot, margin=0.1):
        pass

    def set_impl_plot_slider_limits(self, plot: PlotXYWithSlider, start, end):
        pass

    def update_slider_limits(self, plot: PlotXYWithSlider, begin, end):
        pass

    def enable_tight_layout(self):
        pass

    def disable_tight_layout(self):
        pass

    def set_focus_plot(self, mpl_axes):
        pass

    @BackendParserBase.run_in_one_thread
    def activate_cursor(self):
        pass

    @BackendParserBase.run_in_one_thread
    def deactivate_cursor(self):
        pass

    def get_impl_x_axis(self, plot: PlotItem) -> AxisItem:
        return plot.getAxis('left')

    def get_impl_x_axis_limits(self, plot: PlotItem) -> Tuple[float, float]:
        return plot.getViewBox().viewRange()[0]

    def get_impl_y_axis(self, plot: PlotItem) -> AxisItem:
        return plot.getAxis('bottom')

    def get_impl_y_axis_limits(self, plot: PlotItem) -> AxisItem:
        return plot.getViewBox().viewRange()[1]

    def get_oaw_axis_limits(self):
        pass

    def set_impl_x_axis_label_text(self):
        pass

    def set_impl_x_axis_limits(self):
        pass

    def set_impl_y_axis_label_text(self):
        pass

    def set_impl_y_axis_limits(self):
        pass

    def set_oaw_axis_limits(self):
        pass

    def transform_data(self, plot: PlotItem, data) -> List[Any]:
        # TODO
        return data

    def transform_value(self):
        pass
