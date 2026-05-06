# Changelog:
#   Jan 2023:   -Added support for legend position and layout [Alberto Luengo]
import gc
import os
from datetime import datetime
from typing import Any, Callable, Collection, List, Tuple
import numpy as np
import pandas as pd
import pyqtgraph as pg
from PySide6.QtCore import Signal as QtSignal
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QFontMetricsF, QTransform
from pyqtgraph import PlotItem, AxisItem, PlotDataItem, IsocurveItem, ViewBox, LegendItem, PColorMeshItem
from pyqtgraph.Qt import OpenGLConstants as GLC
from pyqtgraph.Qt import QtCore, QtWidgets
from pyqtgraph.Qt.QtWidgets import QSlider, QHBoxLayout, QVBoxLayout, QLabel, QWidget
from pyqtgraph import TextItem

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

IPLOT_PYQTGRAPH_OPENGL = os.environ.get('IPLOT_PYQTGRAPH_OPENGL', "").lower()
use_open_gl = IPLOT_PYQTGRAPH_OPENGL in ("1", "true", "yes") if IPLOT_PYQTGRAPH_OPENGL else False

pg.setConfigOptions(antialias=True, useOpenGL=use_open_gl)


class _AlphaColorMeshItem(PColorMeshItem):
    """PColorMeshItem subclass with OpenGL alpha blending support.

    When OpenGL is active (useOpenGL=True), pyqtgraph's PColorMeshItem
    renders via paintGL() which does NOT enable blending by default —
    semi-transparent colors appear fully opaque.

    This subclass wraps paintGL() to enable GL_BLEND with standard
    alpha compositing (SRC_ALPHA, ONE_MINUS_SRC_ALPHA) before rendering,
    and disables it after to avoid side effects on other items.

    Used by the envelope visualization (create_area_envelope_1D) to
    render the filled min/max area with 30% opacity behind the curves.
    """

    def paintGL(self, widget):
        glf = widget.getFunctions()
        glf.glEnable(GLC.GL_BLEND)
        glf.glBlendFunc(GLC.GL_SRC_ALPHA, GLC.GL_ONE_MINUS_SRC_ALPHA)
        super().paintGL(widget)
        glf.glDisable(GLC.GL_BLEND)


class QtViewBox(pg.ViewBox):
    pressed = QtSignal(object, object)
    released = QtSignal(object, object)
    dragged = QtSignal(object, object)  # For drag events during mouse move with button pressed

    def __init__(self, parent=None):
        super().__init__(parent=parent, enableMenu=False)
        self.sigRangeChangedManually.connect(self.release_event)
        self._right_click_pan_handled = False

    def mousePressEvent(self, ev):
        self._right_click_pan_handled = False
        # Right click PAN has no effect
        if ev.button() == Qt.MouseButton.RightButton and self.getState()['mouseEnabled'] == [True, True]:
            ev.accept()
            self.released.emit(self, ev)
            self._right_click_pan_handled = True
            return
        super().mousePressEvent(ev)
        self.pressed.emit(self, ev)

    def mouseMoveEvent(self, ev):
        super().mouseMoveEvent(ev)
        # Emit dragged signal when mouse moves (for drag preview)
        self.dragged.emit(self, ev)

    def mouseReleaseEvent(self, ev):
        super().mouseReleaseEvent(ev)
        if not self._right_click_pan_handled:
            self.released.emit(self, ev)

    def release_event(self):
        self.released.emit(self, None)

    def mouseClickEvent(self, ev):
        super().mouseClickEvent(ev)
        if not self._right_click_pan_handled:
            self.released.emit(self, ev)

    def wheelEvent(self, ev, axis=None):
        ev.ignore()


