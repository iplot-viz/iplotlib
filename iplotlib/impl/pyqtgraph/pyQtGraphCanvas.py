# Changelog:
#   Jan 2023:   -Added support for legend position and layout [Alberto Luengo]
from datetime import datetime
from typing import Any, Callable, Collection, List, Tuple
import numpy as np
import pandas as pd
import pyqtgraph as pg
from PySide6.QtCore import Signal as QtSignal
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QFontMetricsF
from pyqtgraph import PlotItem, AxisItem, PlotDataItem, IsocurveItem, ViewBox, LegendItem, FillBetweenItem
from pyqtgraph.Qt import QtCore
from pyqtgraph.Qt import QtWidgets
from pyqtgraph.Qt.QtWidgets import QSlider, QHBoxLayout, QVBoxLayout, QLabel, QWidget

from iplotLogging import setupLogger
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
from iplotlib.impl.pyqtgraph.pyQtCrosshair import pyQtCrosshair
from iplotlib.impl.pyqtgraph.dateFormatter import NanosecondDateFormatter

logger = setupLogger.get_logger(__name__)

# Maps PyQtGraph line styles to corresponding Qt.PenStyle values
LINESTYLE_MAP = {
    'solid': QtCore.Qt.PenStyle.SolidLine,
    'dashed': QtCore.Qt.PenStyle.DashLine,
    'dashdot': QtCore.Qt.PenStyle.DashDotLine,
    'dotted': QtCore.Qt.PenStyle.DotLine,
}

# Maps PlotDataItem stepMode values
STEP_MAP_PG = {
    'linear': False,
    'post': 'right'
}


class QtViewBox(pg.ViewBox):
    pressed = QtSignal(object, object)
    released = QtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent=parent, enableMenu=True)
        self.sigRangeChangedManually.connect(self.release_event)

    def mousePressEvent(self, ev):
        # Add log message
        if ev.button() == Qt.MouseButton.RightButton:
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


