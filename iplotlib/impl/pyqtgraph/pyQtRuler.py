"""Frozen crosshair (Ruler) anchored to a single PyQtGraph plot."""

from typing import List, Tuple, Union

import numpy as np
import pyqtgraph as pg
from pyqtgraph import InfiniteLine, PlotItem, TextItem
from pyqtgraph.Qt import QtCore, QtGui
from PySide6.QtCore import QPointF

from iplotlib.core.ruler import contrast_text_color
from iplotlib.impl.pyqtgraph.dateFormatter import NanosecondDateFormatter


class pyQtRuler:
    """A frozen vertical + horizontal line pair anchored at (x, y) of a plot."""

    # Same tolerance as the crosshair: a signal value label only shows when the
    # nearest sample is within this fraction of the visible X range.
    VAL_TOLERANCE = 0.05

    def __init__(self,
                 plot: PlotItem,
                 name: str,
                 xy: Tuple[float, float],
                 color: Union[str, Tuple[int, int, int]] = "#FFFFFF",
                 font_color: str = "#FFFFFF",
                 lw: int = 1,
                 font_size: int = 8,
                 value_lines: List = None):
        self.plot = plot
        self.name = name
        self.xy = xy
        # Absolute (offset-free) X and Y; re-projected to the plot offsets on each
        # refresh so zoom/pan keep the ruler anchored to its data position.
        self.abs_x = xy[0]
        self.abs_y = xy[1]
        self.is_echo = False
        self.color = color
        self.font_color = font_color
        self.visible = True
        self.show_label = True
        self.show_val_label = True

        pen = pg.mkPen(color=color, width=lw, style=QtCore.Qt.PenStyle.DashLine, cosmetic=True)
        font = QtGui.QFont()
        font.setPointSize(font_size)
        font.setBold(True)

        vb = plot.getViewBox()

        self.v_line = InfiniteLine(angle=90, movable=False, pen=pen, pos=xy[0])
        self.v_line.setZValue(2000)
        vb.addItem(self.v_line, ignoreBounds=True)

        self.h_line = InfiniteLine(angle=0, movable=False, pen=pen, pos=xy[1])
        self.h_line.setZValue(2000)
        vb.addItem(self.h_line, ignoreBounds=True)

        text_fg = font_color
        axis_b = plot.getAxis("bottom")
        self.x_label = TextItem(anchor=(0.5, 0.0), color=text_fg, border=color, fill=color)
        self.x_label.textItem.setFont(font)
        self.x_label.setZValue(2000)
        self.x_label.setParentItem(axis_b)

        axis_l = plot.getAxis("left")
        self.y_label = TextItem(anchor=(1.0, 0.5), color=text_fg, border=color, fill=color)
        self.y_label.textItem.setFont(font)
        self.y_label.setZValue(2000)
        self.y_label.setParentItem(axis_l)

        self.name_label = TextItem(anchor=(0.0, 1.0), color=text_fg, border=color, fill=color)
        self.name_label.textItem.setFont(font)
        self.name_label.setZValue(2000)
        self.name_label.setText(name)
        vb.addItem(self.name_label, ignoreBounds=True)
        self.name_label.setPos(xy[0], xy[1])

        # One value label per signal line, styled like the crosshair's.
        self.value_labels = []
        for line_item in value_lines or []:
            label = TextItem(anchor=(0.0, 1.0), color=text_fg, border="green", fill="green")
            label.textItem.setFont(font)
            label.setZValue(2000)
            label.line = line_item
            vb.addItem(label, ignoreBounds=True)
            self.value_labels.append(label)

        self._apply_text_colors()
        self.refresh_labels()

    def _text_color_for(self, background) -> str:
        """Label text colour: an explicit (non-default) font colour wins;
        otherwise auto-contrast with the label background so light rulers stay
        legible."""
        if self.font_color and pg.mkColor(self.font_color).name().upper() != "#FFFFFF":
            return self.font_color
        c = pg.mkColor(background)
        return contrast_text_color((c.red(), c.green(), c.blue()))

    def _apply_text_colors(self):
        # Name/X/Y sit on the ruler colour; value tags sit on green.
        name_xy = self._text_color_for(self.color)
        for label in (self.x_label, self.y_label, self.name_label):
            label.setColor(name_xy)
        value = self._text_color_for("green")
        for label in self.value_labels:
            label.setColor(value)

    def refresh_labels(self):
        plot = self.plot
        vb = plot.getViewBox()
        [[xmin, xmax], [ymin, ymax]] = vb.viewRange()
        x, y = self.xy
        self.v_line.setPos(x)
        self.h_line.setPos(y)

        axis_b = plot.getAxis("bottom")
        if isinstance(axis_b, NanosecondDateFormatter):
            if getattr(axis_b, '_numeric_offset', 0) != 0:
                x_text = f"{x * axis_b.autoSIPrefixScale:g}"
            else:
                ts = axis_b.tickStrings([x], 1.0, getattr(axis_b, '_tick_spacing', 1))
                x_text = ts[0]
        else:
            x_text = f"{x:.6g}"
        self.x_label.setText(x_text)

        vr = vb.sceneBoundingRect()
        x_scene = vb.mapViewToScene(QPointF(x, ymin)).x()
        y_scene = vr.bottom()
        self.x_label.setPos(axis_b.mapFromScene(QPointF(x_scene, y_scene)))

        axis_l = plot.getAxis("left")
        self.y_label.setText(f"{y:.6g}")
        y_scene = vb.mapViewToScene(QPointF(xmin, y)).y()
        x_scene = vr.left()
        self.y_label.setPos(axis_l.mapFromScene(QPointF(x_scene, y_scene)))

        # X shows whenever it is in the time window; the horizontal line and Y
        # value only when y is in range. The name sits at the X·Y intersection, or
        # drops to the bottom when y is out of range. Honour a hidden ruler.
        # Inclusive bounds match the matplotlib backend (iplotMplRuler); bool()
        # because view range / xy may be numpy and setVisible rejects numpy.bool.
        in_x = bool(xmin <= x <= xmax)
        in_y = bool(ymin <= y <= ymax)
        # Place the name on the opposite side of the vertical line from the value
        # label (which hangs toward the side with more room) so they never overlap.
        name_anchor_x = 1.0 if (x - xmin) < (xmax - x) else 0.0
        self.name_label.setAnchor((name_anchor_x, 1.0))
        self.name_label.setPos(x, y if in_y else ymin)
        self.v_line.setVisible(self.visible and in_x)
        self.x_label.setVisible(self.visible and in_x)
        self.h_line.setVisible(self.visible and in_x and in_y)
        self.y_label.setVisible(self.visible and in_x and in_y)
        self.name_label.setVisible(self.visible and in_x and self.show_label)
        self._refresh_value_labels(in_x, xmin, xmax, ymin, ymax)

    def _refresh_value_labels(self, in_x, xmin, xmax, ymin, ymax):
        """Pin each signal's value label to the sample nearest to the ruler X,
        following the crosshair behaviour (tolerance, clamped to the view)."""
        x = self.xy[0]
        for label in self.value_labels:
            shown = False
            if self.visible and self.show_val_label and in_x and label.scene() is not None:
                x_data, y_data = label.line.getData()
                if x_data is not None and len(x_data) > 0:
                    idx = np.searchsorted(x_data, x, side="left")
                    if 0 < idx < len(x_data) and abs(x - x_data[idx - 1]) < abs(x - x_data[idx]):
                        idx -= 1
                    idx = min(idx, len(x_data) - 1)
                    if abs(x - x_data[idx]) < (xmax - xmin) * self.VAL_TOLERANCE:
                        xp = min(max(x_data[idx], xmin), xmax)
                        yp = min(max(y_data[idx], ymin), ymax)
                        anchor_x = 0.0 if (xp - xmin) < (xmax - xp) else 1.0
                        if getattr(label, "_last_anchor", None) != (anchor_x, 0.5):
                            label.setAnchor((anchor_x, 0.5))
                            label._last_anchor = (anchor_x, 0.5)
                        label.setPos(float(xp), float(yp))
                        label.setText(f"{y_data[idx]:.6g}")
                        shown = True
            label.setVisible(shown)

    def set_label_text(self, text: str):
        self.name_label.setText(text)

    def set_color(self, color):
        self.color = color
        pen = self.v_line.pen
        pen.setColor(pg.mkColor(color))
        self.v_line.setPen(pen)
        self.h_line.setPen(pen)
        for label in (self.x_label, self.y_label, self.name_label):
            label.fill = pg.mkBrush(color)
            label.border = pg.mkPen(color)
            label.update()
        # A new background may flip the auto-contrast text colour.
        self._apply_text_colors()

    def set_font_color(self, color: str):
        self.font_color = color
        self._apply_text_colors()

    def set_show_label(self, show: bool):
        self.show_label = show
        if self.visible:
            self.refresh_labels()

    def set_show_val_label(self, show: bool):
        self.show_val_label = show
        if self.visible:
            self.refresh_labels()

    def set_visible(self, visible: bool):
        self.visible = visible
        self.v_line.setVisible(visible)
        self.h_line.setVisible(visible)
        self.x_label.setVisible(visible)
        self.y_label.setVisible(visible)
        self.name_label.setVisible(visible)
        for label in self.value_labels:
            label.setVisible(visible)
        if visible:
            self.refresh_labels()

    def remove(self):
        items = [self.v_line, self.h_line, self.name_label, self.x_label, self.y_label,
                 *self.value_labels]
        for item in items:
            sc = item.scene()
            if sc is not None:
                item.setVisible(False)
                sc.removeItem(item)
            item.setParentItem(None)
