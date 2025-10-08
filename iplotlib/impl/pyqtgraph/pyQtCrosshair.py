from typing import Sequence, List, Optional, Tuple, Union, Dict
import math
import pyqtgraph as pg
from pyqtgraph import PlotItem, PlotDataItem, InfiniteLine, TextItem
from pyqtgraph.Qt import QtCore


class pyQtCrosshair:
    """
    Matplotlib-like multi-cursor for PyQtGraph.

    Visual:
      - Red badges at X (bottom axis) and Y (left axis).
      - Green marker + badge at the intersection with VAL only.
      - Vertical line shared across plots; horizontal per-plot.

    Behavior:
      - Uses original data (xData/yData) when present.
      - VAL snaps to nearest X with tolerance (percent of visible X-span).
    """

    def __init__(
            self,
            plots: Sequence[PlotItem],
            *,
            x_label: bool = True,
            y_label: bool = True,
            val_label: bool = True,
            color: Union[str, Tuple[int, int, int]] = "r",
            lw: int = 1,
            horiz_on: bool = False,
            vert_on: bool = True,
            val_tolerance: float = 0.05,
            cache_table=None,
            text_color: str = "white",
            font_size: int = 8,
    ):
        # Config
        self.plots: List[PlotItem] = list(plots) if isinstance(plots, (list, tuple)) else [plots]
        self.horiz_on = bool(horiz_on)
        self.vert_on = bool(vert_on)
        self.x_label = bool(x_label)
        self.y_label = bool(y_label)
        self.value_label = bool(val_label)
        self.text_color = text_color
        self.font_size = int(font_size)
        self._cache_table = cache_table
        self.val_tolerance = float(val_tolerance)

        # Graphics containers
        pen = pg.mkPen(color=color, width=lw)
        self.v_lines: Dict[PlotItem, Optional[InfiniteLine]] = {}
        self.h_lines: Dict[PlotItem, Optional[InfiniteLine]] = {}
        self.x_badges: Dict[PlotItem, TextItem] = {}
        self.y_badges: Dict[PlotItem, TextItem] = {}
        self.corner: Dict[PlotItem, pg.ScatterPlotItem] = {}
        self.val_badges: Dict[PlotItem, TextItem] = {}

        # Create per-plot graphics
        for p in self.plots:
            vb = p.getViewBox()

            # Vertical line
            if self.vert_on:
                v = InfiniteLine(angle=90, movable=False, pen=pen)
                v.setZValue(1_000_000)
                v.setVisible(False)
                vb.addItem(v, ignoreBounds=True)
                self.v_lines[p] = v
            else:
                self.v_lines[p] = None

            # Horizontal line
            if self.horiz_on:
                h = InfiniteLine(angle=0, movable=False, pen=pen)
                h.setZValue(1_000_000)
                h.setVisible(False)
                vb.addItem(h, ignoreBounds=True)
                self.h_lines[p] = h
            else:
                self.h_lines[p] = None

            # X badge (red)
            xb = TextItem(anchor=(0.5, 1.0))
            xb.setZValue(1_000_000)
            xb.setHtml(
                "<div style='background:#c62828;color:#fff; padding:2px 6px;border-radius:2px;font-weight:600;'></div>")
            vb.addItem(xb, ignoreBounds=True)  # add into ViewBox, no bounds contribution
            xb.setVisible(False)
            self.x_badges[p] = xb

            # Y badge (red)
            yb = TextItem(anchor=(0.0, 0.5))
            yb.setZValue(1_000_000)
            yb.setHtml(
                "<div style='background:#c62828;color:#fff; padding:2px 6px;border-radius:2px;font-weight:600;'></div>")
            vb.addItem(yb, ignoreBounds=True)  # add into ViewBox, no bounds contribution
            yb.setVisible(False)
            self.y_badges[p] = yb

            # Corner marker (green)
            cr = pg.ScatterPlotItem(pen=None, brush=pg.mkBrush(46, 125, 50), size=7, symbol="s")
            cr.setZValue(1_000_000)
            vb.addItem(cr, ignoreBounds=True)  # add into ViewBox, no bounds contribution
            cr.setVisible(False)
            self.corner[p] = cr

            # Green VAL badge
            gb = TextItem(anchor=(0.0, 1.0))
            gb.setZValue(1_000_000)
            gb.setHtml(
                "<div style='background:#2e7d32;color:#fff; padding:2px 6px;border-radius:2px;font-weight:600;'></div>")
            vb.addItem(gb, ignoreBounds=True)  # add into ViewBox, no bounds contribution
            gb.setVisible(False)
            self.val_badges[p] = gb

        # Event connection
        scene = self.plots[0].scene()
        self._proxy = pg.SignalProxy(scene.sigMouseMoved, rateLimit=60, slot=self.on_move)
        self._scene = scene

        # Blit-like placeholders
        self.use_blit = False
        self.background = None
        self.need_clear = False

    def clear(self, event=None, *, destroy: bool = False):
        # hide
        buckets = (self.v_lines, self.h_lines, self.x_badges, self.y_badges, self.corner, self.val_badges)
        for d in buckets:
            for o in d.values():
                if o:
                    try:
                        o.setVisible(False)
                    except Exception:
                        pass

        if not destroy:
            return

        # disconnect events
        if self._proxy and self._scene:
            try:
                self._scene.sigMouseMoved.disconnect(self._proxy)
            except Exception:
                pass
        self._proxy = None
        self._scene = None

        # no-show
        for p in list(self.plots):
            vb = p.getViewBox() if hasattr(p, "getViewBox") else None
            for o in (self.v_lines.get(p), self.h_lines.get(p)):
                if vb and o:
                    try:
                        vb.removeItem(o)
                    except Exception:
                        pass
            for o in (self.x_badges.get(p), self.y_badges.get(p), self.corner.get(p), self.val_badges.get(p)):
                if o:
                    try:
                        p.removeItem(o)
                    except Exception:
                        pass

        # clean refs
        for d in buckets: d.clear()
        self.plots.clear()

    def on_move(self, evt):
        """Mouse move handler (scene coords)."""
        pos: QtCore.QPointF = evt[0]

        # Pick shared X from first plot under cursor
        shared_x = None
        hit_plot = None
        for p in self.plots:
            if p.sceneBoundingRect().contains(pos):
                mp = p.getViewBox().mapSceneToView(pos)
                shared_x = mp.x()
                hit_plot = p
                break

        if shared_x is None:
            self.clear(None)
            return

        # Update per plot
        for p in self.plots:
            vb = p.getViewBox()
            vr = vb.viewRect()

            v = self.v_lines.get(p)
            h = self.h_lines.get(p)
            xb = self.x_badges[p]
            yb = self.y_badges[p]
            cr = self.corner[p]
            gb = self.val_badges[p]

            # Draw only if shared_x in visible X-range
            in_x = (vr.left() <= shared_x <= vr.right())
            if not in_x:
                if v is not None:
                    v.setVisible(False)
                if h is not None:
                    h.setVisible(False)
                xb.setVisible(False)
                yb.setVisible(False)
                cr.setVisible(False)
                gb.setVisible(False)
                continue

            # Vertical line (shared X)
            if v is not None:
                v.setPos(shared_x)
                v.setVisible(True)
                vb.disableAutoRange()

            # Mouse-Y for active plot; VAL snap (nearest) for all
            if p is hit_plot:
                mp = vb.mapSceneToView(pos)
                y_mouse = mp.y()
                val, x_snap, dx = self._snap_value_for_plot(p, shared_x)
            else:
                val, x_snap, dx = self._snap_value_for_plot(p, shared_x)
                y_mouse = None

            # Horizontal line (mouse Y on active; otherwise VAL)
            y_for_line = y_mouse if y_mouse is not None else (val if isinstance(val, (int, float)) else None)
            if h is not None and y_for_line is not None:
                h.setPos(float(y_for_line))
                h.setVisible(True)
                vb.disableAutoRange()
            elif h is not None:
                h.setVisible(False)

            # X badge (red) at bottom axis
            if self.x_label and y_for_line is not None:
                y_axis_baseline = min(vr.top(), vr.bottom())
                xb.setHtml(
                    "<div style='background:#c62828;color:#fff;"
                    "padding:2px 6px;border-radius:2px;font-weight:600;'>"
                    f"{shared_x:.6g}</div>"
                )
                xb.setAnchor(pg.Point(0.5, 1.0))
                xb.setPos(shared_x, y_axis_baseline)
                xb.setVisible(True)
            else:
                xb.setVisible(False)

            # Y badge (red) at left axis with inward px offset
            if self.y_label and y_for_line is not None:
                y_min = min(vr.top(), vr.bottom())
                y_max = max(vr.top(), vr.bottom())
                y_vis = float(max(y_min, min(y_max, y_for_line)))
                dx_per_px, _ = vb.viewPixelSize()
                x_left = min(vr.left(), vr.right())
                x_for_badge = x_left + dx_per_px * 10.0  # ~10 px inside view
                yb.setHtml(
                    "<div style='background:#c62828;color:#fff;"
                    "padding:2px 6px;border-radius:2px;font-weight:600;'>"
                    f"{y_vis:.6g}</div>"
                )
                yb.setAnchor(pg.Point(0.0, 0.5))
                yb.setPos(x_for_badge, y_vis)
                yb.setVisible(True)
            else:
                yb.setVisible(False)

            # VAL green badge at intersection with tolerance (percent of X-span)
            tol_span = abs(vr.right() - vr.left())
            val_ok = (
                    self.value_label
                    and isinstance(val, (int, float))
                    and (dx is not None)
                    and tol_span > 0
                    and dx <= tol_span * self.val_tolerance
            )

            if val_ok and y_for_line is not None:
                cr.setData([shared_x], [float(y_for_line)])
                cr.setVisible(True)
                gb.setHtml(
                    "<div style='background:#2e7d32;color:#fff;"
                    "padding:2px 6px;border-radius:2px;font-weight:600;'>"
                    f"{float(val):.6g}</div>"
                )
                gb.setAnchor(pg.Point(0.0, 1.0))
                gb.setPos(shared_x, float(y_for_line))
                gb.setVisible(True)
            else:
                cr.setVisible(False)
                gb.setVisible(False)

        self._update()

    def _update(self):
        # Intentionally empty; PyQtGraph handles repaint internally.
        return

    def disconnect(self):
        """Disconnect mouse move handler."""
        try:
            if self._proxy is not None and self._scene is not None:
                self._scene.sigMouseMoved.disconnect(self._proxy)
        except Exception:
            pass
        self._proxy = None

    # Helpers

    def _snap_value_for_plot(self, plot: PlotItem, x: float) -> Tuple[
        Optional[float], Optional[float], Optional[float]]:
        """Return (val, x_snap, dx). If two lines, average Y at nearest X."""
        try:
            items = [it for it in plot.listDataItems() if isinstance(it, PlotDataItem) and it.isVisible()]
            if not items:
                return None, None, None

            def snap_on_item(it, xq):
                try:
                    import numpy as np
                    xd = getattr(it, "xData", None)
                    yd = getattr(it, "yData", None)
                    if xd is None or yd is None:
                        xd, yd = it.getData()
                    if xd is None or yd is None:
                        return None, None, None
                    xd = np.asarray(xd)
                    yd = np.asarray(yd)
                    n = xd.shape[0]
                    if n == 0 or yd.shape[0] != n:
                        return None, None, None
                    if n == 1:
                        return float(yd[0]), float(xd[0]), abs(float(xq - xd[0]))
                    mono_up = (xd[1:] >= xd[:-1]).all()
                    mono_dn = (xd[1:] <= xd[:-1]).all()
                    if mono_up or mono_dn:
                        idx = int(np.searchsorted(xd, xq))
                        if idx <= 0:
                            idx = 0
                        elif idx >= n:
                            idx = n - 1
                        if 0 < idx < n and abs(xq - xd[idx - 1]) <= abs(xq - xd[idx]):
                            idx -= 1
                    else:
                        idx = int(np.argmin(np.abs(xd - xq)))
                    return float(yd[idx]), float(xd[idx]), abs(float(xq - xd[idx]))
                except Exception:
                    return None, None, None

            val1, xs1, dx1 = snap_on_item(items[0], x)
            if len(items) >= 2:
                val2, xs2, dx2 = snap_on_item(items[1], x)
                if val1 is not None and val2 is not None:
                    val = (val1 + val2) / 2.0
                    if dx1 is not None and dx2 is not None:
                        return (val, xs1, dx1) if dx1 <= dx2 else (val, xs2, dx2)
                    return val, xs1 if xs1 is not None else xs2, dx1 if dx1 is not None else dx2
                return (val1, xs1, dx1) if val1 is not None else (val2, xs2, dx2)
            else:
                return val1, xs1, dx1
        except Exception:
            return None, None, None