# Changelog:
#   Jan 2023:   -Added support for legend position and layout [Alberto Luengo]
import datetime
import numpy as np
from typing import Any, Callable, Collection, List, Tuple
import pyqtgraph as pg
from pyqtgraph import IsocurveItem
from pyqtgraph.Qt import QtCore, QtWidgets

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

from pyqtgraph import PlotItem, AxisItem, PlotDataItem

from iplotlib.impl.pyqtgraph.pyQtCrosshair import pyQtCrosshair

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


class FechaPyQtGraph(pg.AxisItem):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def tickStrings(self, values, scale, spacing):
        formatted_dates = []
        for val in values:
            try:
                timestamp = val / 1e9
                date_str = datetime.datetime.fromtimestamp(timestamp, datetime.UTC).strftime('%Y-%m-%d %H:%M:%S')
                formatted_dates.append(date_str)
            except Exception:
                formatted_dates.append(str(val))
        return formatted_dates


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
        self.figure.setBackground('w')
        self._layout = {}
        self._cell_gl = {}  # (row, col) -> GraphicsLayout sublayout
        self._layout_stacks = {}  # (row, col, stack_id) -> PlotItem
        self._impl_plot_ranges_hash = dict()

        if tight_layout:
            self.enable_tight_layout()
        else:
            self.disable_tight_layout()

    def _ensure_cell_layout(self, row: int, col: int, rowspan: int, colspan: int):
        key = (row, col)
        cell_gl = self._cell_gl.get(key)
        if cell_gl is None:
            cell_gl = pg.GraphicsLayout()
            # sublayout anclado a (row, col) con spans reales
            self.figure.addItem(cell_gl, row=row, col=col, rowspan=rowspan, colspan=colspan)
            self._cell_gl[key] = cell_gl
        return cell_gl

    def export_image(self, filename: str, **kwargs):
        super().export_image(filename, **kwargs)

    def legend_downsampled_signal(self, signal, mpl_axes, plot_lines):
        """
        Add or removes a '*' in the legend label to indicate if the signal is downsampled or not
        """
        pass

    def do_impl_line_plot_xy(self, signal: SignalXY, plot: PlotItem, i_plot: PlotXY, cache_item, x_data, y_data):
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
                # usar ViewBox en PyQtGraph
                vb = plot.getViewBox()
                (x_lo, x_hi), (y_lo, y_hi) = vb.viewRange()
                ax_window = x_hi - x_lo

                all_y_data = []
                for s in i_plot.signals[cache_item.stack_key]:
                    if s.lines[0][0].get_visible() and len(s.x_data) > 0:
                        max_x_data = s.x_data.max()[0]
                        for x_temp, y_temp in zip(s.x_data, s.y_data):
                            if max_x_data - ax_window <= x_temp <= max_x_data:
                                all_y_data.append(y_temp)

                if all_y_data:
                    diff = (max(all_y_data) - min(all_y_data)) / 15
                    vb.setYRange(min(all_y_data) - diff, max(all_y_data) + diff, padding=0)

                # desplaza la ventana X al último tramo visible
                vb.setXRange(float(max(x_data) - ax_window), float(max(x_data)), padding=0)

            # Preserve visible status for lines
            for new, old in zip(plot_lines, signal.lines):
                for n, o in zip(new, old):
                    n.setVisible(o.isVisible())
        else:
            if x_data.ndim == 1 and y_data.ndim == 1:
                plot_lines = [draw_fn(x=x_data, y=y_data, **style)]
                # _update_marker_by_point_count(plot_lines[0], x_data, style)
            elif x_data.ndim == 1 and y_data.ndim == 2:
                lines = plot.plot(x=x_data, y=y_data, **style)
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

    def do_impl_line_plot_xy_slider(self, signal: SignalXY, mpl_axes: PlotItem, plot: PlotXYWithSlider, cache_item,
                                    x_data, y_data, z_data):
        pass

    def do_impl_line_plot_contour(self, signal: SignalContour, plot_item: PlotItem, plot: PlotContour, x_data, y_data,
                                  z_data):
        plot_lines = self._signal_impl_shape_lut.get(id(signal))  # type: List[IsocurveItem]
        contour_filled = self._pm.get_value(plot, 'contour_filled')
        legend_format = self._pm.get_value(plot, "legend_format")
        equivalent_units = self._pm.get_value(plot, "equivalent_units")
        contour_levels = self._pm.get_value(signal, 'contour_levels')
        color_map = self._pm.get_value(signal, 'color_map')

        curves = []

        if isinstance(plot_lines, IsocurveItem):
            for tp in plot_lines.collections:
                tp.remove()

            if contour_filled:
                pass
                # draw_fn = mpl_axes.contourf
            else:
                img = pg.ImageItem(z_data)

            if x_data.ndim == y_data.ndim == z_data.ndim == 2:
                plot_item.addItem(img)
                bar = pg.ColorBarItem(values=(np.min(z_data), np.max(z_data)),
                                      colorMap=pg.colormap.get(color_map),
                                      label='Z value',
                                      interactive=False)
                bar.setImageItem(img)

                for idx, v in enumerate(contour_levels):
                    # Colores de las isocurvas
                    norm_values = (v - np.min(z_data)) / (np.max(z_data) - np.min(z_data))
                    color = color_map.map(norm_values, mode='float')
                    color_rgba = tuple(int(c * 255) for c in color)
                    pen_color = pg.mkColor(color_rgba)
                    pen = pg.mkPen(color=pen_color, width=2)

                    iso_curve = pg.IsocurveItem(data=z_data, level=v, pen=pen)
                    iso_curve.setParentItem(img)
                    plot_item.addItem(iso_curve)
                    curves.append(iso_curve)

                # plot_lines = draw_fn(x_data, y_data, z_data, levels=contour_levels, cmap=color_map)

                # if legend_format == 'in_lines':
                # if not contour_filled:
                # plt.clabel(plot_lines, inline=1, fontsize=10)
            # if equivalent_units:
            # mpl_axes.set_aspect('equal', adjustable='box')
            # self.figure.canvas.draw_idle()
        else:
            if contour_filled:
                # draw_fn = mpl_axes.contourf
                pass
            else:
                # draw_fn = mpl_axes.contour
                img = pg.ImageItem(z_data)
                # img.setRect(QtCore.QRectF(np.min(x_data)[0], np.min(y_data)[0], np.ptp(x_data), np.ptp(y_data)))
                plot_item.addItem(img)

            if x_data.ndim == y_data.ndim == z_data.ndim == 2:
                # plot_lines = draw_fn(x_data, y_data, z_data, levels=contour_levels, cmap=color_map)

                colormap_obj = pg.colormap.get('viridis')
                bar = pg.ColorBarItem(values=(np.min(z_data)[0], np.max(z_data)[0]),
                                      colorMap=colormap_obj,
                                      label='Z value',
                                      interactive=False)
                bar.setImageItem(img)
                levels = np.linspace(np.min(z_data)[0], np.max(z_data)[0], contour_levels)

                for i, v in enumerate(levels):
                    """
                    # Colores de las isocurvas
                    norm_values = (v - np.min(z_data)) / (np.max(z_data) - np.min(z_data))
                    color = colormapp.map(norm_values, mode='float')
                    color_rgba = tuple(int(c * 255) for c in color) 
                    pen_color = pg.mkColor(color_rgba)
                    pen = pg.mkPen(color=pen_color, width=2)
                    """

                    iso_curve = pg.IsocurveItem(data=z_data, level=v, pen=(i, len(levels) * 1.5))
                    # Scaled data
                    """
                    scale_x = np.ptp(x_data) / z_data.shape[1]
                    scale_y = np.ptp(y_data) / z_data.shape[0]
                    iso_curve.setTransform(
                        pg.Qt.QtGui.QTransform().scale(scale_x, scale_y).translate(np.min(x_data)[0] / scale_x,
                                                                                   np.min(y_data)[0] / scale_y))
                    """
                    iso_curve.setParentItem(img)
                    iso_curve.setZValue(10)

                    plot_item.addItem(iso_curve)
                    curves.append(iso_curve)

                # if legend_format == 'color_bar':
                # color_bar = self.figure.colorbar(plot_lines, ax=mpl_axes, location='right')
                # color_bar.set_label(z_data.unit, size=self.legend_size)
                # else:
                # if not contour_filled:
                # plt.clabel(plot_lines, inline=1, fontsize=10)
            # if equivalent_units:
            # mpl_axes.set_aspect('equal', adjustable='box')

        return curves

    def do_impl_envelope_plot(self, signal: Signal, mpl_axes: PlotItem, x_data, y1_data, y2_data):
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

        if not hasattr(self, "_layout_stacks"):
            self._layout_stacks = {}

        full_mode_all_stack = self._pm.get_value(self.canvas, 'full_mode_all_stack')

        cell_gl = self._ensure_cell_layout(row, col, i_plot.row_span, i_plot.col_span)

        plot = None
        prev_plot = None
        visible_row_ids = []
        for stack_id, key in enumerate(sorted(i_plot.signals.keys())):
            is_stack_plot_focused = self._focus_plot_stack_key == key

            if not full_mode_all_stack and self._focus_plot_stack_key is not None and not is_stack_plot_focused:
                continue
            signals = i_plot.signals.get(key) or list()

            if not full_mode_all_stack and self._focus_plot_stack_key is not None:
                row_id = 0
            else:
                row_id = stack_id
            visible_row_ids.append(row_id)
            key = (row, col)

            k_stack = (row, col, row_id)
            if key not in self._layout:
                plot = pg.PlotItem()
                cell_gl.addItem(plot, row=0, col=0)
                self._layout[key] = plot
                self._layout_stacks[k_stack] = plot
            elif k_stack not in self._layout_stacks:
                pi = pg.PlotItem()
                cell_gl.addItem(pi, row=row_id, col=0)
                pi.setXLink(self._layout[key])
                pi.getAxis('bottom').setStyle(showValues=False)
                self._layout_stacks[k_stack] = pi

            plot = self._layout_stacks[k_stack]
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

            # Set mouse interaction
            self.set_mouse(plot)

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

        if visible_row_ids:
            for rid in set(visible_row_ids):
                self._layout_stacks[(row, col, rid)].getAxis('bottom').setStyle(showValues=False)
            last_row_id = max(visible_row_ids)
            self._layout_stacks[(row, col, last_row_id)].getAxis('bottom').setStyle(showValues=True)

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

        # Set aspect legend
        legend.setBrush(pg.mkBrush('w'))
        legend.setPen(pg.mkPen(color='k'))

    def _update_slider(self, val, plot, slider_values, current_label, formatter):
        pass

    def _axis_update_callback(self, mpl_axes):
        pass

    def process_ipl_log_axis(self, axis_item: AxisItem, plot: Plot):
        if axis_item.orientation == 'left':
            log_scale = self._pm.get_value(plot, 'log_scale')
            if log_scale:
                # Set log scale for AxisItem
                pass

    def process_ipl_axis_params(self, fc, fs, axis: Axis, axis_item: AxisItem):
        label_props = dict(maxTickLevel=0)

        # Set ticks on the top and right axis
        if self._pm.get_value(self.canvas, 'ticks_position'):
            label_props['maxTickLevel'] = 2
        else:
            label_props['maxTickLevel'] = 0

        if axis.label is not None:
            axis_item.setLabel(axis.label)

        # axis_item.set_tick_params(**tick_props)
        axis_item.setStyle(**label_props)

    def process_ipl_axis_formatter(self, impl_plot: PlotItem, axis_item: AxisItem, ax_idx: int):
        ci = self._impl_plot_cache_table.get_cache_item(impl_plot)
        """
        mpl_axis.set_major_formatter(NanosecondDateFormatter(ax_idx,
                                                             offset_lut=ci.offsets,
                                                             roundh=self._pm.get_value(self.canvas, 'round_hour')))
        """
        return

    def process_ipl_axis_ticks(self, tick_number, axis_item: AxisItem):
        # axis_item.setStyle()
        return

    def process_ipl_signal_impl_plot(self, signal: Signal):
        plot = self._signal_impl_plot_lut.get(signal.uid)  # type: PlotItem
        if not isinstance(plot, PlotItem):
            logger.error(f"PlotItem not found for signal {signal}. Unexpected error. signal_id: {id(signal)}")
            return
        return plot

    def process_ipl_signal_annotations(self, signal: Signal, impl_plot: PlotItem):
        return

        if isinstance(signal, SignalXY):
            if impl_plot.get_lines()[0].get_marker() == 'None':
                return
            if signal.markers_list:
                annotations_names = [child.get_text() for child in impl_plot.get_children() if
                                     isinstance(child, plt.Annotation)]
                for marker in signal.markers_list:
                    if marker.visible:
                        # Check if the marker is already drawn
                        if marker.name not in annotations_names:
                            x = self.transform_value(impl_plot, 0, marker.xy[0], inverse=True)
                            y = marker.xy[1]
                            impl_plot.annotate(text=marker.name,
                                               xy=(x, y),
                                               xytext=(x, y),
                                               bbox=dict(boxstyle="round,pad=0.3",
                                                         edgecolor="black",
                                                         facecolor=marker.color))

    def clear(self):
        """
        Set the canvas gridspec for the figure.
        """
        super().clear()
        self._layout = {}
        self._cell_gl = {}
        self._layout_stacks = {}
        # Elimina items relevantes del GraphicsLayoutWidget
        for item in self.figure.items()[:]:
            try:
                if isinstance(item, (
                        pg.PlotItem,
                        pg.LegendItem,
                        pg.ImageItem,
                        pg.GraphicsLayout,  # sublayouts por celda
                        QtWidgets.QGraphicsProxyWidget  # sliders/otros QWidget embebidos
                )):
                    self.figure.removeItem(item)
            except Exception:
                pass

    @staticmethod
    def set_grid(plot: PlotItem, grid: bool = True):
        """
        Enable or disable the grid for the given plot.
        """
        plot.showGrid(x=grid, y=grid)

    @staticmethod
    def set_mouse(plot: PlotItem):
        vb = plot.vb
        vb.setMouseEnabled(x=False, y=False)

    def set_view_box(self):
        for plot in list(self._layout.values()) + list(self._layout_stacks.values()):
            if not plot:
                continue
            vb = plot.vb
            vb.setMouseMode(vb.PanMode)
            vb.enableAutoRange(x=True, y=True)
            vb.setMouseEnabled(x=True, y=True)

    def set_view_box_zoom(self):
        for plot in list(self._layout.values()) + list(self._layout_stacks.values()):
            if not plot:
                continue
            vb = plot.vb
            vb.setMouseMode(vb.RectMode)
            vb.enableAutoRange(x=False, y=False)
            vb.setAspectLocked(False)
            vb.setLimits(minXRange=1e-9, minYRange=1e-12)
            vb.setMouseEnabled(x=True, y=True)

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
        for plot in self._layout.values():
            if not plot:
                continue

            self._cursors.append(pyQtCrosshair(plot))

    @BackendParserBase.run_in_one_thread
    def deactivate_cursor(self):
        pass

    def get_impl_x_axis(self, plot: PlotItem) -> AxisItem:
        return plot.getAxis('bottom')

    def get_impl_x_axis_limits(self, plot: PlotItem) -> Tuple[float, float]:
        return plot.getViewBox().viewRange()[0]

    def get_impl_y_axis(self, plot: PlotItem) -> AxisItem:
        return plot.getAxis('left')

    def get_impl_y_axis_limits(self, plot: PlotItem) -> AxisItem:
        return plot.getViewBox().viewRange()[1]

    def set_impl_x_axis_label_text(self, plot: PlotItem, text: str):
        # self.get_impl_x_axis(plot).set_label_text(text)
        pass

    def set_impl_x_axis_limits(self, plot: PlotItem, limits: tuple):
        if isinstance(plot, PlotItem):
            vb = plot.getViewBox()
            vb.setXRange(limits[0], limits[1], padding=0)

    def set_impl_y_axis_label_text(self, plot: PlotItem, text: str):
        """Implementations should set the y_axis label text"""
        # self.get_impl_y_axis(plot).set_label_text(text)
        pass

    def set_impl_y_axis_limits(self, plot: PlotItem, limits: tuple):
        if isinstance(plot, PlotItem):
            vb = plot.getViewBox()
            vb.setYRange(limits[0], limits[1], padding=0)

    def transform_data(self, plot: PlotItem, data) -> List[Any]:
        """This function post processes data if it cannot be plotted with matplotlib directly.
                Currently, it transforms data if it is a large integer which can cause overflow in matplotlib"""
        ret = []
        if isinstance(data, Collection):
            ci = self._impl_plot_cache_table.get_cache_item(plot)
            for i, d in enumerate(data):
                logger.debug(f"\t transform data i={i} d = {d} ")

                offset = None
                if ci:
                    offset = ci.offsets[i]
                    if offset is None and i == 0:
                        offset = self.create_offset(d)
                        ci.offsets[i] = offset

                if ci and offset is not None:
                    logger.debug(f"\tApplying data offsets {offset} to plot {id(plot)} ax_idx: {i}")
                    if isinstance(d, Collection) and not isinstance(d, (str, bytes)):
                        arr = np.asarray(d, dtype=np.int64)
                        ret.append(BufferObject(arr / 10000))
                    else:
                        ret.append(np.int64(d) / 10000)
                else:
                    ret.append(d)
        return ret

    def transform_value(self, plot: PlotItem, ax_idx: int, value: Any, inverse=False):
        """Adds or subtracts axis offset from value trying to preserve type of offset (ex: does not convert to
        float when offset is int)"""
        return self._impl_plot_cache_table.transform_value(plot, ax_idx, value, inverse=inverse)
