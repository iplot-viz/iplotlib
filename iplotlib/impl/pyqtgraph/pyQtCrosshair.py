from typing import List, Optional, Tuple, Union
import numpy as np
import pyqtgraph as pg
from pyqtgraph import PlotItem, InfiniteLine, TextItem, PlotDataItem
from pyqtgraph.Qt import QtCore, QtGui
from iplotlib.core.impl_base import ImplementationPlotCacheTable
from iplotlib.impl.pyqtgraph.dateFormatter import NanosecondDateFormatter


class pyQtCrosshair:
    def __init__(self,
                 plots: List[PlotItem],
                 *,
                 x_label: bool = True,
                 y_label: bool = True,
                 val_label: bool = True,
                 horiz_on: bool = False,
                 vert_on: bool = True,
                 val_tolerance: float = 0.05,
                 text_color: str = "white",
                 font_size: int = 8,
                 cache_table: ImplementationPlotCacheTable = None,
                 color: Union[str, Tuple[int, int, int]] = "r",
                 lw: int = 1,
                 **kwargs):

        self.plots = plots
        self.horiz_on = horiz_on
        self.vert_on = vert_on
        self.x_label = x_label
        self.y_label = y_label
        self.value_label = val_label
        self._cache_table = cache_table
        self.val_tolerance = val_tolerance
        self._connected = False
        self._scene = None
        self._is_active = True

        self.v_lines: List[InfiniteLine] = []
        self.h_lines: List[InfiniteLine] = []
        self.x_arrows: List[TextItem] = []
        self.y_arrows: List[TextItem] = []
        self.value_annotations: List[TextItem] = []

        self._last_x = None
        self._text_cache = {}

        pen = pg.mkPen(color=color, width=lw, cosmetic=True)
        font = QtGui.QFont()
        font.setPointSize(font_size)
        font.setBold(True)

        for ax in self.plots:
            vb = ax.getViewBox()
            if vert_on:
                line = InfiniteLine(angle=90, movable=False, pen=pen)
                line.setZValue(2000)
                vb.addItem(line, ignoreBounds=True)
                self.v_lines.append(line)
            if horiz_on:
                line = InfiniteLine(angle=0, movable=False, pen=pen)
                line.setZValue(2000)
                vb.addItem(line, ignoreBounds=True)
                self.h_lines.append(line)
            if x_label:
                arrow = TextItem(anchor=(0.5, 1.0), color=text_color, border=color, fill=color)
                arrow.textItem.setFont(font)
                arrow.setZValue(2000)
                vb.addItem(arrow, ignoreBounds=True)
                self.x_arrows.append(arrow)
            if y_label:
                arrow = TextItem(anchor=(0.0, 0.5), color=text_color, border=color, fill=color)
                arrow.textItem.setFont(font)
                arrow.setZValue(2000)
                vb.addItem(arrow, ignoreBounds=True)
                self.y_arrows.append(arrow)
            if val_label and self._cache_table:
                self._create_value_annotations(ax, vb, font)

        self.clear(None)

        if self.plots:
            self._scene = self.plots[0].scene()
            if self._scene:
                self._scene.sigMouseMoved.connect(self.on_move)
                self._connected = True

    def _create_value_annotations(self, plot_item: PlotItem, view_box: pg.ViewBox, font: QtGui.QFont):
        ci = self._cache_table.get_cache_item(plot_item)
        if hasattr(ci, "signals") and ci.signals:
            from iplotlib.core import SignalContour
            for sig_ref in ci.signals:
                signal = sig_ref()
                if not signal or isinstance(signal, SignalContour): continue
                for line in getattr(signal, 'lines', []):
                    line_item = line[0] if isinstance(line, list) else line
                    if isinstance(line_item, PlotDataItem):
                        annotation = TextItem(anchor=(0.0, 1.0), color="white", border="green", fill="green")
                        annotation.textItem.setFont(font)
                        annotation.setZValue(2000)
                        annotation.line = line_item
                        annotation.viewbox = view_box
                        view_box.addItem(annotation, ignoreBounds=True)
                        self.value_annotations.append(annotation)

    def on_move(self, pos):
        if not self._is_active: return

        active_plot = None
        mouse_point = None
        for plot in self.plots:
            if plot.scene() and plot.sceneBoundingRect().contains(pos):
                active_plot = plot
                mouse_point = plot.getViewBox().mapSceneToView(pos)
                break

        if not active_plot:
            if self._last_x is not None:
                self.clear(None)
                self._last_x = None
            return

        x, y = mouse_point.x(), mouse_point.y()

        if self._last_x is not None and abs(x - self._last_x) < 1e-9:
            return
        self._last_x = x

        for line in self.v_lines: line.setPos(x); line.setVisible(True)
        for line in self.h_lines: line.setPos(y); line.setVisible(True)

        for i, plot in enumerate(self.plots):
            if not plot.scene(): continue
            vb = plot.getViewBox()
            [[xmin, xmax], [ymin, ymax]] = vb.viewRange()

            if self.x_label and i < len(self.x_arrows):
                arrow = self.x_arrows[i]
                if xmin < x < xmax:
                    axis = plot.getAxis("bottom")
                    text_key = f"x{i}"
                    current_text = self._text_cache.get(text_key)
                    new_text = (axis.tickStrings([x], 1.0, 1)[0]
                                if isinstance(axis, NanosecondDateFormatter) and axis.tickStrings([x], 1.0, 1)
                                else f"{x:.6g}")
                    if current_text != new_text:
                        arrow.setText(new_text)
                        self._text_cache[text_key] = new_text
                    arrow.setPos(x, ymin);
                    arrow.setVisible(True)
                else:
                    arrow.setVisible(False)

            if self.y_label and i < len(self.y_arrows):
                arrow = self.y_arrows[i]
                if ymin < y < ymax:
                    text_key = f"y{i}"
                    current_text = self._text_cache.get(text_key)
                    new_text = f"{y:.6g}"
                    if current_text != new_text:
                        arrow.setText(new_text)
                        self._text_cache[text_key] = new_text
                    arrow.setPos(xmin, y);
                    arrow.setVisible(True)
                else:
                    arrow.setVisible(False)

        if self.value_label:
            for annotation in self.value_annotations:
                if not annotation.scene(): continue
                line = annotation.line
                x_data, y_data = line.getData()
                if x_data is None or len(x_data) == 0:
                    annotation.setVisible(False);
                    continue

                idx = np.searchsorted(x_data, x, side="left")
                if 0 < idx < len(x_data) and abs(x - x_data[idx - 1]) < abs(x - x_data[idx]):
                    idx -= 1
                idx = min(idx, len(x_data) - 1)

                vb = annotation.viewbox
                [[xmin, xmax], _] = vb.viewRange()
                if abs(x - x_data[idx]) < (xmax - xmin) * self.val_tolerance:
                    annotation.setPos(x_data[idx], y_data[idx])
                    annotation.setText(f"{y_data[idx]:.6g}")
                    annotation.setVisible(True)
                else:
                    annotation.setVisible(False)

    def clear(self, event):
        all_items = self.v_lines + self.h_lines + self.x_arrows + self.y_arrows + self.value_annotations
        for item in all_items:
            if item.scene():
                item.setVisible(False)
        self._text_cache.clear()

    def remove(self):
        self._is_active = False
        self.disconnect()
        self.v_lines.clear()
        self.h_lines.clear()
        self.x_arrows.clear()
        self.y_arrows.clear()
        self.value_annotations.clear()

    def disconnect(self):
        if self._connected and self._scene:
            try:
                self._scene.sigMouseMoved.disconnect(self.on_move)
            except (TypeError, RuntimeError):
                pass
        self._connected = False
        self._scene = None