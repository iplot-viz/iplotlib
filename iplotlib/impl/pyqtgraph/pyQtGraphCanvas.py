# Changelog:
#   Jan 2023:   -Added support for legend position and layout [Alberto Luengo]
import datetime
import numpy as np
from typing import Any, Callable, Collection, List, Tuple
import pandas as pd
import pyqtgraph as pg
from pyqtgraph.Qt import QtWidgets
from pyqtgraph import IsocurveItem, ViewBox, LegendItem
from pyqtgraph.Qt import QtCore
from pyqtgraph.Qt.QtWidgets import QSlider, QHBoxLayout, QLabel, QGraphicsSceneMouseEvent
from PySide6.QtCore import Signal as QtSignal

from iplotLogging import setupLogger
from iplotProcessing.core import BufferObject
from iplotlib.core import (Axis,
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


class QtViewBox(pg.ViewBox):
    pressed = QtSignal(object, object)
    released = QtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent=parent, enableMenu=True)
        self.sigRangeChanged.connect(self.release_event)

    def mousePressEvent(self, ev: QGraphicsSceneMouseEvent):
        # Add log message
        super().mousePressEvent(ev)
        self.pressed.emit(self, ev)

    def release_event(self):
        self.released.emit(self)


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
        self._cell_gl = {}  # (row, col) -> GraphicsLayout sublayout
        self._layout_stacks = {}  # (row, col, stack_id) -> PlotItem
        self._slider_placeholders = {}  # (row, col) -> QGraphicsProxyWidget
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

    def legend_downsampled_signal(self, signal, impl_plot, plot_lines):
        """
        Add or removes a '*' in the legend label to indicate if the signal is downsampled or not
        """
        legend = impl_plot.legend
        if len(legend.items) and plot_lines is not None:
            lines = [lines[0].item.name() for lines in legend.items]
            pos = lines.index(plot_lines[0].name())

            legend_text = legend.items[pos][1].text
            if legend_text.endswith('*') and not signal.isDownsampled:
                legend.items[pos][1].setText(legend_text[:-1])
            elif not legend_text.endswith('*') and signal.isDownsampled:
                legend.items[pos][1].setText(legend_text + '*')

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
                line = plot_lines[0]
                self.set_line_data(style, line, x_data, y_data)
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
            # TODO: revisar bien
            """
            for new, old in zip(plot_lines, signal.lines):
                for n, o in zip(new, old):
                    n.setVisible(o.isVisible())
            """
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
        style['antialias'] = True

        return style

    def do_impl_line_plot_xy_slider(self, signal: SignalXY, plot: PlotItem, i_plot: PlotXYWithSlider, cache_item,
                                    x_data, y_data, z_data):
        plot_lines = self._signal_impl_shape_lut.get(id(signal))  # type: List[List[PlotDataItem]]
        style = self.get_signal_style(signal)
        draw_fn = plot.plot

        ysub_data = y_data[i_plot.slider.value()]

        # Review to implement directly in PlotXY class
        if signal.color is None:
            signal.color = i_plot.get_next_color()

        if isinstance(plot_lines, list):
            if x_data.ndim == 1 and ysub_data.ndim == 1:
                line = plot_lines[0]
                self.set_line_data(style, line, x_data, ysub_data)
                # _update_marker_by_point_count(line, x_data, style)
            elif x_data.ndim == 1 and ysub_data.ndim == 2:
                for i, line in enumerate(plot_lines):
                    line[0].setData(x=x_data, y=y_data[:, i])
                    line[0].setPen(style['pen'])
                    # _update_marker_by_point_count(line[0], x_data, style)
        else:
            if x_data.ndim == 1 and ysub_data.ndim == 1:
                plot_lines = [draw_fn(x_data, ysub_data, **style)]
            elif x_data.ndim == 1 and ysub_data.ndim == 2:
                lines = draw_fn(x_data, ysub_data, **style)
                plot_lines = [[line] for line in lines]
                for i, line in enumerate(plot_lines):
                    line[0].set_label(f"{signal.label}[{i}]")

        signal.lines = plot_lines

        return plot_lines

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
            # TODO: Check size z_data
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
                    # TODO: pendiente add antialiasing para isocurvas
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

    def set_impl_plot_limits(self, impl_plot: PlotItem, ax_idx: int, limits: tuple) -> bool:
        if not isinstance(impl_plot, PlotItem):
            return False
        self.set_oaw_axis_limits(impl_plot, ax_idx, limits)
        return True

    def _get_all_shared_axes(self, base_impl_plot: PlotItem):
        if not isinstance(self.canvas, Canvas):
            return []

        cache_item = self._impl_plot_cache_table.get_cache_item(base_impl_plot)
        if not hasattr(cache_item, 'plot'):
            return
        base_plot = cache_item.plot()
        if not isinstance(base_plot, Plot):
            return
        if isinstance(base_plot, PlotXYWithSlider):
            return []
        shared = list()
        base_limits = self.get_plot_limits(base_plot, which='original')
        base_begin, base_end = base_limits.axes_ranges[0].begin, base_limits.axes_ranges[0].end

        if (base_begin, base_end) != (None, None) or (base_begin, base_end) == (None, None):
            # for axes in self.figure.axes:
            for stack in self._layout_stacks.values():
                for plot_item in stack.values():
                    cache_item = self._impl_plot_cache_table.get_cache_item(plot_item)
                    if not hasattr(cache_item, 'plot'):
                        continue
                    plot = cache_item.plot()
                    if not isinstance(plot, Plot):
                        continue
                    limits = self.get_plot_limits(plot, which='original')
                    begin, end = limits.axes_ranges[0].begin, limits.axes_ranges[0].end
                    # Check if it is date and the max difference is 1 second
                    # Need to differentiate if it is absolute or relative
                    max_diff = self._pm.get_value(self.canvas, 'max_diff')
                    max_diff_ns = max_diff * 1e9 if plot.axes[0].is_date or isinstance(plot,
                                                                                       PlotXYWithSlider) else max_diff
                    if ((begin, end) == (base_begin, base_end) or (
                            abs(begin - base_begin) <= max_diff_ns and abs(end - base_end) <= max_diff_ns)):
                        shared.append(plot_item)
        return shared

    def process_ipl_plot_xy(self):
        pass

    def process_ipl_plot_contour(self):
        pass

    def process_ipl_plot_xy_slider(self, i_plot: PlotXYWithSlider, row, col, visible_stack_ids, cell_gl):

        # Check if there was a previous plot_with_slider with a value
        if i_plot.slider_last_val is not None:
            value = i_plot.slider_last_val
        else:
            value = 0

        # Slider creation
        slider = QSlider(QtCore.Qt.Orientation.Horizontal)
        slider.setMinimum(0)
        slider.setMaximum(i_plot.signals[1][0].y_data.shape[0] - 1)
        slider.setValue(value)
        slider.setTickInterval(1)

        i_plot.slider = slider

        # Proxy widget
        rc_key = (row, col)
        proxy = QtWidgets.QGraphicsProxyWidget()
        proxy.setWidget(slider)
        last_row_id = max(visible_stack_ids) + 1
        cell_gl.addItem(proxy, row=last_row_id, col=0)
        self._slider_placeholders[rc_key] = proxy

        # Annotate labels along the slider axis
        h_layout = QHBoxLayout()

        # Get data for the slider
        slider_values = i_plot.signals[1][0].z_data
        min_label = QLabel(f"{pd.Timestamp(slider_values[0])}")
        max_label = QLabel(f"{pd.Timestamp(slider_values[-1])}")
        current_label = QLabel(F"{pd.Timestamp(slider_values[0])}")
        h_layout.addWidget(min_label)
        h_layout.addStretch()
        h_layout.addWidget(current_label)
        h_layout.addStretch()
        h_layout.addWidget(max_label)

        # Register the callback function to update the plot when the slider value changes
        slider.valueChanged.connect(lambda val, i_p=i_plot: self._update_slider(val, i_p, slider_values, current_label))

        # pyqt_layout.addWidget(slider)
        # pyqt_layout.addLayout(h_layout)

        # return pyqt_layout
        return cell_gl

    def process_ipl_plot(self, i_plot: Plot, col: int, row: int):
        if not isinstance(i_plot, Plot):
            return

        cell_gl = self._ensure_cell_layout(row, col, i_plot.row_span, i_plot.col_span)

        visible_stack_ids = []

        plot = None
        l_key = (row, col)
        for stack_id, key in enumerate(sorted(i_plot.signals.keys())):
            signals = i_plot.signals.get(key) or list()
            visible_stack_ids.append(stack_id)

            if l_key not in self._layout_stacks:
                plot = pg.PlotItem(viewBox=QtViewBox())
                cell_gl.addItem(plot, row=0, col=0)
                self._layout_stacks.setdefault(l_key, {})[stack_id] = plot
            elif stack_id not in self._layout_stacks[l_key]:
                pi = pg.PlotItem(viewBox=QtViewBox())
                cell_gl.addItem(pi, row=stack_id, col=0)
                pi.vb.setXLink(self._layout_stacks[l_key][0])
                pi.getAxis('bottom').setStyle(showValues=False)
                self._layout_stacks[l_key][stack_id] = pi

            # Slider creation only if it doesn't exist
            if isinstance(i_plot, PlotXYWithSlider):
                cell_gl = self.process_ipl_plot_xy_slider(i_plot, row, col, visible_stack_ids, cell_gl)

            plot = self._layout_stacks[l_key][stack_id]
            self._plot_impl_plot_lut[id(i_plot)].append(plot)

            # Keep references to iplotlib instances for ease of access in callbacks.
            self._impl_plot_cache_table.register(plot, self.canvas, i_plot, stack_id, signals)

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

            # Legend processing for downsampled data when drawing
            ix_legend = 0
            for signal in signals:
                if signal.isDownsampled:
                    legend_label = plot.legend.items[ix_legend][1].text + '*'
                    plot.legend.items[ix_legend][1].setText(legend_label)
                ix_legend += 1

        # Observe the axis limit change events
        vb = plot.getViewBox()
        vb.sigXRangeChanged.connect(self._axis_update_callback)
        vb.sigYRangeChanged.connect(self._axis_update_callback)

        self.set_bottom_axis_stacked(row, col, visible_stack_ids)

    def set_bottom_axis_stacked(self, row: int, col: int, visible_stacks: List[int]):
        if not visible_stacks:
            return
        for s_id in set(visible_stacks):
            if s_id == max(visible_stacks):
                self._layout_stacks[(row, col)][s_id].getAxis('bottom').setStyle(showValues=True)
            else:
                self._layout_stacks[(row, col)][s_id].getAxis('bottom').setStyle(showValues=False)

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
        def set_legend_position(legend: LegendItem, position: str):
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

    def _update_slider(self, val, i_plot: PlotXYWithSlider, slider_values, current_label):
        for c_row in i_plot.signals.values():
            for c_signal in c_row:
                self.process_ipl_signal(c_signal)

        # Refresh current label value
        current_value = pd.Timestamp(slider_values[int(val)])
        current_label.setText(f"{current_value}")

        i_plot.slider_last_val = val

        if self._pm.get_value(i_plot, 'sync_slider'):
            return

        if self._pm.get_value(self.canvas, 'shared_x_axis'):
            plot_with_slider_shared = self.get_shared_plot_xy_slider(i_plot)
            for plot_with_slider in plot_with_slider_shared:
                if not self.canvas.focus_plot:
                    plot_with_slider.sync_slider = True
                    plot_with_slider.slider.setValue(val)
                    plot_with_slider.sync_slider = False
                else:
                    plot_with_slider.slider_last_val = val

    def _axis_update_callback(self, view_box: ViewBox):

        affected_axes = [view_box.parentItem()]
        if self._pm.get_value(self.canvas, 'shared_x_axis') and not self.canvas.undo_redo:
            plot = view_box.parentItem()
            other_axes = self._get_all_shared_axes(plot)
            affected_axes = other_axes
            for other_axis in other_axes:
                cur_x_limits = self.get_oaw_axis_limits(plot, 0)
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

        for axes in affected_axes:
            ci = self._impl_plot_cache_table.get_cache_item(axes)
            if not hasattr(ci, 'plot'):
                return
            if not isinstance(ci.plot(), Plot):
                return
            ranges = []

            for ax_idx, ax in enumerate(ci.plot().axes):
                if isinstance(ax, Collection):
                    self.update_multi_range_axis(ax, ax_idx, axes)
                elif isinstance(ax, RangeAxis):
                    self.update_range_axis(ax, ax_idx, axes)
                    ranges = ax.get_limits()
            if ci not in self._stale_citems:
                self._stale_citems.append(ci)
            if self.canvas.undo_redo:
                return
            if isinstance(ci.plot(), PlotXYWithSlider):
                return
            if not hasattr(ci, 'signals'):
                return
            if not ci.signals:
                return

            for singal_ref in ci.signals:
                signal = singal_ref()
                if hasattr(signal, "set_xranges") and isinstance(signal, SignalXY):
                    signal.set_xranges(ranges)
                    logger.debug(f"callback update {ranges[0]} axis range to {ranges[1]}")

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
        self._cell_gl = {}
        self._layout_stacks = {}
        self._slider_placeholders = {}
        # Clean relevant items from GraphicsLayoutWidget
        for item in self.figure.items()[:]:
            try:
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
        for stack in self._layout_stacks.values():
            for plot in stack.values():
                if not plot:
                    continue
                vb = plot.vb
                vb.setMouseMode(vb.PanMode)

    def set_view_box_zoom(self):
        for stack in self._layout_stacks.values():
            for plot in stack.values():
                if not plot:
                    continue
                vb = plot.vb
                vb.setMouseMode(vb.RectMode)

    def autoscale_y_axis(self, impl_plot, margin=0.1):
        pass

    def set_impl_plot_slider_limits(self, plot: PlotXYWithSlider, start, end):
        pass

    def update_slider_limits(self, plot: PlotXYWithSlider, begin, end):
        if bool(begin > (1 << 53)):
            # Convert time-based 'begin' and 'end' values to corresponding indices in z_data
            new_start = np.searchsorted(plot.signals[1][0].z_data, begin)
            new_end = np.searchsorted(plot.signals[1][0].z_data, end)

            # Ensure indices are within the valid range of the signal's time data
            max_len = len(plot.signals[1][0].z_data) - 1
            new_start = max(0, min(new_start, max_len))
            new_end = max(0, min(new_end, max_len))

            # Adjust current slider value
            if plot.slider.value() < new_start:
                val = new_start
            elif plot.slider.value() > new_end:
                val = new_end
            else:
                val = plot.slider.value()

            # Update slider limits
            plot.slider_last_min = new_start
            plot.slider.setRange(new_start, new_end)
            # plot.slider.setMinimum(new_start)

            # plot.slider.setMaximum(new_end)
            plot.slider_last_max = new_end

            plot.slider.setValue(val)

            # Update the annotations labels for the slider limits
            """
            annotations = [label for label in plot.slider.ax.get_children() if isinstance(label, plt.Annotation)]
            min_annotation, current_annotation, max_annotation = annotations[:3]
            min_annotation.set_text(f'{pandas.Timestamp(plot.signals[1][0].z_data[new_start])}')
            current_annotation.set_text(f'{pandas.Timestamp(plot.signals[1][0].z_data[val])}')
            max_annotation.set_text(f'{pandas.Timestamp(plot.signals[1][0].z_data[new_end])}')

            # Remove any previously highlighted region from the slider axis
            for child in plot.slider.ax.get_children():
                if isinstance(child, Patch) and child.get_facecolor()[:3] == (1.0, 0.0, 0.0):
                    child.remove()
            

            # Highlight the selected area in the slider, avoiding drawing a region if start and end span the full range
            if plot.slider_last_min != 0 or plot.slider_last_max != max_len:
                # plot.slider.ax.axvspan(new_start, new_end, color='red', alpha=0.3)
                painter = QPainter()
                painter.setBrush(QtGui.QColor(255, 0, 0, 80))
                painter.drawRect(QtCore.QRect(int(start_x), 0, int(end_x - start_x), plot.slider.height()))
                painter.end()
                
            """

    def enable_tight_layout(self):
        pass

    def disable_tight_layout(self):
        pass

    def set_focus_plot(self, impl_plot: PlotItem):
        un_focus = self._focus_plot is not None or impl_plot is None
        all_stack = self._pm.get_value(self.canvas, "full_mode_all_stack")
        if un_focus:
            self._focus_plot = None
            row, col, stack_id = None, None, None
        else:
            self._focus_plot = impl_plot
            ci = self._impl_plot_cache_table.get_cache_item(impl_plot)
            plot = ci.plot()
            row = plot.row - 1
            col = plot.col - 1
            stack_id = ci.stack_key

        for (r, c), stack_dict in self._layout_stacks.items():
            for s_id, plot_item in stack_dict.items():
                if un_focus:
                    plot_item.setVisible(True)
                else:
                    if all_stack:
                        plot_item.setVisible(r == row and c == col)
                    else:
                        plot_item.setVisible(r == row and c == col and s_id == stack_id)
                        self.set_bottom_axis_stacked(row, col, [stack_id])

        for key, value in self._slider_placeholders.items():
            if key == (row, col):
                continue
            value.setVisible(un_focus)

    @BackendParserBase.run_in_one_thread
    def activate_cursor(self):
        for stack in self._layout_stacks.values():
            for plot in stack.values():
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
        self.get_impl_x_axis(plot).setLabel(text)

    def set_impl_x_axis_limits(self, plot: PlotItem, limits: tuple):
        if isinstance(plot, PlotItem):
            vb = plot.getViewBox()
            vb.setXRange(limits[0], limits[1], padding=0)

    def set_impl_y_axis_label_text(self, plot: PlotItem, text: str):
        self.get_impl_y_axis(plot).setLabel(text)

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
        ci = self._impl_plot_cache_table.get_cache_item(plot)
        if hasattr(ci, 'offsets') and ci.offsets[ax_idx] is not None:
            base = ci.offsets[ax_idx]
            if isinstance(base, int) or type(base).__name__ == 'int64':
                value = int(value)
        return value / 10000 if inverse else value * 10000