class PyQtGraphParser(BackendParserBase):
    def __init__(self,
                 canvas: Canvas = None,
                 tight_layout: bool = True,
                 focus_plot=None,
                 focus_plot_stack_key=None,
                 impl_flush_method: Callable = None) -> None:
        # Initialize before super().__init__() because it calls clear() via process_ipl_canvas
        self.map_legend_to_ax = {}
        self._legend_signal_lut = {}  # id(ItemSample/LabelItem) -> Signal
        self._on_legend_right_click = None  # callback(Signal) set by Qt canvas
        self.legend_size = 8
        self._cursors = []
        self._cursor_active = False
        self._grid_spacing_labels = {}  # PlotItem -> TextItem
        self._cell_gl = {}
        self._layout_stacks = {}
        self._slider_placeholders = {}
        self._impl_plot_ranges_hash = dict()
        self._colorbar_lut = dict()
        self._row_offset = 0

        super().__init__(canvas=canvas, focus_plot=focus_plot, focus_plot_stack_key=focus_plot_stack_key,
                         impl_flush_method=impl_flush_method)

        self.figure = pg.GraphicsLayoutWidget()
        self.figure.setBackground('w')

        if tight_layout:
            self.enable_tight_layout()
        else:
            self.disable_tight_layout()

    def _ensure_cell_layout(self, row: int, col: int, rowspan: int, colspan: int):
        key = (row, col)
        cell_gl = self._cell_gl.get(key)
        if cell_gl is None:
            rspan = max(1, rowspan)
            cspan = max(1, colspan)
            layout_row = row + self._row_offset
            end_row = layout_row + rspan - 1
            end_col = col + cspan - 1

            lay = self.figure.ci.layout
            lay.setRowStretchFactor(end_row, 1)
            lay.setColumnStretchFactor(end_col, 1)

            cell_gl = pg.GraphicsLayout()
            cell_gl.layout.setSpacing(0)  # Reduce vertical spacing between stacked plots
            cell_gl.layout.setContentsMargins(0, 0, 0, 0)
            self.figure.addItem(cell_gl, row=layout_row, col=col, rowspan=rowspan, colspan=colspan)
            self._cell_gl[key] = cell_gl
        return cell_gl

    def export_image(self, filename: str, **kwargs):
        canvas = kwargs.get('canvas')
        if canvas:
            self.process_ipl_canvas(canvas)

        ext = os.path.splitext(filename)[1].lower() if '.' in filename else '.png'
        if ext == '.svg':
            from pyqtgraph.exporters import SVGExporter
            exporter = SVGExporter(self.figure.scene())
            exporter.export(filename)
        else:
            from pyqtgraph.exporters import ImageExporter
            exporter = ImageExporter(self.figure.scene())
            width = kwargs.get('width', 1920)
            exporter.parameters()['width'] = width
            exporter.export(filename)

    def legend_downsampled_signal(self, signal, impl_plot: PlotItem, plot_lines: PlotDataItem):
        """
        Add or removes a '*' in the legend label to indicate if the signal is downsampled or not
        """
        legend = impl_plot.legend
        if not legend:
            return

        # Skip if line is not visible (hidden signals are not in legend)
        if not plot_lines.isVisible():
            return

        lines = [lines[0].item.name() for lines in legend.items]
        if plot_lines.name() not in lines:
            return
        pos = lines.index(plot_lines.name())
        legend_label = legend.items[pos][1]
        legend_text = legend.items[pos][1].text

        if legend_text.endswith('*') and not signal.isDownsampled:
            legend_label.setText(legend_text[:-1])
        elif not legend_text.endswith('*') and signal.isDownsampled:
            legend_label.setText(legend_text + '*')

    def set_signal_visible(self, signal, visible: bool):
        """Set visibility of signal lines."""
        if hasattr(signal, 'lines') and signal.lines:
            for line in signal.lines:
                line.setVisible(visible)

    def remove_signal_lines(self, signal):
        """Remove signal lines from the plot."""
        if hasattr(signal, 'lines') and signal.lines:
            for line in signal.lines:
                if hasattr(line, 'scene') and line.scene():
                    line.scene().removeItem(line)

    def remove_signal_from_legend(self, impl_plot: PlotItem, signal):
        """Remove signal from legend."""
        if not impl_plot.legend:
            return
        if hasattr(signal, 'lines') and signal.lines:
            try:
                impl_plot.legend.removeItem(signal.lines[0])
            except Exception:
                pass
        # Also try by name
        label = getattr(signal, 'label', '') or getattr(signal, 'name', '')
        if label:
            try:
                impl_plot.legend.removeItem(label)
            except Exception:
                pass

    def add_signal_to_legend(self, impl_plot: PlotItem, signal):
        """Add signal to legend."""
        if impl_plot.legend and hasattr(signal, 'lines') and signal.lines:
            label = getattr(signal, 'label', '') or getattr(signal, 'name', '')
            impl_plot.legend.addItem(signal.lines[0], label)

    def rebuild_legend(self, impl_plot: PlotItem, plot):
        """Rebuild legend for PyQtGraph based on visible signals."""
        if not impl_plot.legend:
            return

        # Clear existing legend items
        impl_plot.legend.clear()

        # Get cache item to find signals
        ci = self._impl_plot_cache_table.get_cache_item(impl_plot)
        if not ci or not hasattr(ci, 'signals'):
            return

        # Add visible signals to legend
        for sig_ref in ci.signals:
            sig = sig_ref() if sig_ref else None
            if sig and hasattr(sig, 'lines') and sig.lines:
                # Check if signal is visible and still in scene
                line = sig.lines[0]
                in_scene = hasattr(line, 'scene') and line.scene() is not None
                if in_scene and hasattr(line, 'isVisible') and line.isVisible():
                    label = getattr(sig, 'label', '') or getattr(sig, 'name', '')
                    if label:
                        impl_plot.legend.addItem(line, label)

    def register_dynamic_signal(self, impl_plot: PlotItem, plot, signal):
        """Register a dynamically added signal and update legend."""
        import weakref
        cache_item = self._impl_plot_cache_table.get_cache_item(impl_plot)
        if cache_item and hasattr(cache_item, 'signals'):
            cache_item.signals.append(weakref.ref(signal))
        self.rebuild_legend(impl_plot, plot)

    @staticmethod
    def _update_marker_by_point_count(marker_line: PlotDataItem, signal_x_data, signal_style: dict):
        if len(signal_x_data) == 1:
            marker_line.setSymbol('x')
            marker_line.setSymbolSize(5)
        else:
            symbol = signal_style.get('symbol')
            marker_line.setSymbol(symbol or None)

    def create_plot_lines_1D(self, draw_fn, x_data, y_data, style):
        line = draw_fn(x=x_data, y=y_data, **style)
        return [line]

    def create_plot_lines_2D(self, draw_fn, signal, x_data, y_data, style):
        plot_lines = []
        for i in range(y_data.shape[1]):
            style_i = dict(**style)
            line_color = PlotXY._color_cycle[i % len(PlotXY._color_cycle)]
            pen = pg.mkPen(style_i['pen'])
            pen.setColor(line_color)
            style_i['pen'] = pen
            style_i['symbolPen'] = line_color
            style_i['symbolBrush'] = line_color

            curve = draw_fn(x=x_data, y=y_data[:, i], **style_i)
            curve.opts["name"] = f"{signal.label}[{i}]"
            self._update_marker_by_point_count(curve, x_data, style)
            plot_lines.append(curve)

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
            if not signal.lines[0].isVisible():
                continue
            # Snapshot x/y once: the receiver thread can update them between reads.
            x_data = signal.x_data
            y_data = signal.y_data
            n = min(len(x_data), len(y_data))
            if n == 0:
                continue
            x_data = x_data[:n]
            y_data = y_data[:n]
            mask = (x_data >= min_time) & (x_data <= now)
            all_y_data.extend(y_data[mask])

        if all_y_data:
            y_max = np.nanmax(all_y_data).item()
            y_min = np.nanmin(all_y_data).item()
            vb.setYRange(y_min, y_max, padding=0.1)

        begin = self.transform_value(impl_plot, 0, min_time, inverse=True)
        end = self.transform_value(impl_plot, 0, now, inverse=True)
        vb.setXRange(begin, end, padding=0.02)

    def _apply_xrange(self, impl_plot: PlotItem, begin, end):
        impl_plot.getViewBox().setXRange(begin, end, padding=0.02)

    def set_line_data(self, line: PlotDataItem, x_data, y_data):
        """
        Set the data for a PlotDataItem based on the attributes of SignalXY.
        """
        line.setData(x=x_data, y=y_data)

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
            line.setSymbolBrush(style['symbolBrush'])

    def get_signal_style(self, signal: SignalXY) -> dict:
        """
        Returns a dict of arguments for PlotDataItem based on the attributes of SignalXY
        """
        style = {'name': signal.label}

        signal_color = self._pm.get_value(signal, 'color')
        color = signal_color if signal_color is not None else signal.original_color
        line_size = self._pm.get_value(signal, 'line_size')
        line_style = self._pm.get_value(signal, 'line_style').lower()
        if line_size == 0 or line_style == 'none':
            pen = None
        else:
            pen = pg.mkPen(
                color=color,
                width=line_size,
                style=LINESTYLE_MAP.get(line_style, QtCore.Qt.PenStyle.SolidLine),
                cosmetic=True
            )
        style['pen'] = pen

        marker = self._pm.get_value(signal, 'marker')
        if marker != 'None':
            style['symbol'] = self._pm.get_value(signal, 'marker')
            style['symbolSize'] = self._pm.get_value(signal, 'marker_size')
            marker_color = self._pm.get_value(signal, 'color')
            style['symbolPen'] = marker_color
            style['symbolBrush'] = marker_color

        step = self._pm.get_value(signal, 'step') or 'linear'
        step_mode = STEP_MAP_PG.get(step)
        style['stepMode'] = step_mode
        style['antialias'] = True

        return style

    def get_line_label(self, line: PlotDataItem):
        return line.name()

    def get_ysub_data(self, plot: PlotXYWithSlider, y_data):
        return y_data[plot.slider.value()]

    def create_slider_plot_lines_1D(self, draw_fn, x_data, ysub_data, style) -> List[PlotDataItem]:
        return [draw_fn(x_data, ysub_data, **style)]

    def create_slider_plot_lines_2D(self, draw_fn, x_data, ysub_data, style):
        pass

    def slider_visible_status(self, plot_lines, signal):
        pass

    def set_image_limits(self, ax_idx, signal, impl_plot: PlotItem):
        data = np.arange(0, len(signal.x_data) + 1).astype(float)
        # data[0] -= 0.5
        # data[-1] += 0.5

        origin = self._pm.get_value(signal.parent(), 'origin')
        if ax_idx == 1 and origin == 'upper':
            impl_plot.invertY(True)

        return data

    def create_image(self, impl_plot: PlotItem, plot: PlotImage, cache_item, data):
        origin = self._pm.get_value(plot, 'origin')
        data = np.asarray(data, dtype=float)

        img = pg.ImageItem(axisOrder='row-major', border='w', colorMap='viridis')  # type: ImageItem
        impl_plot.addItem(img)

        img.setImage(data)

        vb = impl_plot.getViewBox()
        # vb.setAspectLocked(True)

        # if origin == 'upper':
        #     impl_plot.invertY(True)

        return img

    def do_impl_line_plot_contour(self, signal: SignalContour, plot_item: PlotItem, plot: PlotContour, x_data, y_data,
                                  z_data):
        plot_lines = self._signal_impl_shape_lut.get(id(signal))  # type: List[IsocurveItem]
        contour_filled = self._pm.get_value(plot, 'contour_filled')
        contour_levels = self._pm.get_value(signal, 'contour_levels')
        color_map = self._pm.get_value(signal, 'color_map')
        curves = []

        # TODO: Check size z_data
        if plot_lines is not None:
            for curve in plot_lines:
                if isinstance(curve, IsocurveItem):
                    curve.setParentItem(None)
                    plot_item.removeItem(curve)
            plot_lines.clear()
        else:
            if contour_filled:
                img = pg.ImageItem(z_data)
            else:
                img = pg.ImageItem()

            if x_data.ndim == y_data.ndim == z_data.ndim == 2:
                x_min, x_max = np.min(x_data).item(), np.max(x_data).item()
                y_min, y_max = np.min(y_data).item(), np.max(y_data).item()
                z_min, z_max = np.min(z_data).item(), np.max(z_data).item()

                # 1. Configure and add the image first, before any children
                # Set rectangle view for the image. Values correspond to: x, y, w, h
                # Transformations needed to convert pixels into real data values
                img.setRect(QtCore.QRectF(x_min, y_min, np.ptp(x_data), np.ptp(y_data)))

                tr = QTransform()
                tr.translate(x_min, y_min)
                tr.scale((x_max - x_min) / np.shape(z_data)[0], (y_max - y_min) / np.shape(z_data)[1])
                img.setTransform(tr)
                if contour_filled:
                    img.setImage(z_data)
                plot_item.addItem(img)

                # 2. Set ColorBarItem
                colormap_obj = pg.colormap.get(color_map)
                img.setColorMap(colormap_obj)

                bar = self._colorbar_lut.get(id(signal))
                bar.setImageItem(img)
                bar.setLevels(low=z_min, high=z_max)

                # 3. Isocurves creation after img is fully set up in the scene
                levels = np.linspace(z_min, z_max, contour_levels)
                lut = None if contour_filled else colormap_obj.getLookupTable(nPts=256, alpha=False)
                z_range = z_max - z_min

                for i, level in enumerate(levels):
                    if contour_filled:
                        pen = (i, len(levels) * 1.5)
                    else:
                        norm = (level - z_min) / z_range if z_range != 0.0 else 0.0
                        r, g, b = lut[int(norm * 255)]
                        pen = pg.mkPen(color=(int(r), int(g), int(b)), cosmetic=True)

                    iso_curve = pg.IsocurveItem(data=z_data, level=level, pen=pen)
                    iso_curve.setZValue(10)
                    iso_curve.setParentItem(img)
                    curves.append(iso_curve)
            return curves

    def do_impl_line_plot_contour_slider(self, signal: SignalContour, plot_item: PlotItem, plot: PlotContourWithSlider,
                                         x_data, y_data, z_data):

        plot_lines = self._signal_impl_shape_lut.get(id(signal))  # type: List[IsocurveItem]

        # Contour parameters
        contour_filled = self._pm.get_value(plot, 'contour_filled')
        contour_levels = self._pm.get_value(signal, 'contour_levels')
        color_map = self._pm.get_value(signal, 'color_map')
        curves = []

        # Slider data
        x_sub_data = x_data[plot.slider.value()]
        y_sub_data = y_data[plot.slider.value()]
        z_sub_data = z_data[plot.slider.value()]

        if plot_lines is not None:
            for curve in plot_lines:
                if isinstance(curve, IsocurveItem):
                    curve.setParentItem(None)
                    plot_item.removeItem(curve)
            plot_lines.clear()

        if contour_filled:
            img = pg.ImageItem(z_data)
        else:
            img = pg.ImageItem()

        if x_sub_data.ndim == y_sub_data.ndim == z_sub_data.ndim == 2:
            x_min, x_max = np.min(x_sub_data).item(), np.max(x_sub_data).item()
            y_min, y_max = np.min(y_sub_data).item(), np.max(y_sub_data).item()
            z_min, z_max = np.min(z_sub_data).item(), np.max(z_sub_data).item()

            # 1. Configure and add the image first, before any children
            # Set rectangle view for the image. Values correspond to: x, y, w, h
            # Transformations needed to convert pixels into real data values
            img.setRect(QtCore.QRectF(x_min, y_min, np.ptp(x_sub_data), np.ptp(y_sub_data)))

            # scale() - Moves origin from (0,0) to the data minimum
            # translate() - Each pixel in X becomes (x_max - x_min)/ n_cols wide, and each pixel in Y becomes
            # (y_max - y_min) / n_rows tall
            tr = QTransform()
            tr.translate(x_min, y_min)
            tr.scale((x_max - x_min) / np.shape(z_sub_data)[0], (y_max - y_min) / np.shape(z_sub_data)[1])
            img.setTransform(tr)
            if contour_filled:
                img.setImage(z_sub_data)
            plot_item.addItem(img)

            # 2. Set ColorBarItem
            colormap_obj = pg.colormap.get(color_map)
            img.setColorMap(colormap_obj)

            bar = self._colorbar_lut.get(id(signal))
            bar.setImageItem(img)
            bar.setLevels(low=z_min, high=z_max)

            # 3. Isocurves creation after img is fully set up in the scene
            levels = np.linspace(z_min, z_max, contour_levels)
            lut = None if contour_filled else colormap_obj.getLookupTable(nPts=256, alpha=False)
            z_range = z_max - z_min

            for i, level in enumerate(levels):
                if contour_filled:
                    pen = (i, len(levels) * 1.5)
                else:
                    norm = (level - z_min) / z_range if z_range != 0.0 else 0.0
                    r, g, b = lut[int(norm * 255)]
                    pen = pg.mkPen(color=(int(r), int(g), int(b)), cosmetic=True)

                iso_curve = pg.IsocurveItem(data=z_sub_data, level=level, pen=pen)
                iso_curve.setZValue(10)
                iso_curve.setParentItem(img)
                curves.append(iso_curve)
        return curves

    def update_area_envelope_1D(self, shapes, impl_plot: PlotItem, x_data, y1_data, y2_data, style):
        area = shapes[0][3]
        if isinstance(area, _AlphaColorMeshItem):
            x_mesh = np.vstack([x_data, x_data])
            y_mesh = np.vstack([y2_data, y1_data])
            z_mesh = np.ones((1, len(x_data) - 1))
            area.setData(x_mesh, y_mesh, z_mesh)

    def create_area_envelope_1D(self, draw_fn, impl_plot: Any, signal, x_data, y1_data, y2_data, y3_data, style,
                                style2):

        # Create PlotDataItem curves for min, max and average data
        curve_1 = [draw_fn(x=x_data, y=y1_data, **style)]  # type: List[PlotDataItem]
        curve_2 = [draw_fn(x=x_data, y=y2_data, **style2)]  # type: List[PlotDataItem]
        curve_3 = [draw_fn(x=x_data, y=y3_data, **style2)]  # type: List[PlotDataItem]

        # Extract base color from the min curve and create a semi-transparent uniform colormap for the envelope area
        pen = curve_1[0].opts['pen']
        qcolor = pen.color()
        rgba = np.array([[qcolor.red(), qcolor.green(), qcolor.blue(), int(0.3 * 255)]])
        cmap = pg.ColorMap([0.0, 1.0], np.vstack([rgba, rgba]))

        # Build mesh grids
        x_mesh = np.vstack([x_data, x_data])
        y_mesh = np.vstack([y2_data, y1_data])
        z_mesh = np.ones((1, len(x_data) - 1))

        area = _AlphaColorMeshItem(x_mesh, y_mesh, z_mesh, colorMap=cmap, edgecolors=None)
        area.setZValue(-1)
        impl_plot.addItem(area)

        plot_lines = [curve_1 + curve_2 + curve_3 + [area]]

        return plot_lines

    def set_suptitle(self, title: str, font_size: int = None, font_color: str = 'black'):
        suptitle = pg.LabelItem(justify='center')
        cols = self._grid_shape[1] if hasattr(self, "_grid_shape") else 1
        self.figure.addItem(suptitle, row=0, col=0, colspan=cols)

        if font_size:
            suptitle.setText(title, size=f'{font_size}pt', color=font_color)
        else:
            suptitle.setText(title, color=font_color)

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

    def process_ipl_plot_contour_colorbar(self, i_plot: PlotContour | PlotContourWithSlider, visible_stack_ids,
                                          cell_gl):
        z_data = i_plot.signals[1][0].z_data
        color_map = self._pm.get_value(i_plot.signals[1][0], 'color_map')
        colormap_obj = pg.colormap.get(color_map)

        previous_bar = self._colorbar_lut.get(id(i_plot.signals[1][0]))
        if previous_bar is None:
            bar = pg.ColorBarItem(values=(np.min(z_data).item(), np.max(z_data).item()),
                                  colorMap=colormap_obj,
                                  label='Z value',
                                  interactive=False)
            cell_gl.addItem(bar, row=visible_stack_ids[0] + 1, col=1)
            self._colorbar_lut[id(i_plot.signals[1][0])] = bar

        return cell_gl

    def process_ipl_plot_xy_slider(self, i_plot: PlotXYWithSlider | PlotContourWithSlider, row, col,
                                   visible_stack_ids, cell_gl):
        # Maximum index value for the slider based on the y-data length
        if isinstance(i_plot, PlotXYWithSlider):
            val_max = i_plot.signals[1][0].y_data.shape[0] - 1
        else:
            val_max = i_plot.signals[1][0].time.shape[0] - 1

        # Slider creation
        slider = QSlider(QtCore.Qt.Orientation.Horizontal)
        slider.setMinimum(0)
        slider.setMaximum(val_max)
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
        last_row_id = max(visible_stack_ids) + 2
        cell_gl.addItem(proxy, row=last_row_id, col=0)
        cell_gl.layout.setRowMinimumHeight(last_row_id, 30)
        self._slider_placeholders[rc_key] = proxy

        # Set colormap in case of PlotContourWithSlider
        if isinstance(i_plot, PlotContourWithSlider):
            cell_gl = self.process_ipl_plot_contour_colorbar(i_plot, visible_stack_ids, cell_gl)

        # Get data for the slider
        slider_values = i_plot.signals[1][0].time
        formatter = NanosecondDateFormatter(orientation='bottom')
        is_date = bool(min(slider_values) > (1 << 53) and max(slider_values) < (1 << 62))

        # Set slider labels
        if is_date:
            min_value = pd.Timestamp(slider_values[0]).value
            max_value = pd.Timestamp(slider_values[-1]).value

            # Format start, current and end timestamps
            # Reduced format for current value and end value
            start_format = formatter.date_fmt(min_value, formatter.YEAR, formatter.NANOSECOND, postfix_end=True)
            current_format = formatter.date_fmt(min_value, formatter.cut_start + 3, formatter.NANOSECOND,
                                                postfix_end=True)
            end_format = formatter.date_fmt(max_value, formatter.cut_start + 3, formatter.NANOSECOND,
                                            postfix_end=True)
            min_label = QLabel(start_format)
            max_label = QLabel(end_format)
            current_label = QLabel(current_format)
        else:
            min_label = QLabel(f"{slider_values[0]}")
            max_label = QLabel(f"{slider_values[-1]}")
            current_label = QLabel(F"{slider_values[0]}")

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

        # Check if there was a previous plot_with_slider with a value
        if i_plot.slider_last_val is not None:
            value = i_plot.slider_last_val
            # Update current value label
            if is_date:
                current_value = pd.Timestamp(slider_values[int(value)]).value
                current_label.setText(
                    formatter.date_fmt(current_value, formatter.cut_start + 3, formatter.NANOSECOND,
                                       postfix_end=True))
            else:
                current_value = slider_values[int(value)]
                current_label.setText(str(current_value))
        else:
            value = 0
            i_plot.slider_last_val = value

        slider.setValue(value)

        # Register the callback function to update the plot when the slider value changes
        slider.valueChanged.connect(
            lambda val, i_p=i_plot: self._update_slider(val, i_p, slider_values, current_label, formatter))

        # Check if the PlotXYWithSlider had a previously defined min/max range for the slider
        slider_min = i_plot.slider_last_min
        slider_max = i_plot.slider_last_max

        if slider_min is not None and slider_max is not None:
            # If the minimum and maximum values of a PlotXYWithSlider differ from their original values, it means
            # they were modified due to a zoom action performed on a PlotXY that shares the same shared time.
            # Therefore, when the PlotXYWithSlider is processed again, the red highlighted area should continue
            # to be displayed, provided that the shared time is still active.
            if (slider_min != 0 or slider_max != val_max) and self._pm.get_value(self.canvas, 'shared_x_axis'):
                # Update the slider range based on previous limits
                i_plot.slider.setMinimum(slider_min)
                i_plot.slider.setMaximum(slider_max)

                # Set current value according to slider limits
                val = i_plot.slider.value()
                if val < slider_min:
                    val = slider_min
                elif val > slider_max:
                    val = slider_max
                i_plot.slider.setValue(val)

                # Update min and max label
                if is_date:
                    min_value = pd.Timestamp(slider_values[int(slider_min)]).value
                    min_label.setText(
                        formatter.date_fmt(min_value, formatter.YEAR, formatter.NANOSECOND,
                                           postfix_end=True))
                    max_value = pd.Timestamp(slider_values[int(slider_max)]).value
                    max_label.setText(
                        formatter.date_fmt(max_value, formatter.cut_start + 3, formatter.NANOSECOND,
                                           postfix_end=True))
                else:
                    min_value = slider_values[int(slider_min)]
                    min_label.setText(str(min_value))
                    max_value = slider_values[int(slider_max)]
                    max_label.setText(str(max_value))

                # Update slider limits
                slider.setMinimum(slider_min)
                slider.setMaximum(slider_max)
            else:
                i_plot.slider_last_min = 0
                i_plot.slider_last_max = val_max
        else:
            # Initialize the PlotXYWithSlider range when no previous limits are set
            i_plot.slider_last_min = 0
            i_plot.slider_last_max = val_max

        return cell_gl

    def get_slider_val(self, plot: PlotXYWithSlider):
        return plot.slider.value()

    def process_ipl_plot(self, i_plot: Plot, col: int, row: int):
        if not isinstance(i_plot, Plot):
            return

        cell_gl = self._ensure_cell_layout(row, col, i_plot.row_span, i_plot.col_span)

        visible_stack_ids = []
        axis_items = {}
        plot = None
        l_key = (row, col)
        stack_map = self._layout_stacks.setdefault(l_key, {})

        full_mode_all_stack = self._pm.get_value(self.canvas, "full_mode_all_stack")
        focus_stack_key = self._focus_plot_stack_key

        for stack_id, key in enumerate(i_plot.signals):
            if focus_stack_key is not None and not full_mode_all_stack and key != focus_stack_key:
                continue

            if isinstance(i_plot.axes[0], RangeAxis) and i_plot.axes[0].is_date:
                axis_items["bottom"] = NanosecondDateFormatter(orientation='bottom')
            else:
                axis_items["bottom"] = NanosecondDateFormatter(is_date=False, orientation='bottom')

            axis_items["left"] = NanosecondDateFormatter(is_date=False, orientation='left')

            signals = i_plot.signals.get(key) or list()

            if focus_stack_key is not None and not full_mode_all_stack:
                row_id = 0
            else:
                row_id = stack_id

            visible_stack_ids.append(row_id)

            if row_id not in stack_map:
                pi = pg.PlotItem(viewBox=QtViewBox(), axisItems=axis_items)
                # Compact layout only for non-stacked plots
                if len(i_plot.signals) <= 1:
                    pi.showAxes((True, True, True, True), showValues=(True, False, False, True))
                    pi.layout.setContentsMargins(0, 0, 0, 0)
                # Add space for expo
                if stack_id == 0:
                    cell_gl.addItem(axis_items["left"].common_label, row=0, col=0)

                # Add Plot Item
                cell_gl.addItem(pi, row=row_id + 1, col=0)
                if row_id > 0:
                    pi.getAxis('bottom').setStyle(showValues=False)
                stack_map[row_id] = pi

            # Slider creation only if it doesn't exist
            if isinstance(i_plot, (PlotXYWithSlider, PlotContourWithSlider)):
                cell_gl = self.process_ipl_plot_xy_slider(i_plot, row, col, visible_stack_ids, cell_gl)

            elif isinstance(i_plot, PlotContour):
                cell_gl = self.process_ipl_plot_contour_colorbar(i_plot, visible_stack_ids, cell_gl)

            plot = stack_map[row_id]
            plot.enableAutoRange(x=False, y=False)
            plot.hideButtons()
            self._plot_impl_plot_lut[id(i_plot)].append(plot)

            # Keep references to iplotlib instances for ease of access in callbacks.
            self._impl_plot_cache_table.register(plot, self.canvas, i_plot, key, signals)

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

            # Legend processing for downsampled data when drawing
            fs = self._pm.get_value(i_plot, 'font_size')  # Font size fot legend lines
            ix_legend = 0

            if plot.legend and plot.legend.items:
                # Set legend_lines and build legend → signal mapping
                legend_samples = [sample
                                  for item in plot.legend.items
                                  for sample in item
                                  if isinstance(sample, pg.ItemSample)]
                legend_lines = [sample.item for sample in legend_samples]

                for signal in signals:
                    for line in self._signal_impl_shape_lut.get(id(signal)):
                        self.map_legend_to_ax[legend_lines[ix_legend]] = line
                        self._legend_signal_lut[id(legend_samples[ix_legend])] = signal
                        label_item = plot.legend.items[ix_legend][1]
                        self._legend_signal_lut[id(label_item)] = signal
                        # Patch ItemSample to handle right-click for signal preferences
                        sample = legend_samples[ix_legend]
                        orig_handler = sample.mouseClickEvent
                        def _patched_click(ev, orig=orig_handler, sig=signal, parser=self):
                            if ev.button() == QtCore.Qt.MouseButton.RightButton:
                                if parser._on_legend_right_click:
                                    parser._on_legend_right_click(sig, ev.screenPos())
                                ev.accept()
                                return
                            orig(ev)
                        sample.mouseClickEvent = _patched_click
                        label_item.setAttr(attr='size', value=f'{fs}pt')
                        legend_label = line.name() if not isinstance(line, Collection) else line[0].name()
                        if signal.isDownsampled:
                            legend_label += '*'
                        label_item.setText(legend_label)
                        size = label_item.sizeHint(QtCore.Qt.SizeHint.PreferredSize, None)
                        label_item.resize(size)
                        ix_legend += 1
                plot.legend.updateSize()
                self._auto_adjust_legend_layout(plot, i_plot, signals)

            # Observe the axis limit change events
            vb = plot.getViewBox()
            if not isinstance(i_plot, (PlotContour, PlotContourWithSlider)):
                vb.sigXRangeChanged.connect(self._x_axis_update_callback)
                vb.sigYRangeChanged.connect(self._y_axis_update_callback)

        self.set_bottom_axis_stacked(row, col, visible_stack_ids)
        if isinstance(i_plot.axes[0], RangeAxis):
            cell_gl.addItem(axis_items["bottom"].common_label, row=len(i_plot.signals) + 1, col=0)

        self.align_y_axis(col)

        # Update grid spacing labels after all data and axes are configured
        for plot in stack_map.values():
            self.update_grid_spacing_label(plot)

    def set_bottom_axis_stacked(self, row: int, col: int, visible_stacks: List[int]):
        if not visible_stacks:
            return

        max_stack = max(visible_stacks)
        stack_dict = self._layout_stacks.get((row, col), {})

        for s_id in set(visible_stacks):
            plot_item = stack_dict.get(s_id)
            if plot_item is None:
                continue

            axis = plot_item.getAxis('bottom')
            show = (s_id == max_stack)

            axis.setStyle(showValues=show)
            if axis.label is not None:
                axis.label.setVisible(show)

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

        # Show the plot legend if enabled
        show_legend = self._pm.get_value(i_plot, 'legend')
        if not show_legend:
            plot.legend = None
            return

        plot_leg_position = self._pm.get_value(i_plot, 'legend_position')
        canvas_leg_position = self._pm.get_value(self.canvas, 'legend_position')
        plot_leg_layout = self._pm.get_value(i_plot, 'legend_layout')
        canvas_leg_layout = self._pm.get_value(self.canvas, 'legend_layout')

        if plot_leg_position == 'same as canvas':
            plot_leg_position = canvas_leg_position
        if plot_leg_layout == 'same as canvas':
            plot_leg_layout = canvas_leg_layout

        if plot_leg_layout == 'horizontal':
            col_count = len(signals)
        else:
            col_count = 1

        plot.addLegend(horSpacing=25, colCount=col_count)
        legend = plot.legend
        legend.layout.setContentsMargins(3, 0, 0, 0)

        # Set legend event
        legend.sigSampleClicked.connect(self.check_envelope_signal)

        # Set aspect legend
        set_legend_position(legend, plot_leg_position)
        legend.setBrush(pg.mkBrush(255, 255, 255, 120))
        legend.setPen(pg.mkPen(color='k'))

    def check_envelope_signal(self, item: PlotDataItem):
        ax_lines = self.map_legend_to_ax[item]
        if not isinstance(ax_lines, Collection):
            return

        for ax_line in ax_lines[1:]:
            ax_line.setVisible(not ax_line.isVisible())

    def _auto_adjust_legend_layout(self, plot: PlotItem, i_plot: Plot, signals):
        legend = plot.legend
        if legend is None:
            return

        layout = self._pm.get_value(i_plot, 'legend_layout')
        canvas_layout = self._pm.get_value(self.canvas, 'legend_layout')
        if layout == 'same as canvas':
            layout = canvas_layout

        if layout == 'horizontal':
            cols = range(len(signals), 0, -1)
        else:
            max_cols = min(4, len(signals))
            cols = range(1, max_cols + 1)

        vb_rect = plot.getViewBox().sceneBoundingRect()

        for ncol in cols:
            legend.setColumnCount(ncol)
            legend.updateSize()
            leg_rect = legend.sceneBoundingRect()
            if (leg_rect.left() >= vb_rect.left()
                    and leg_rect.right() <= vb_rect.right()
                    and leg_rect.top() >= vb_rect.top()
                    and leg_rect.bottom() <= vb_rect.bottom()):
                break

    def _update_slider(self, val, i_plot: PlotXYWithSlider, slider_values, current_label, formatter):
        for c_row in i_plot.signals.values():
            for c_signal in c_row:
                self.process_ipl_signal(c_signal)

        # Refresh current label value
        is_date = bool(min(slider_values) > (1 << 53) and max(slider_values) < (1 << 62))
        if is_date:
            current_value = pd.Timestamp(slider_values[int(val)]).value
            current_label.setText(formatter.date_fmt(current_value, formatter.cut_start + 3, formatter.NANOSECOND,
                                                     postfix_end=True))
        else:
            current_value = slider_values[int(val)]
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
        current_plot = view_box.parentItem()  # type: PlotItem
        if not self.canvas.streaming:
            super()._y_axis_update_callback(current_plot)

        for (r, c), stacks in self._layout_stacks.items():
            if current_plot in stacks.values():
                self.align_y_axis(c)
                break
        self.update_grid_spacing_label(current_plot)

    def _x_axis_update_callback(self, view_box: ViewBox):
        if self.canvas.streaming:
            return
        current_plot = view_box.parentItem()  # type: PlotItem
        super()._x_axis_update_callback(current_plot)
        self.update_grid_spacing_label(current_plot)

    def process_ipl_log_axis(self, axis_item: AxisItem, plot: Plot):
        if axis_item.orientation != 'left':
            return
        log_scale = self._pm.get_value(plot, 'log_scale')
        if log_scale:
            plot_item = axis_item.parentItem()
            plot_item.setLogMode(x=False, y=True)

    def process_ipl_axis_params(self, fc, fs, tick_number, axis: Axis, axis_item: AxisItem):
        tick_props = dict(maxTickLevel=0)
        show_all_ticks = self._pm.get_value(self.canvas, 'ticks_position')

        # Set ticks on the top and right axis
        if show_all_ticks:
            tick_props['tickLength'] = -4
        else:
            tick_props['tickLength'] = 4

        # Configure top and right axes ticks based on ticks_position
        if axis_item.orientation == 'left':
            plot_item = axis_item.parentItem()
            if plot_item:
                if show_all_ticks:
                    # Show ticks on top and right axes
                    plot_item.getAxis('top').setStyle(tickLength=-4, maxTickLevel=0)
                    plot_item.getAxis('right').setStyle(tickLength=-4, maxTickLevel=0)
                else:
                    # Hide ticks on top and right axes
                    plot_item.getAxis('top').setTicks([])
                    plot_item.getAxis('right').setTicks([])

        # Create font and metrics if font size is valid
        if fs and fs > 0:
            tick_font = QFont()
            tick_font.setPointSize(int(fs))
            font_metrics = QFontMetricsF(tick_font)
            tick_props['tickFont'] = tick_font
        else:
            font_metrics = None

        # Reduce vertical space between tick labels and axis edge
        if axis_item.orientation == 'bottom':
            tick_props['tickTextOffset'] = 1
            if font_metrics:
                tick_length = tick_props.get('tickLength', 4)
                h = int(font_metrics.height() + abs(tick_length) + 2)
            else:
                h = 16
            axis_item.setHeight(h)
            axis_item._base_height = h

        # Font size for UTC label
        if isinstance(axis_item, NanosecondDateFormatter):
            axis_item.common_label.setText(axis_item.offset_str, size=f'{fs}pt', color=fc)
            if font_metrics:
                axis_item.common_label.setMaximumHeight(int(font_metrics.height() + 2))
            else:
                axis_item.common_label.setMaximumHeight(14)

        axis_item.setStyle(**tick_props)

        # Set color to tick values
        axis_item.setTextPen(pg.mkPen(fc))

        # Set number of ticks and labels
        if isinstance(axis_item, NanosecondDateFormatter):
            axis_item.set_ticks_number(tick_number)

    def process_ipl_axis_params_label(self, axis_item: AxisItem, text, fc, fs):
        if text is None:
            return
        label_props = {}
        if fc:
            label_props['color'] = fc
        if fs and fs > 0:
            label_props['font-size'] = f'{int(fs)}pt'
        axis_item.setLabel(text, **label_props)

        if axis_item.orientation == 'bottom' and text:
            if fs and fs > 0:
                label_font = QFont()
                label_font.setPointSize(int(fs))
                label_height = QFontMetricsF(label_font).height()
            else:
                label_height = 12

            base_height = getattr(axis_item, '_base_height', None) or axis_item.height() or 16
            axis_item.setHeight(int(base_height + label_height + 2))

    def process_ipl_axis_formatter(self, impl_plot: PlotItem, impl_axis: NanosecondDateFormatter, ax_idx: int):
        ci = self._impl_plot_cache_table.get_cache_item(impl_plot)
        impl_axis.set_offset(ci.offsets[ax_idx])

    def process_ipl_signal_impl_plot(self, signal: Signal):
        plot = self._signal_impl_plot_lut.get(signal.uid)  # type: PlotItem
        if not isinstance(plot, PlotItem):
            logger.error(f"PlotItem not found for signal {signal}. Unexpected error. signal_id: {id(signal)}")
            return
        return plot

    def process_ipl_signal_annotations(self, signal: Signal, impl_plot: PlotItem):
        if not isinstance(signal, SignalXY):
            return

        if impl_plot.listDataItems() and impl_plot.listDataItems()[0].opts['symbol'] is None:
            return

        if signal.markers_list:
            annotations_names = [child.toPlainText() for child in impl_plot.items if isinstance(child, TextItem)]
            for marker in signal.markers_list:
                if marker.visible:
                    # Draw marker with correct offset to right display
                    x = self.transform_value(impl_plot, 0, marker.xy[0], inverse=True)
                    y = marker.xy[1]

                    # Create annotation if not present (import case)
                    if marker.name not in annotations_names:
                        marker_text = TextItem(anchor=(0.5, 0.5),
                                               html=f"""<div style="
                                               background-color:{marker.color};
                                               color:black;
                                               border:1px solid black;
                                               border-radius:4px;
                                               padding:2px 5px;
                                               font-size:12pt;
                                               text-align:center;
                                                ">{marker.name}</div>""")
                        marker_text.setPos(x, y)
                        impl_plot.addItem(marker_text)
                    else:
                        # Update position if annotation already exists
                        prev_annotation = [child for child in impl_plot.items if isinstance(child,
                                                                                            TextItem) and child.toPlainText() == marker.name]  # type: List[TextItem]
                        prev_annotation[0].setPos(x, y)

    def clear(self):
        """
        Set the canvas gridspec for the figure.
        """
        super().clear()

        # remove any active multi‑cursors
        for c in self._cursors:
            c.remove()
        self._cursors.clear()

        self._cell_gl = {}
        self._layout_stacks = {}
        self._slider_placeholders = {}

        # Remove all items from the layout and set the current row and column to 0
        # The clear() method is wrapped from the figure (GraphicsLayoutWidget) internal GraphicsLayout
        self.figure.clear()
        if self.canvas:
            for col in self.canvas.plots:
                for plot in col:
                    if not plot:
                        continue
                    for signal in [elem for sublist in plot.signals.values() for elem in sublist]:
                        signal.lines.clear()
                    if isinstance(plot, PlotXYWithSlider) or isinstance(plot, PlotContourWithSlider):
                        plot.clean_slider()

        self.map_legend_to_ax.clear()
        self._grid_spacing_labels.clear()
        self._impl_plot_ranges_hash.clear()
        self._slider_placeholders.clear()
        self._colorbar_lut.clear()

        gc.collect()

    @staticmethod
    def set_grid(plot: PlotItem, grid: bool = True):
        """
        Enable or disable the grid for the given plot.
        """
        plot.showGrid(x=grid, y=grid)

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

    def update_grid_spacing_label(self, plot: PlotItem):
        """Update or remove the grid spacing label for a plot."""
        ci = self._impl_plot_cache_table.get_cache_item(plot)
        if not ci:
            return
        i_plot = ci.plot()
        show = self._pm.get_value(i_plot, 'grid') and self._pm.get_value(i_plot, 'grid_spacing_label')

        if not show:
            if plot in self._grid_spacing_labels:
                plot.removeItem(self._grid_spacing_labels.pop(plot))
            return

        vb = plot.getViewBox()
        vr = vb.viewRange()
        x_axis = plot.getAxis('bottom')
        y_axis = plot.getAxis('left')
        is_date = getattr(x_axis, 'is_date', False)

        def _get_tick_spacing(axis, vr_min, vr_max):
            """Get the actual tick spacing from an axis."""
            try:
                geom = axis.geometry()
                size = geom.width() if axis.orientation in ('bottom', 'top') else geom.height()
                if size <= 0:
                    size = 800  # fallback for initial draw
                tick_levels = axis.tickValues(vr_min, vr_max, size)
                if tick_levels:
                    spacing, ticks = tick_levels[0]
                    if spacing > 0:
                        return spacing
                    if len(ticks) >= 2:
                        return abs(ticks[1] - ticks[0])
            except Exception:
                pass
            return 0

        x_spacing = _get_tick_spacing(x_axis, vr[0][0], vr[0][1])
        y_spacing = _get_tick_spacing(y_axis, vr[1][0], vr[1][1])

        # Correct for axis offset scaling (datetime axes may use offset == 100_000 as multiplier)
        if is_date:
            offset = getattr(x_axis, 'offset', 0)
            if offset == 100_000:
                x_spacing = x_spacing * offset

        x_label = self._format_spacing(x_spacing, is_date) if x_spacing > 0 else ""
        y_label = self._format_spacing(y_spacing, False) if y_spacing > 0 else ""

        text = f"X: {x_label}  Y: {y_label}" if x_label and y_label else x_label or y_label
        if not text:
            return

        fs = self._pm.get_value(i_plot, 'font_size') or 8

        if plot not in self._grid_spacing_labels:
            label = TextItem(text, color=(0, 0, 0), anchor=(1, 1))
            label.setZValue(100)
            label.setFlag(label.GraphicsItemFlag.ItemIsMovable, True)
            label._user_moved = False
            # Track if user moved it
            orig_release = label.mouseReleaseEvent
            def _on_release(ev, lbl=label, orig=orig_release):
                lbl._user_moved = True
                if orig:
                    orig(ev)
            label.mouseReleaseEvent = _on_release
            plot.addItem(label, ignoreBounds=True)
            self._grid_spacing_labels[plot] = label
        else:
            label = self._grid_spacing_labels[plot]
            label.setText(text)
        font = QFont()
        font.setPointSize(int(fs))
        label.setFont(font)

        # Position at bottom-right of the view (only if user hasn't moved it)
        if not getattr(label, '_user_moved', False):
            label.setPos(vr[0][1], vr[1][0])

    @staticmethod
    def set_mouse(plot: PlotItem):
        vb = plot.vb
        vb.setMouseEnabled(x=False, y=False)

    def set_view_box(self):
        if self._cursor_active:
            self.deactivate_cursor()
        for stack in self._layout_stacks.values():
            for plot in stack.values():
                if not plot:
                    continue
                vb = plot.vb
                vb.setMouseMode(vb.PanMode)
                self.set_mouse(plot)

    def set_view_box_zoom(self):
        if self._cursor_active:
            self.deactivate_cursor()
        for stack in self._layout_stacks.values():
            for plot in stack.values():
                if not plot:
                    continue
                iplot = self._impl_plot_cache_table.get_cache_item(plot).plot()
                if isinstance(iplot, (PlotContour, PlotContourWithSlider)):
                    logger.warning(f"Zoom action is not supported for {type(iplot).__name__}")
                    continue
                vb = plot.vb
                vb.setMouseMode(vb.RectMode)
                self.set_mouse(plot)

    def set_view_box_pan(self):
        if self._cursor_active:
            self.deactivate_cursor()
        for stack in self._layout_stacks.values():
            for plot in stack.values():
                if not plot:
                    continue
                iplot = self._impl_plot_cache_table.get_cache_item(plot).plot()
                if isinstance(iplot, (PlotContour, PlotContourWithSlider)):
                    logger.warning(f"Pan action is not supported for {type(iplot).__name__}")
                    continue
                vb = plot.vb
                vb.setMouseMode(vb.PanMode)
                vb.setMouseEnabled(x=True, y=True)

    def set_view_box_crosshair(self):
        if self._cursor_active:
            return
        for stack in self._layout_stacks.values():
            for plot in stack.values():
                if not plot:
                    continue
                vb = plot.vb
                vb.setMouseMode(vb.PanMode)
                self.set_mouse(plot)
        self.activate_cursor()
        self._cursor_active = True

    def get_impl_data(self, line: PlotDataItem):
        return line.getData()[0], line.getData()[1]

    def get_impl_lines(self, impl_plot: PlotItem):
        lines = impl_plot.listDataItems()
        vb = impl_plot.getViewBox()
        lo, hi = vb.viewRange()[0]
        return lines, lo, hi

    def autoscale_y_axis(self, impl_plot: PlotItem, padding=0.1):
        """
        This function rescales the y-axis based on the data that is visible given the current limits of the viewbox.
        impl_plot -- a PyQtGraph plot item
        padding -- the fraction of the total height of the y-data to pad the upper and lower ylims
        """
        bot, top = super().autoscale_y_axis(impl_plot)
        vb = impl_plot.getViewBox()

        # Set new Y axis limits
        vb.setYRange(bot, top, padding=padding)

    def set_impl_plot_slider_limits(self, plot: PlotXYWithSlider, start, end):
        """
            Apply slider limit changes to a PlotXYWithSlider instance (used in UNDO/REDO operations)
        """
        if plot.slider is None:
            return

        # Update internal and actual slider limits
        plot.slider_last_min = start
        plot.slider_last_max = end
        plot.slider.setMinimum(start)
        plot.slider.setMaximum(end)

        # Adjust the current slider value
        val = plot.slider.value()
        if val < start:
            val = start
        elif val > end:
            val = end

        plot.slider.setValue(val)

        # Update the annotations labels for the slider limits
        row, col = plot.row - 1, plot.col - 1
        annotations = self._slider_placeholders[(row, col)].widget().findChildren(QLabel)
        min_annotation, current_annotation, max_annotation = annotations[:3]

        slider_values = plot.signals[1][0].z_data
        is_date = bool(min(slider_values) > (1 << 53) and max(slider_values) < (1 << 62))
        if is_date:
            formatter = NanosecondDateFormatter(orientation='bottom')
            start_value = slider_values[start]
            current_value = slider_values[val]
            max_value = slider_values[end]

            min_annotation.setText(
                formatter.date_fmt(start_value, formatter.YEAR, formatter.NANOSECOND, postfix_end=True))
            current_annotation.setText(
                formatter.date_fmt(current_value, formatter.cut_start + 3, formatter.NANOSECOND, postfix_end=True))
            max_annotation.setText(
                formatter.date_fmt(max_value, formatter.cut_start + 3, formatter.NANOSECOND, postfix_end=True))
        else:
            min_annotation.setText(f'{slider_values[start]}')
            current_annotation.setText(f'{slider_values[val]}')
            max_annotation.setText(f'{slider_values[end]}')

    def update_slider_limits(self, plot: PlotXYWithSlider, begin, end):
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
        plot.slider_last_max = new_end
        plot.slider.setMinimum(new_start)
        plot.slider.setMaximum(new_end)
        plot.slider.setValue(val)

        # Update the annotations labels for the slider limits
        row, col = plot.row - 1, plot.col - 1
        annotations = self._slider_placeholders[(row, col)].widget().findChildren(QLabel)
        min_annotation, current_annotation, max_annotation = annotations[:3]

        slider_values = plot.signals[1][0].z_data
        is_date = bool(min(slider_values) > (1 << 53) and max(slider_values) < (1 << 62))
        if is_date:
            formatter = NanosecondDateFormatter(orientation='bottom')
            start_value = slider_values[new_start]
            current_value = slider_values[val]
            max_value = slider_values[new_end]

            min_annotation.setText(
                formatter.date_fmt(start_value, formatter.YEAR, formatter.NANOSECOND, postfix_end=True))
            current_annotation.setText(
                formatter.date_fmt(current_value, formatter.cut_start + 3, formatter.NANOSECOND, postfix_end=True))
            max_annotation.setText(
                formatter.date_fmt(max_value, formatter.cut_start + 3, formatter.NANOSECOND, postfix_end=True))
        else:
            min_annotation.setText(f'{slider_values[new_start]}')
            current_annotation.setText(f'{slider_values[val]}')
            max_annotation.setText(f'{slider_values[new_end]}')

    def enable_tight_layout(self):
        glw = self.figure
        glw.ci.layout.setContentsMargins(4, 4, 4, 4)
        glw.ci.layout.setSpacing(2)

    def disable_tight_layout(self):
        glw = self.figure
        glw.ci.layout.setContentsMargins(0, 0, 0, 0)
        glw.ci.layout.setSpacing(0)

    def set_canvas_gridspec(self, rows: int, cols: int):
        prev_shape = getattr(self, "_grid_shape", (0, 0))
        prev_offset = getattr(self, "_row_offset", 0)
        prev_rows, prev_cols = prev_shape

        self._grid_shape = (rows, cols)
        lay = self.figure.ci.layout

        has_title = self._pm.get_value(self.canvas, 'title') is not None
        new_offset = 1 if has_title else 0
        self._row_offset = new_offset

        prev_total_rows = prev_rows + prev_offset
        new_total_rows = rows + new_offset

        reset_rows = max(lay.rowCount(), prev_total_rows, new_total_rows)
        reset_cols = max(lay.columnCount(), prev_cols, cols)

        for r in range(reset_rows):
            lay.setRowStretchFactor(r, 0)
        for c in range(reset_cols):
            lay.setColumnStretchFactor(c, 0)

        if has_title:
            lay.setRowStretchFactor(0, 0)

        for r in range(rows):
            lay.setRowStretchFactor(r + new_offset, 1)
        for c in range(cols):
            lay.setColumnStretchFactor(c, 1)

    def set_focus_plot(self, impl_plot: PlotItem):
        un_focus = self._focus_plot is not None or impl_plot is None
        all_stack = self._pm.get_value(self.canvas, "full_mode_all_stack")
        if un_focus:
            self._focus_plot = None
            self._focus_plot_stack_key = None
            row, col, stack_id = None, None, None
        else:
            ci = self._impl_plot_cache_table.get_cache_item(impl_plot)
            plot = ci.plot()
            self._focus_plot = plot
            self._focus_plot_stack_key = ci.stack_key
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
        if self._cursor_active:
            return

        plots: List[PlotItem] = []
        for stack in self._layout_stacks.values():
            for plot in stack.values():
                if plot:
                    plots.append(plot)
        if not plots:
            return

        x_label = self._pm.get_value(self.canvas, 'enable_x_label_crosshair')
        y_label = self._pm.get_value(self.canvas, 'enable_y_label_crosshair')
        val_label = self._pm.get_value(self.canvas, 'enable_val_label_crosshair')
        color = self._pm.get_value(self.canvas, 'crosshair_color')
        lw = getattr(self.canvas, 'crosshair_line_width', 1)
        horiz_on = bool(getattr(self.canvas, 'crosshair_horizontal', False))
        vert_on = bool(getattr(self.canvas, 'crosshair_vertical', True))

        font_size = int(self._pm.get_value(self.canvas, 'font_size') or 8)

        if getattr(self.canvas, 'crosshair_per_plot', False):
            for p in plots:
                cursor = pyQtCrosshair(
                    plots=[p],
                    x_label=x_label,
                    y_label=y_label,
                    val_label=val_label,
                    color=color,
                    lw=lw,
                    horiz_on=horiz_on,
                    vert_on=vert_on,
                    val_tolerance=0.05,
                    font_size=font_size,
                    cache_table=self._impl_plot_cache_table,
                )
                self._cursors.append(cursor)
        else:
            cursor = pyQtCrosshair(
                plots=plots,
                x_label=x_label,
                y_label=y_label,
                val_label=val_label,
                color=color,
                lw=lw,
                horiz_on=horiz_on,
                vert_on=vert_on,
                val_tolerance=0.05,
                font_size=font_size,
                cache_table=self._impl_plot_cache_table,
            )
            self._cursors.append(cursor)

        self._cursor_active = True

    @BackendParserBase.run_in_one_thread
    def deactivate_cursor(self):
        if not self._cursor_active:
            return

        for cursor in self._cursors:
            cursor.remove()

        self._cursors.clear()
        self._cursor_active = False

    def get_impl_x_axis(self, plot: PlotItem) -> AxisItem:
        return plot.getAxis('bottom')

    def get_impl_x_axis_limits(self, plot: PlotItem) -> Tuple[float, float]:
        return plot.getViewBox().viewRange()[0]

    def get_impl_y_axis(self, plot: PlotItem) -> AxisItem:
        return plot.getAxis('left')

    def get_impl_y_axis_limits(self, plot: PlotItem) -> AxisItem:
        return plot.getViewBox().viewRange()[1]

    def set_impl_x_axis_label_text(self, plot: PlotItem, text: str):
        ci = self._impl_plot_cache_table.get_cache_item(plot)
        i_plot = ci.plot() if ci else None
        # Get the X axis to retrieve its font properties
        x_axis = i_plot.axes[0] if i_plot and len(i_plot.axes) > 0 else None
        fc = self._pm.get_value(x_axis, 'font_color') if x_axis else self._pm.get_value(i_plot,
                                                                                        'font_color') if i_plot else None
        fs = self._pm.get_value(x_axis, 'font_size') if x_axis else self._pm.get_value(i_plot,
                                                                                       'font_size') if i_plot else None
        self.process_ipl_axis_params_label(self.get_impl_x_axis(plot), text, fc, fs)

    def set_impl_x_axis_limits(self, plot: PlotItem, limits: tuple):
        if isinstance(plot, PlotItem):
            vb = plot.getViewBox()
            vb.setXRange(limits[0], limits[1], padding=0)

    def set_impl_y_axis_label_text(self, plot: PlotItem, text: str):
        ci = self._impl_plot_cache_table.get_cache_item(plot)
        i_plot = ci.plot() if ci else None
        # Get the Y axis to retrieve its font properties
        y_axis = None
        if i_plot and len(i_plot.axes) > 1:
            stacked_plots = self._plot_impl_plot_lut.get(id(i_plot), [])
            pos = stacked_plots.index(plot) if plot in stacked_plots else 0
            y_axis = i_plot.axes[1][pos] if isinstance(i_plot.axes[1], Collection) else i_plot.axes[1]
        fc = self._pm.get_value(y_axis, 'font_color') if y_axis else self._pm.get_value(i_plot,
                                                                                        'font_color') if i_plot else None
        fs = self._pm.get_value(y_axis, 'font_size') if y_axis else self._pm.get_value(i_plot,
                                                                                       'font_size') if i_plot else None
        self.process_ipl_axis_params_label(self.get_impl_y_axis(plot), text, fc, fs)

    def set_impl_y_axis_limits(self, plot: PlotItem, limits: tuple):
        if isinstance(plot, PlotItem):
            vb = plot.getViewBox()
            vb.setYRange(limits[0], limits[1], padding=0)

    def align_y_axis(self, col: int) -> None:
        """
        Synchronizes the Y-axis width across all plots in a column.
        """
        # Collect all plots from the specified column
        column_plots = [
            p for (r, c), stack_dict in self._layout_stacks.items()
            if c == col
            for p in stack_dict.values()
            if p
        ]

        if not column_plots:
            return

        # Reset widths to allow PyQtGraph to recalculate
        for p in column_plots:
            p.getAxis('left').setWidth(None)

        # Calculate maximum required width based on current tick labels
        max_w = 0.0
        for p in column_plots:
            ax = p.getAxis('left')
            vb = p.getViewBox()
            y0, y1 = vb.viewRange()[1]

            tv = ax.tickValues(y0, y1, vb.height()) if vb.height() != 0.0 else None
            if not tv:
                max_w = max(max_w, ax.width())
                continue

            spacing, values = tv[0]
            labels = ax.tickStrings(values, scale=1.0, spacing=spacing)

            # Measure tick label text width
            fm = QFontMetricsF(ax.style.get('tickFont') or QtWidgets.QApplication.font())
            text_w = max((fm.horizontalAdvance(str(s)) for s in labels), default=0.0)

            # Add axis label width if visible
            label_w = ax.label.boundingRect().height() if ax.label.isVisible() else 0.0

            # Update maximum (including margin for ticks and padding)
            max_w = max(max_w, text_w + label_w + 15)

        if max_w <= 0:
            return

        # Apply maximum width to all axes in column
        w = int(max_w)
        for p in column_plots:
            p.getAxis('left').setWidth(w)

    def transform_value(self, impl_plot: Any, ax_idx: int, value: Any, inverse=False):
        """Adds or subtracts axis offset from value trying to preserve type of offset (ex: does not convert to
        float when offset is int)"""
        return self._impl_plot_cache_table.transform_value(impl_plot, ax_idx, value, inverse=inverse)
