"""Frozen crosshair (Ruler) anchored to a single PyQtGraph plot."""

from typing import Tuple, Union

import pyqtgraph as pg
from pyqtgraph import InfiniteLine, PlotItem, TextItem
from pyqtgraph.Qt import QtCore, QtGui
from PySide6.QtCore import QPointF

from iplotlib.impl.pyqtgraph.dateFormatter import NanosecondDateFormatter


class pyQtRuler:
    """A frozen vertical + horizontal line pair anchored at (x, y) of a plot."""

    def __init__(self,
                 plot: PlotItem,
                 name: str,
                 xy: Tuple[float, float],
                 color: Union[str, Tuple[int, int, int]] = "#FFFFFF",
                 lw: int = 1,
                 font_size: int = 8):
        self.plot = plot
        self.name = name
        self.xy = xy
        # Absolute (offset-free) X and Y; re-projected to the plot offsets on each
        # refresh so zoom/pan keep the ruler anchored to its data position.
        self.abs_x = xy[0]
        self.abs_y = xy[1]
        self.is_echo = False
        self.color = color
        self.visible = True

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

        text_fg = "white"
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

        self.refresh_labels()

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
        self.name_label.setPos(x, y if in_y else ymin)
        self.v_line.setVisible(self.visible and in_x)
        self.x_label.setVisible(self.visible and in_x)
        self.h_line.setVisible(self.visible and in_x and in_y)
        self.y_label.setVisible(self.visible and in_x and in_y)
        self.name_label.setVisible(self.visible and in_x)

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

    def set_visible(self, visible: bool):
        self.visible = visible
        self.v_line.setVisible(visible)
        self.h_line.setVisible(visible)
        self.x_label.setVisible(visible)
        self.y_label.setVisible(visible)
        self.name_label.setVisible(visible)
        if visible:
            self.refresh_labels()

    def remove(self):
        items = [self.v_line, self.h_line, self.name_label, self.x_label, self.y_label]
        for item in items:
            sc = item.scene()
            if sc is not None:
                item.setVisible(False)
                sc.removeItem(item)
            item.setParentItem(None)