class PyQtGraphParser(BackendParserBase):
    def __init__(self,
                 canvas: Canvas = None,
                 tight_layout: bool = True,
                 focus_plot=None,
                 focus_plot_stack_key=None,
                 impl_flush_method: Callable = None) -> None:
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

    def legend_downsampled_signal(self, signal, impl_plot: PlotItem, plot_lines: PlotDataItem):
        """
        Add or removes a '*' in the legend label to indicate if the signal is downsampled or not
        """
        legend = impl_plot.legend
        lines = [lines[0].item.name() for lines in legend.items]
        pos = lines.index(plot_lines.name())

        legend_text = legend.items[pos][1].text
        if legend_text.endswith('*') and not signal.isDownsampled:
            legend.items[pos][1].setText(legend_text[:-1])
        elif not legend_text.endswith('*') and signal.isDownsampled:
            legend.items[pos][1].setText(legend_text + '*')

    @staticmethod
    def _get_visible_data(xd, yd, lo, hi):
        pass

    @staticmethod
    def _update_marker_by_point_count(marker_line: PlotDataItem, signal_x_data, signal_style: dict):
        # TODO: implement
        pass

    def create_plot_lines_1D(self, draw_fn, x_data, y_data, style):
        return [draw_fn(x=x_data, y=y_data, **style)]

    def create_plot_lines_2D(self, draw_fn, x_data, y_data, style):
        plot_lines = []
        for i in range(y_data.shape[1]):
            curve = draw_fn(x=x_data, y=y_data[:, i], **style)
            plot_lines.append(curve)
            self._update_marker_by_point_count(curve, x_data, style)

        return plot_lines

    def visible_status(self, plot_lines, signal):
        pass

    def do_impl_streaming(self, impl_plot: PlotItem, plot: Plot, cache_item):
        """
        Updates the X and Y view ranges of the ViewBox based on the most recent data received from the Streaming
        """
        vb = impl_plot.getViewBox()
        vb_x_limits = vb.viewRange()[0]
        ax_window = vb_x_limits[1] - vb_x_limits[0]

        # Time window
        now = int(datetime.now().timestamp() * 1e9)
        min_time = now - int(ax_window)

        all_y_data = []
        for signal_ref in cache_item.signals:
            signal = signal_ref()
            if signal.lines[0].isVisible() and len(signal.x_data) > 0:
                mask = (signal.x_data >= min_time) & (signal.x_data <= now)
                all_y_data.extend(signal.y_data[mask])

        if all_y_data:
            y_max = np.nanmax(all_y_data).item()
            y_min = np.nanmin(all_y_data).item()
            vb.setYRange(y_min, y_max, padding=0.1)

        begin = self.transform_value(impl_plot, 0, min_time, inverse=True)
        end = self.transform_value(impl_plot, 0, now, inverse=True)
        vb.setXRange(begin, end, padding=0)

    def set_line_data(self, line: PlotDataItem, x_data, y_data, style: dict):
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

    def get_ysub_data(self, plot: PlotXYWithSlider, y_data):
        return y_data[plot.slider.value()]

    def create_slider_plot_lines_1D(self, draw_fn, x_data, ysub_data, style) -> List[PlotDataItem]:
        return [draw_fn(x_data, ysub_data, **style)]

    def create_slider_plot_lines_2D(self, draw_fn, x_data, ysub_data, style):
        pass

    def slider_visible_status(self, plot_lines, signal):
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
                img.setRect(QtCore.QRectF(np.min(x_data)[0], np.min(y_data)[0], np.ptp(x_data), np.ptp(y_data)))
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

                    scale_x = np.ptp(x_data) / z_data.shape[1]
                    scale_y = np.ptp(y_data) / z_data.shape[0]
                    iso_curve.setTransform(
                        pg.Qt.QtGui.QTransform().scale(scale_x, scale_y).translate(np.min(x_data)[0] / scale_x,
                                                                                   np.min(y_data)[0] / scale_y))

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

    def update_area_envelope_1D(self, shapes, impl_plot: PlotItem, x_data, y1_data, y2_data, style):
        # Update FillBetweenItem
        area = shapes[0][2]
        if isinstance(area, FillBetweenItem):
            area.setCurves(shapes[0][0], shapes[0][1])

    def create_area_envelope_1D(self, draw_fn, impl_plot: Any, signal, x_data, y1_data, y2_data, style, style2):
        # Creation of FillBetweenItem
        curve_1 = [draw_fn(x=x_data, y=y1_data, **style)]  # type: List[PlotDataItem]
        curve_2 = [draw_fn(x=x_data, y=y2_data, **style2)]  # type: List[PlotDataItem]

        # Brush for FillBetweenItem
        pen = curve_1[0].opts['pen']
        qcolor = pen.color()
        brush = (qcolor.red(), qcolor.green(), qcolor.blue(), int(0.3 * 255))

        area = FillBetweenItem(curve1=curve_1[0], curve2=curve_2[0], brush=brush)
        impl_plot.addItem(area)

        plot_lines = [curve_1 + curve_2 + [area]]

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

    def get_canvas_plots(self):
        plots = []
        for stack in self._layout_stacks.values():
            for plot_item in stack.values():
                plots.append(plot_item)
        return plots

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

        # Annotate labels along the slider axis
        h_layout = QHBoxLayout()

        # Proxy widget
        rc_key = (row, col)
        proxy = QtWidgets.QGraphicsProxyWidget()
        container = QWidget()
        v_layout = QVBoxLayout(container)
        v_layout.setContentsMargins(0, 0, 0, 0)
        v_layout.setSpacing(0)
        v_layout.addWidget(slider)
        v_layout.addLayout(h_layout)
        proxy.setWidget(container)
        last_row_id = max(visible_stack_ids) + 1
        cell_gl.addItem(proxy, row=last_row_id, col=0)
        self._slider_placeholders[rc_key] = proxy

        # Get data for the slider
        slider_values = i_plot.signals[1][0].z_data

        # Slider labels
        min_label = QLabel(f"{pd.Timestamp(slider_values[0])}")
        max_label = QLabel(f"{pd.Timestamp(slider_values[-1])}")
        current_label = QLabel(F"{pd.Timestamp(slider_values[0])}")

        # Apply font_size for slider labels
        fs = self._pm.get_value(i_plot, 'font_size')
        if fs:
            qf = QFont()
            qf.setPointSize(int(fs))
            min_label.setFont(qf)
            current_label.setFont(qf)
            max_label.setFont(qf)

        h_layout.addWidget(min_label)
        h_layout.addStretch()
        h_layout.addWidget(current_label)
        h_layout.addStretch()
        h_layout.addWidget(max_label)

        # Register the callback function to update the plot when the slider value changes
        slider.valueChanged.connect(lambda val, i_p=i_plot: self._update_slider(val, i_p, slider_values, current_label))

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
                pi.getAxis('bottom').setStyle(showValues=False)
                self._layout_stacks[l_key][stack_id] = pi

            # Slider creation only if it doesn't exist
            if isinstance(i_plot, PlotXYWithSlider):
                cell_gl = self.process_ipl_plot_xy_slider(i_plot, row, col, visible_stack_ids, cell_gl)

            plot = self._layout_stacks[l_key][stack_id]
            plot.enableAutoRange(x=False, y=False)
            plot.hideButtons()
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
                self._signal_impl_plot_lut.update({signal.uid: plot})
                self.process_ipl_signal(signal)

            # Set limits for y axis
            # self.update_multi_range_axis(i_plot.axes[1], 1, plot)

            # Legend processing for downsampled data when drawing
            fs = self._pm.get_value(i_plot, 'font_size')  # Font size fot legend lines
            ix_legend = 0
            for signal in signals:
                plot.legend.items[ix_legend][1].setAttr(attr='size', value=f'{fs}pt')
                legend_label = plot.legend.items[ix_legend][1].text
                if signal.isDownsampled:
                    legend_label += '*'
                plot.legend.items[ix_legend][1].setText(legend_label)
                ix_legend += 1

            # Observe the axis limit change events
            vb = plot.getViewBox()
            vb.sigXRangeChanged.connect(self._x_axis_update_callback)
            vb.sigYRangeChanged.connect(self._y_axis_update_callback)

        self.set_bottom_axis_stacked(row, col, visible_stack_ids)
        if isinstance(i_plot.axes[0], RangeAxis) and i_plot.axes[0].is_date:
            cell_gl.addItem(axis_items["bottom"].common_label, row=len(i_plot.signals), col=0)

        # MODIFIED
        self.align_y_axis(row, col)

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
        plot.setTitle(i_plot.plot_title, color=fc, size=f'{fs}pt')

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
            # Clean
            for item in items:
                grid.removeItem(item)
            # Relocate
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
        # Check for 'same as canvas' value
        if leg_position == 'same as canvas':
            leg_position = 'upper right'
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

    def _y_axis_update_callback(self, view_box: ViewBox):
        if self.canvas.streaming:
            return
        current_plot = view_box.parentItem()  # type: PlotItem
        super()._y_axis_update_callback(current_plot)

        # MODIFIED
        for (r, c), stacks in self._layout_stacks.items():
            if current_plot in stacks.values():
                self.align_y_axis(r, c)
                break

    def _x_axis_update_callback(self, view_box: ViewBox):
        if self.canvas.streaming:
            return
        current_plot = view_box.parentItem()  # type: PlotItem
        super()._x_axis_update_callback(current_plot)

    def process_ipl_log_axis(self, axis_item: AxisItem, plot: Plot):
        if axis_item.orientation != 'left':
            return
        log_scale = self._pm.get_value(plot, 'log_scale')
        if log_scale:  # TODO: review log scale
            # Set log scale for AxisItem
            plot_item = axis_item.parentItem()
            plot_item.setLogMode(y=log_scale)
            # axis_item.setLogMode(log_scale)

    def process_ipl_axis_params(self, fc, fs, axis: Axis, axis_item: AxisItem):
        tick_props = dict(maxTickLevel=0)  # TODO: add color to tick values
        label_props = dict(color=fc)

        # Set ticks on the top and right axis
        if self._pm.get_value(self.canvas, 'ticks_position'):
            tick_props['maxTickLevel'] = 2
        else:
            tick_props['maxTickLevel'] = 0

        # Set color and font
        if fs is not None and fs > 0:
            tick_font = QFont()
            tick_font.setPointSize(int(fs))
            tick_props.update({'tickFont': tick_font})
            label_props.update({'font-size': f'{int(fs)}pt'})

        if axis.label is not None:
            axis_item.setLabel(axis.label, **label_props)

        # Font size for UTC label
        if isinstance(axis_item, NanosecondDateFormatter):
            axis_item.common_label.setText(axis_item.offset_str, size=f'{fs}pt')

        axis_item.setStyle(**tick_props)

    def process_ipl_axis_formatter(self, impl_plot: PlotItem, impl_axis: NanosecondDateFormatter, ax_idx: int):
        ci = self._impl_plot_cache_table.get_cache_item(impl_plot)
        impl_axis.set_offset(ci.offsets[ax_idx])

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
        # impl_plot.vb.enableAutoRange(y=autoscale)

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
            ci = self._impl_plot_cache_table.get_cache_item(impl_plot)
            plot = ci.plot()
            self._focus_plot = plot
            row = plot.row - 1
            col = plot.col - 1
            stack_id = ci.stack_key

        """
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
                             plot_item.getAxis("bottom").common_label.setVisible(
                                 r == row and c == col and s_id == stack_id)
                         self.set_bottom_axis_stacked(row, col, [stack_id])
    
         for key, value in self._slider_placeholders.items():
             if key == (row, col):
                 continue
             value.setVisible(un_focus)
         """

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

    # MODIFIED
    def align_y_axis(self, row: int, col: int) -> None:
        stacks = self._layout_stacks.get((row, col))
        if not stacks:
            return

        for p in stacks.values():
            if p:
                p.getAxis('left').setWidth(None)

        max_w = 0.0
        for p in stacks.values():
            if not p:
                continue
            ax = p.getAxis('left')
            vb = p.getViewBox()
            y0, y1 = vb.viewRange()[1]
            if y0 == 0 and y1 == 1:
                continue
            tv = ax.tickValues(y0, y1, vb.height())
            if not tv:
                continue
            spacing, values = tv[0]
            labels = ax.tickStrings(values, scale=1.0, spacing=spacing)
            fm = QFontMetricsF(ax.style.get('tickFont') or QtWidgets.QApplication.font())
            text_w = max((fm.horizontalAdvance(str(s)) for s in labels), default=0.0)
            label_w = ax.label.boundingRect().height() if ax.label.isVisible() else 0.0
            if text_w + label_w > max_w:
                max_w = text_w + label_w

        if max_w <= 0:
            return

        w = int(max_w)
        for p in stacks.values():
            if p:
                p.getAxis('left').setWidth(w)

        gl = getattr(self, '_graphics_layout', None)
        if gl:
            gl.updateGeometry()

    def transform_value(self, impl_plot: Any, ax_idx: int, value: Any, inverse=False):
        """Adds or subtracts axis offset from value trying to preserve type of offset (ex: does not convert to
        float when offset is int)"""
        return self._impl_plot_cache_table.transform_value(impl_plot, ax_idx, value, inverse=inverse)
