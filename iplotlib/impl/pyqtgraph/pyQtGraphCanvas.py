# Changelog:
#   Jan 2023:   -Added support for legend position and layout [Alberto Luengo]
import datetime
import inspect
import weakref
from collections import defaultdict
from typing import Any, Callable, Collection, List, Tuple, Optional

import numpy as np
import pandas as pd
import pyqtgraph as pg
from PySide6.QtCore import Signal as QtSignal
from PySide6.QtCore import Qt
from pyqtgraph import PlotItem, AxisItem, PlotDataItem, IsocurveItem, ViewBox, LegendItem, FillBetweenItem
from pyqtgraph.Qt import QtCore
from pyqtgraph.Qt import QtWidgets
from pyqtgraph.Qt.QtWidgets import QSlider, QHBoxLayout, QLabel, QGraphicsSceneMouseEvent

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
from iplotlib.core.limits import IplPlotViewLimits, IplSignalLimits, IplAxisLimits, IplSliderLimits
from iplotlib.impl.pyqtgraph.pyQtCrosshair import pyQtCrosshair
from iplotlib.impl.pyqtgraph.dateFormatter import NanosecondDateFormatter

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
    'post': 'right'
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
        self._block_right_button = False

    def mousePressEvent(self, ev: QGraphicsSceneMouseEvent):
        if ev.button() == Qt.MouseButton.RightButton and self._block_right_button:
            self.pressed.emit(self, ev)
            ev.accept()
            return
        super().mousePressEvent(ev)
        self.pressed.emit(self, ev)

    def release_event(self):
        self.released.emit(self)

    def mouseClickEvent(self, ev):
        super().mouseClickEvent(ev)
        self.released.emit(self)

    def wheelEvent(self, ev, axis=None):
        ev.ignore()

    def mouseDragEvent(self, ev, axis=None):
        if getattr(self, 'state', None) and self.state.get('mouseMode') == self.RectMode \
                and ev.button() == Qt.MouseButton.RightButton:
            if ev.isStart():
                self.rbScaleBox.setPen(pg.mkPen((0, 0, 0), width=1, style=QtCore.Qt.PenStyle.DashLine))
                self.updateScaleBox(ev.buttonDownPos(), ev.pos())
                ev.accept()
                return
            elif ev.isFinish():
                p0 = self.mapSceneToView(ev.buttonDownScenePos())
                p1 = self.mapSceneToView(ev.scenePos())
                x1, x2 = float(min(p0.x(), p1.x())), float(max(p0.x(), p1.x()))
                y1, y2 = float(min(p0.y(), p1.y())), float(max(p0.y(), p1.y()))
                self.rbScaleBox.hide()
                if x2 - x1 <= 0 or y2 - y1 <= 0:
                    ev.accept()
                    return
                (vx0, vx1), (vy0, vy1) = self.viewRange()
                vw = float(vx1 - vx0)
                vh = float(vy1 - vy0)
                cx = (x1 + x2) / 2.0
                cy = (y1 + y2) / 2.0
                new_w = vw * vw / float(x2 - x1)
                new_h = vh * vh / float(y2 - y1)
                self.setXRange(cx - new_w / 2.0, cx + new_w / 2.0, padding=0)
                self.setYRange(cy - new_h / 2.0, cy + new_h / 2.0, padding=0)
                ev.accept()
                return
            else:
                self.updateScaleBox(ev.buttonDownPos(), ev.pos())
                ev.accept()
                return
        super().mouseDragEvent(ev, axis=axis)


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

        self._update = defaultdict(int)

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

        plot_lines = self._signal_impl_shape_lut.get(id(signal))  # type: List[PlotDataItem]
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
        Returns a dict of arguments for PlotDataItem based on the attributes of SignalXY
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

    def do_impl_envelope_plot(self, signal: Signal, plot: PlotItem, x_data, y1_data, y2_data):
        plot_lines = self._signal_impl_shape_lut.get(id(signal))  # type: List[PlotDataItem]

        # Reflect downsampling in legend
        self.legend_downsampled_signal(signal, plot, plot_lines)

        style = self.get_signal_style(signal)
        style2 = dict(style)
        style2.pop("name", None)
        draw_fn = plot.plot

        # Review to implement directly in PlotXY class
        if signal.color is None:
            # It means that the color has been reset but must keep the original color
            signal.color = signal.original_color

        if plot_lines is not None:
            if x_data.ndim == 1 and y1_data.ndim == 1 and y2_data.ndim == 1:
                self.set_line_data(style, plot_lines[0], x_data, y1_data)
                self.set_line_data(style2, plot_lines[1], x_data, y2_data)

                # Update FillBetweenItem
                area = plot_lines[2]
                if isinstance(area, FillBetweenItem):
                    area.setCurves(plot_lines[0], plot_lines[1])

        else:
            if x_data.ndim == 1 and y1_data.ndim == 1 and y2_data.ndim == 1:
                # Creation of FillBetweenItem
                curve_1 = draw_fn(x=x_data, y=y1_data, **style)
                pen = curve_1.opts['pen']
                qcolor = pen.color()
                brush = (qcolor.red(), qcolor.green(), qcolor.blue(), int(0.3 * 255))
                curve_2 = draw_fn(x=x_data, y=y2_data, **style2)
                area = FillBetweenItem(curve1=curve_1, curve2=curve_2, brush=brush)
                plot.addItem(area)

                plot_lines = [curve_1, curve_2, area]

        signal.lines = plot_lines
        self._signal_impl_shape_lut.update({id(signal): plot_lines})

        return plot_lines

    def set_suptitle(self, title: str, font_size: int = None, font_color: str = 'black'):
        suptitle = pg.LabelItem(justify='center')
        self.figure.addItem(suptitle, row=0, col=0, colspan=3)
        suptitle.setText("Título general (suptitle)", size='16pt', bold=True)

    def set_impl_plot_limits(self, impl_plot: PlotItem, ax_idx: int, limits: tuple) -> bool:
        if not isinstance(impl_plot, PlotItem):
            return False
        self.set_oaw_axis_limits(impl_plot, ax_idx, limits)
        return True

    def _get_all_shared_axes(self, base_impl_plot: PlotItem) -> List[PlotItem]:
        cache_item = self._impl_plot_cache_table.get_cache_item(base_impl_plot)

        base_plot = cache_item.plot()
        if isinstance(base_plot, PlotXYWithSlider):
            return []

        shared = list()
        base_begin, base_end = base_plot.axes[0].get_limits("original")

        for stack in self._layout_stacks.values():
            for plot_item in stack.values():
                cache_item = self._impl_plot_cache_table.get_cache_item(plot_item)
                plot = cache_item.plot()
                begin, end = plot.axes[0].get_limits("original")

                # Check if it is date and the max difference is 1 second
                # Need to differentiate if it is absolute or relative
                max_diff = self._pm.get_value(self.canvas, 'max_diff')
                max_diff_ns = max_diff * 1e9 if plot.axes[0].is_date or isinstance(plot,
                                                                                   PlotXYWithSlider) else max_diff
                if abs(begin - base_begin) <= max_diff_ns and abs(end - base_end) <= max_diff_ns:
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
        cell_gl.nextRow()
        cell_gl.addItem(proxy)  # row=last_row_id, col=0
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
        axis_items = {}
        plot = None
        l_key = (row, col)
        for stack_id, key in enumerate(sorted(i_plot.signals.keys())):

            if isinstance(i_plot.axes[0], RangeAxis) and i_plot.axes[0].is_date:
                axis_items["bottom"] = NanosecondDateFormatter(orientation='bottom')

            signals = i_plot.signals.get(key) or list()
            visible_stack_ids.append(stack_id)

            if l_key not in self._layout_stacks:
                plot = pg.PlotItem(viewBox=QtViewBox(), axisItems=axis_items)
                cell_gl.addItem(plot, row=0, col=0)
                self._layout_stacks.setdefault(l_key, {})[stack_id] = plot
            elif stack_id not in self._layout_stacks[l_key]:
                pi = pg.PlotItem(viewBox=QtViewBox(), axisItems=axis_items)
                cell_gl.addItem(pi, row=stack_id, col=0)
                pi.vb.setXLink(self._layout_stacks[l_key][0])
                pi.getAxis('bottom').setStyle(showValues=False)
                self._layout_stacks[l_key][stack_id] = pi

            # Slider creation only if it doesn't exist
            if isinstance(i_plot, PlotXYWithSlider):
                cell_gl = self.process_ipl_plot_xy_slider(i_plot, row, col, visible_stack_ids, cell_gl)

            plot = self._layout_stacks[l_key][stack_id]
            plot.enableAutoRange(x=False, y=False)
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
                    x_axis = i_plot.get_x_axis()
                    self.process_ipl_axis(x_axis, ax_idx, i_plot, plot)

            # Process signal
            for signal in signals:
                # self._signal_impl_plot_lut.update({id(signal): mpl_axes})
                self._signal_impl_plot_lut.update({signal.uid: plot})
                self.process_ipl_signal(signal)

            # Set limits for y axis
            # self.update_multi_range_axis(i_plot.axes[1], 1, plot)

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

        self.set_bottom_axis_stacked(row, col, visible_stack_ids)
        if isinstance(i_plot.axes[0], RangeAxis) and i_plot.axes[0].is_date:
            cell_gl.addItem(axis_items["bottom"].common_label, row=len(i_plot.signals), col=0)

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

        current_plot = view_box.parentItem()
        shared_plots = self._get_all_shared_axes(current_plot)

        new_start, new_end = self.get_oaw_axis_limits(current_plot, 0)
        for impl_plot in shared_plots:
            if not self._pm.get_value(self.canvas, 'shared_x_axis') and impl_plot != current_plot:
                continue

            if self._update[impl_plot] == 1 or self._update[impl_plot] == 2:
                continue

            self._update[impl_plot] = 1

            # impl_plot.vb.sigXRangeChanged.disconnect()
            # self._update = False

            plot = self._impl_plot_cache_table.get_cache_item(impl_plot).plot()
            self.set_oaw_axis_limits(impl_plot, 0, (new_start, new_end))

            if self._impl_plot_cache_table.get_cache_item(impl_plot).plot().axes[0].is_date and isinstance(self.get_impl_axis(impl_plot, 0), NanosecondDateFormatter):
                self.process_ipl_axis_formatter(impl_plot, 0)

            for stack in plot.signals.values():
                for signal in stack:
                    signal.set_limits((new_start, new_end))
                    self.process_ipl_signal(signal)

            # impl_plot.vb.sigXRangeChanged.connect(self._axis_update_callback)
            # self._update = True
            self._update[impl_plot] = 2

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

    def process_ipl_axis_formatter(self, impl_plot: PlotItem, ax_idx: int):
        ci = self._impl_plot_cache_table.get_cache_item(impl_plot)
        impl_plot.getAxis("bottom").set_offset(ci.offsets[ax_idx])
        # axis_date = NanosecondDateFormatter(offset=ci.offsets[ax_idx], orientation='bottom')
        # impl_plot.setAxisItems({"bottom": axis_date})

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
        self.deactivate_cursor()
        for stack in self._layout_stacks.values():
            for plot in stack.values():
                if not plot:
                    continue
                vb = plot.vb
                vb.setMouseMode(vb.PanMode)
                self.set_mouse(plot)

    def set_view_box_zoom(self):
        self.deactivate_cursor()
        for stack in self._layout_stacks.values():
            for plot in stack.values():
                if not plot:
                    continue
                vb = plot.vb
                vb.setMouseMode(vb.RectMode)
                self.set_mouse(plot)

    def set_view_box_pan(self):
        self.deactivate_cursor()
        for stack in self._layout_stacks.values():
            for plot in stack.values():
                if not plot:
                    continue
                vb = plot.vb
                vb.setMouseMode(vb.PanMode)
                vb.setMouseEnabled(x=True, y=True)

    def set_view_box_crosshair(self):
        self.deactivate_cursor()
        for stack in self._layout_stacks.values():
            for plot in stack.values():
                if not plot:
                    continue
                vb = plot.vb
                vb.setMouseMode(vb.PanMode)
                self.set_mouse(plot)
        self.activate_cursor()

    def autoscale_y_axis(self, impl_plot, margin=0.1):
        pass
        impl_plot.vb.enableAutoRange(axis=1, enable=True)

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
                    if isinstance(plot_item.getAxis("bottom"), NanosecondDateFormatter):
                        plot_item.getAxis("bottom").common_label.setVisible(True)
                else:
                    if all_stack:
                        plot_item.setVisible(r == row and c == col)
                        if isinstance(plot_item.getAxis("bottom"), NanosecondDateFormatter):
                            plot_item.getAxis("bottom").common_label.setVisible(r == row and c == col)
                    else:
                        plot_item.setVisible(r == row and c == col and s_id == stack_id)
                        if isinstance(plot_item.getAxis("bottom"), NanosecondDateFormatter):
                            plot_item.getAxis("bottom").common_label.setVisible(r == row and c == col and s_id == stack_id)
                        self.set_bottom_axis_stacked(row, col, [stack_id])

        for key, value in self._slider_placeholders.items():
            if key == (row, col):
                continue
            value.setVisible(un_focus)

    @BackendParserBase.run_in_one_thread
    def activate_cursor(self):
        plots = []
        for stack in self._layout_stacks.values():
            for plot in stack.values():
                if plot:
                    plots.append(plot)
        if not plots:
            return

        # Pause repaints/signals to avoid flicker while creating items
        view = self.figure  # GraphicsLayoutWidget is a QGraphicsView
        scene = view.scene()
        vp = view.viewport()

        if vp is not None:
            vp.setUpdatesEnabled(False)
        view.setUpdatesEnabled(False)
        try:
            scene.blockSignals(True)

            x_label = self._pm.get_value(self.canvas, 'enable_x_label_crosshair')
            y_label = self._pm.get_value(self.canvas, 'enable_y_label_crosshair')
            val_label = self._pm.get_value(self.canvas, 'enable_val_label_crosshair')
            color = self._pm.get_value(self.canvas, 'crosshair_color')
            lw = getattr(self.canvas, 'crosshair_line_width', 1)
            horiz_on = getattr(self.canvas, 'crosshair_horizontal', False)
            vert_on = getattr(self.canvas, 'crosshair_vertical', True)
            tol = 0.05  # same as IplotMultiCursor

            if getattr(self.canvas, 'crosshair_per_plot', False):
                for p in plots:
                    self._cursors.append(
                        pyQtCrosshair(
                            plots=[p],
                            x_label=x_label, y_label=y_label, val_label=val_label,
                            color=color, lw=lw,
                            horiz_on=horiz_on, vert_on=vert_on,
                            val_tolerance=tol,
                            cache_table=self._impl_plot_cache_table,
                        )
                    )
            else:
                self._cursors.append(
                    pyQtCrosshair(
                        plots=plots,
                        x_label=x_label, y_label=y_label, val_label=val_label,
                        color=color, lw=lw,
                        horiz_on=horiz_on, vert_on=vert_on,
                        val_tolerance=tol,
                        cache_table=self._impl_plot_cache_table,
                    )
                )
        finally:
            try:
                scene.blockSignals(False)
            except Exception:
                pass
            view.setUpdatesEnabled(True)
            if vp is not None:
                vp.setUpdatesEnabled(True)

    @BackendParserBase.run_in_one_thread
    def deactivate_cursor(self):
        view = self.figure
        scene = view.scene()
        vp = view.viewport()

        if vp is not None:
            vp.setUpdatesEnabled(False)
        view.setUpdatesEnabled(False)
        try:
            scene.blockSignals(True)
            for cursor in self._cursors:
                cursor.clear(destroy=True)
            self._cursors.clear()
        finally:
            try:
                scene.blockSignals(False)
            except Exception:
                pass
            view.setUpdatesEnabled(True)
            if vp is not None:
                vp.setUpdatesEnabled(True)

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

    def transform_data(self, impl_plot: PlotItem, data) -> List[Any]:
        """This function post processes data if it cannot be plotted directly.
                Currently, it transforms data if it is a large integer which can cause overflow"""
        ret = []
        ci = self._impl_plot_cache_table.get_cache_item(impl_plot)

        for ax_idx, d in enumerate(data):
            logger.debug(f"\t transform data ax_idx={ax_idx} d = {d} ")
            offset = ci.offsets[ax_idx]
            if offset == 0 or offset is None:
                ret.append(d)
            elif offset == 100_000:
                ret.append(BufferObject([np.int64(e) / offset for e in d]))
            else:
                ret.append(BufferObject([np.int64(e) - offset for e in d]))
        return ret

    def transform_value(self, impl_plot: PlotItem, ax_idx: int, value: Any, inverse=False):
        """Adds or subtracts axis offset from value trying to preserve type of offset (ex: does not convert to
        float when offset is int)"""

        offset = self._impl_plot_cache_table.get_cache_item(impl_plot).offsets[ax_idx]

        if offset is None:
            return value
        elif offset == 100_000:
            if inverse:
                return value / offset
            else:
                return value * offset
        else:
            if inverse:
                return value - offset
            else:
                return value + offset

    def create_offset_pyqt(self, limits):

        begin, end = limits
        diff = end - begin
        if begin < 10 ** 15:
            offset = 0
        else:
            if diff > 1e14:
                offset = 100_000
            else:
                offset = (begin + end) / 2

        return offset

    def set_oaw_axis_limits(self, impl_plot: Any, ax_idx: int, limits):
        """
        Offset-aware version of implementation's `set_impl_x_axis_limits`, `set_impl_y_axis_limits`
        The `oaw` in the function name stands for OffsetAWare.
        """
        ci = self._impl_plot_cache_table.get_cache_item(impl_plot)

        ci.offsets[ax_idx] = self.create_offset_pyqt(limits)

        begin = self.transform_value(impl_plot, ax_idx, limits[0], inverse=True)
        end = self.transform_value(impl_plot, ax_idx, limits[1], inverse=True)
        logger.debug(f"\tLimits {begin} to to plot {end} ax_idx: {ax_idx} case 0")

        if ax_idx == 0:
            self.set_impl_x_axis_limits(impl_plot, (begin, end))
        elif ax_idx == 1:
            self.set_impl_y_axis_limits(impl_plot, (begin, end))

    def get_oaw_axis_limits(self, impl_plot: Any, ax_idx: int):
        """
        Offset-aware version of implementation's `get_impl_x_axis_limits`, `get_impl_y_axis_limits`
        The `oaw` in the function name stands for OffsetAWare.
        """
        begin, end = (None, None)
        if ax_idx == 0:
            begin, end = self.get_impl_x_axis_limits(impl_plot)
        elif ax_idx == 1:
            begin, end = self.get_impl_y_axis_limits(impl_plot)
            return begin, end
        return self.transform_value(impl_plot, ax_idx, begin), self.transform_value(impl_plot, ax_idx, end)

    def process_ipl_axis(self, axis: Axis, ax_idx: int, i_plot: Plot, impl_plot: Any):
        """
        Prepare the implementation axis.

        :param axis
        :param ax_idx
        :param i_plot: An Axis instance
        :param impl_plot
        :type axis: Axis
        :type ax_idx: int
        :type i_plot: Plot
        :type impl_plot: Any
        """

        axis_item = self.get_impl_axis(impl_plot, ax_idx)
        self._axis_impl_plot_lut.update({id(axis): impl_plot})

        if isinstance(axis, Axis):
            self.process_ipl_log_axis(axis_item, i_plot)

            fc = self._pm.get_value(axis, 'font_color')
            fs = self._pm.get_value(axis, 'font_size')

            axis_item._font_color = fc
            axis_item._font_size = fs
            axis_item._label = axis.label

            self.process_ipl_axis_params(fc, fs, axis, axis_item)

        if ax_idx == 1:
            self.autoscale_y_axis(impl_plot)

        if axis.original_begin is None or axis.original_end is None:
            begin, end = +np.inf, -np.inf
            for stack in i_plot.signals.values():
                for signal in stack:
                    signal.get_data()
                    if signal.data_store[2].size > 0 and signal.data_store[3].size > 0 and ax_idx == 1:
                        # Envelope case
                        data = signal.z_data
                        data = data[~np.isnan(data)]
                        begin, end = min(np.min(data).item(), begin), max(np.max(data).item(), end)
                    else:
                        data = signal.x_data if ax_idx == 0 else signal.y_data
                        data = data[~np.isnan(data)]
                        begin, end = min(np.min(data).item(), begin), max(np.max(data).item(), end)
            axis.original_begin = begin
            axis.original_end = end
        if any(frame.function in ["draw_clicked", "import_dict", "update_canvas_preferences"] for frame in
               inspect.stack()):
            begin, end = axis.original_begin, axis.original_end
        else:
            begin, end = self.get_oaw_axis_limits(impl_plot, ax_idx)

        self.set_oaw_axis_limits(impl_plot, ax_idx, [begin, end])

        if axis.is_date and isinstance(axis_item, NanosecondDateFormatter):
            self.process_ipl_axis_formatter(impl_plot, ax_idx)

        # Set number of ticks and labels
        tick_number = self._pm.get_value(axis, 'tick_number')
        self.process_ipl_axis_ticks(tick_number, axis_item)

    def get_all_plot_limits(self, which='current') -> List[IplPlotViewLimits]:
        """
        Return limits of all plots. The `which` argument can be `original` or `current`
        Use this function to construct an :data:`~iplotlib.core.commands.axes_range.IplotAxesRangeCmd` instance
        that you could push onto the history manager.
        """
        all_limits = []
        if not isinstance(self.canvas, Canvas):
            return all_limits
        for col in self.canvas.plots:
            for plot in col:
                if plot:
                    impl_plot = self._plot_impl_plot_lut.get(id(plot))[0]
                    plot_lims = self.get_plot_limits(plot, impl_plot)
                    if not isinstance(plot_lims, IplPlotViewLimits):
                        continue
                    all_limits.append(plot_lims)
        return all_limits

    def get_plot_limits(self, plot: Plot, impl_plot: PlotItem) -> Optional[IplPlotViewLimits]:
        """
        Return limits for the given plot. The `which` argument can be `original` or `current`
        """
        if not isinstance(self.canvas, Canvas) or not isinstance(plot, Plot):
            return None
        plot_lims = IplPlotViewLimits(plot_ref=weakref.ref(plot))
        for plot_signals in plot.signals.values():
            for sig in plot_signals:
                plot_lims.signals_ranges.append(IplSignalLimits(sig.ts_start, sig.ts_end, weakref.ref(sig)))
        for axes in plot.axes:
            if isinstance(axes, Collection):
                for axis in axes:
                    if not isinstance(axis, RangeAxis):
                        continue
                    # begin, end = axis.get_limits(which)
                    begin, end = self.get_oaw_axis_limits(impl_plot, 1)
                    plot_lims.axes_ranges.append(IplAxisLimits(begin, end, weakref.ref(axis)))
            elif isinstance(axes, RangeAxis):
                axis = axes
                begin, end = self.get_oaw_axis_limits(impl_plot, 0)
                # begin, end = axis.get_limits(which)
                plot_lims.axes_ranges.append(IplAxisLimits(begin, end, weakref.ref(axis)))

        # Save slider limits for PlotXYWithSlider
        if isinstance(plot, PlotXYWithSlider):
            plot_lims.sliders_ranges.append(IplSliderLimits(plot.slider_last_min, plot.slider_last_max))

        return plot_lims
