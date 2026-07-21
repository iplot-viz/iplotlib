import os

from PySide6.QtCore import QMargins, Qt, Signal, QEvent, QTimer
from PySide6.QtGui import QFont, QFontMetricsF
from PySide6.QtWidgets import QVBoxLayout, QMenu, QMessageBox, QSplitter

import numpy as np
from iplotlib.core import Canvas, PlotXY, PlotContour, SignalXY, PlotContourWithSlider
from iplotlib.core.distance import DistanceCalculator
from iplotlib.core.ruler import Ruler
from iplotlib.impl.pyqtgraph.pyQtGraphCanvas import PyQtGraphParser
from iplotlib.impl.pyqtgraph.dateFormatter import (
    NanosecondDateFormatter,
    is_time_label,
    _pick_interval,
    _generate_ticks,
    _segments_for_interval,
)
from iplotlib.qt.gui.iplotQtCanvas import IplotQtCanvas
from iplotlib.qt.gui.iplotSignalShiftDialog import SignalShiftDialog
import iplotLogging.setupLogger as Sl
from pyqtgraph import PlotItem, TextItem
import pyqtgraph as pg

logger = Sl.get_logger(__name__)


class QtPyQtGraphCanvas(IplotQtCanvas):
    """Qt widget that internally uses a matplotlib canvas backend"""

    dropSignal = Signal(object)
    _PREVIEW_RULER_NAME = "__preview__"

    def __init__(self, parent=None, tight_layout=True, **kwargs):
        super().__init__(parent, **kwargs)

        self._dist_calculator = DistanceCalculator()
        self._draw_call_counter = 0
        # Ruler drag state: an existing ruler grabbed with a single left click.
        self._ruler_drag = None
        self._ruler_drag_echoes = []
        # Ghost ruler previewing where a double-click would place the next one.
        self._preview_ruler_plot = None
        self._preview_ruler_identity = None
        self._preview_scene = None

        self._parser = PyQtGraphParser(tight_layout=tight_layout, impl_flush_method=self.draw_in_main_thread, **kwargs)
        self._parser._on_legend_right_click = self._on_legend_right_click

        # Track connected ViewBoxes to avoid duplicate connections
        self._connected_viewboxes = set()

        self._minimap_widget = pg.GraphicsLayoutWidget()
        self._minimap_widget.setMinimumHeight(110)
        self._minimap_widget.setVisible(False)
        self._minimap_widget.setBackground('#f5f5f5')
        self._minimap_plot = self._minimap_widget.addPlot(row=0, col=0)
        self._minimap_plot.setMouseEnabled(x=False, y=False)
        self._minimap_plot.showAxis('left')
        self._minimap_plot.showAxis('bottom')
        self._minimap_plot.setMenuEnabled(False)
        self._minimap_plot.hideButtons()
        self._minimap_common_label = None
        self._minimap_viewport_item = None
        self._minimap_connected_main_vb = None
        self._minimap_signature = None

        self._splitter = QSplitter(Qt.Orientation.Vertical, self)
        self._splitter.setContentsMargins(QMargins())
        self._splitter.setChildrenCollapsible(False)
        self._splitter.addWidget(self._parser.figure)
        self._splitter.addWidget(self._minimap_widget)
        self._splitter.setStretchFactor(0, 4)
        self._splitter.setStretchFactor(1, 1)

        self._vlayout = QVBoxLayout(self)
        self._vlayout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._vlayout.setContentsMargins(QMargins())
        self._vlayout.addWidget(self._splitter)

        self.setLayout(self._vlayout)
        self.set_canvas(kwargs.get('canvas'))

        # Drag & Drop
        self.setAcceptDrops(True)

    def set_canvas(self, canvas):
        prev_canvas = self._parser.canvas

        if prev_canvas != canvas and prev_canvas is not None and canvas is not None:
            self.unfocus_plot()
            self._connected_viewboxes.clear()
            # The scene is recreated with the ViewBoxes; drop the stale hook.
            self._disconnect_preview_scene()

        self._parser.deactivate_cursor()
        self._parser.process_ipl_canvas(canvas)
        self._parser.figure.ci.layout.activate()

        if canvas:
            self.set_mouse_mode(self._mmode or canvas.mouse_mode)

        # Connect events for each plot - only connect if not already connected
        for stack in self._parser._layout_stacks.values():
            for plot in stack.values():
                vb = plot.getViewBox()
                vb_id = id(vb)
                if vb_id not in self._connected_viewboxes:
                    vb.pressed.connect(self._impl_mouse_press_handler)
                    vb.released.connect(self._impl_mouse_release_handler)
                    vb.dragged.connect(self._impl_mouse_drag_handler)
                    # Ruler labels are positioned in scene coordinates; a widget
                    # resize moves the axes without a range change, so re-project.
                    vb.sigResized.connect(self._on_viewbox_resized)
                    self._connected_viewboxes.add(vb_id)

        super().set_canvas(canvas)
        self._repaint_rulers_from_canvas()
        self._update_minimap()

    def _repaint_rulers_from_canvas(self):
        self._clear_preview_ruler()
        self._preview_ruler_identity = None
        self._ruler_window.clear_info()
        canvas = self._parser.canvas
        if not canvas:
            return
        self._ruler_window.set_canvas_columns(len(canvas.plots))
        for col_idx, col in enumerate(canvas.plots):
            for row_idx, plot in enumerate(col):
                if not plot or not getattr(plot, 'rulers', None):
                    continue
                impl_plot = self._get_impl_plot_for_plot(plot)
                if impl_plot is None:
                    continue
                plot_id = (row_idx + 1, col_idx + 1)
                is_date = bool(getattr(plot.axes[0], 'is_date', False))
                for ruler in plot.rulers:
                    x_view = self._parser.transform_value(impl_plot, 0, ruler.xy[0], inverse=True)
                    y_view = self._parser.transform_value(impl_plot, 1, ruler.xy[1], inverse=True)
                    self._parser.add_ruler(impl_plot, ruler.name, x_view, y_view, ruler.color)
                    self._parser.create_ruler_echoes(impl_plot, ruler.name,
                                                     ruler.xy[0], ruler.xy[1], ruler.color)
                    self._ruler_window.add_row(ruler.name, plot_id, ruler.xy,
                                                ruler.color, ruler.visible, is_date,
                                                ruler.font_color, ruler.show_label,
                                                ruler.show_val_label,
                                                self._parser.ruler_signal_values_shared(impl_plot, x_view),
                                                x_is_time=self._plot_x_is_time(plot))
                    self._apply_ruler_state(ruler)
                self._ruler_window.count = max(self._ruler_window.count, len(plot.rulers))

    def _get_main_plot_for_minimap(self) -> PlotItem:
        canvas = self.get_canvas()
        if canvas is None:
            return None
        target = canvas.get_minimap_target_plot()
        if target is None:
            return None
        impl_list = self._parser._plot_impl_plot_lut.get(id(target))
        if impl_list:
            return impl_list[-1]
        for stack in self._parser._layout_stacks.values():
            for plot in stack.values():
                return plot
        return None

    def _minimap_font_size(self, target_plot) -> int:
        """Font size for the minimap tick labels: the same effective size as the
        main plot it mirrors, so a font-size change propagates to both (#141).

        Resolved through the usual property hierarchy (x-axis -> plot -> canvas
        -> default) rather than a dedicated minimap control, keeping the setting
        single-sourced.
        """
        axis = target_plot.axes[0] if (target_plot is not None and getattr(target_plot, 'axes', None)) else None
        ref = axis if axis is not None else target_plot
        fs = self._parser._pm.get_value(ref, 'font_size') if ref is not None else None
        return int(fs) if fs else 8

    def _apply_minimap_tick_font(self, fs: int):
        """Apply the resolved font size to both minimap axes' tick labels (and the
        bottom axis's UTC common label, matching the main axis).

        The bottom axis height and the common-label height are grown from the
        font metrics so larger labels are not clipped, mirroring what the main
        axis does in pyQtGraphCanvas.process_ipl_axis_params.
        """
        font = QFont()
        font.setPointSize(int(fs))
        fm = QFontMetricsF(font)
        for side in ('bottom', 'left'):
            self._minimap_plot.getAxis(side).setStyle(tickFont=font)
        bottom = self._minimap_plot.getAxis('bottom')
        # tickLength default is 4; +2 padding, same formula as the main axis.
        bottom.setHeight(int(fm.height() + 4 + 2))
        common = getattr(bottom, 'common_label', None)
        if common is not None:
            common.setMaximumHeight(int(fm.height() + 2))
            if getattr(bottom, 'offset_str', None):
                common.setText(bottom.offset_str, size=f'{int(fs)}pt')

    def _update_minimap(self):
        canvas = self.get_canvas()
        show = canvas is not None and canvas.show_minimap and canvas.is_minimap_eligible()
        self._minimap_widget.setVisible(show)
        if show:
            total = max(self._splitter.height(), 1)
            minimap_h = max(int(total * 0.22), 110)
            self._splitter.setSizes([total - minimap_h, minimap_h])
        if not show:
            self._minimap_plot.clear()
            self._minimap_viewport_item = None
            self._minimap_signature = None
            self._disconnect_minimap_signals()
            return

        main_plot = self._get_main_plot_for_minimap()
        if main_plot is None:
            QTimer.singleShot(0, self._update_minimap)
            return

        target_plot = canvas.get_minimap_target_plot()
        baseline = canvas.get_minimap_baseline()
        cur_min, cur_max = self._parser.get_oaw_axis_limits(main_plot, 0)
        if cur_min is None or cur_max is None:
            return
        if baseline is None:
            canvas.snapshot_minimap_baseline(cur_min, cur_max)
            baseline = canvas.get_minimap_baseline()

        # The minimap works relative to an integer offset so that huge absolute
        # nanosecond coordinates (~1.8e18) never reach the ViewBox, where they
        # overflow numpy's cast in updateViewRange. That only applies to the
        # absolute *date* axis; a relative-time (seconds) axis has small values
        # and must NOT be shifted, or its labels would show the wrong time
        # (and int() of a negative start would shift the wrong way).
        is_date_axis = bool(target_plot.axes and getattr(target_plot.axes[0], 'is_date', False))
        self._minimap_offset = int(baseline[0]) if (baseline is not None and is_date_axis) else 0

        # Mirror the main plot's font size so the minimap ticks stay legible and
        # track font-size changes (issue #141). Part of the signature so a change
        # forces a rebuild that re-applies it.
        fs = self._minimap_font_size(target_plot)
        signature = (id(target_plot), baseline, fs)
        if self._minimap_signature == signature and self._minimap_viewport_item is not None:
            mm_off = getattr(self, '_minimap_offset', 0)
            self._minimap_viewport_item.setRegion((cur_min - mm_off, cur_max - mm_off))
            self._connect_minimap_signals(main_plot)
            return

        self._minimap_plot.clear()
        self._minimap_viewport_item = None
        bottom_axis = self._minimap_plot.getAxis('bottom')
        if not isinstance(bottom_axis, NanosecondDateFormatter) or getattr(bottom_axis, 'is_date', None) != is_date_axis:
            new_bottom = NanosecondDateFormatter(is_date=is_date_axis, orientation='bottom')
            self._minimap_plot.setAxisItems({'bottom': new_bottom})
            if self._minimap_common_label is not None:
                try:
                    self._minimap_widget.ci.removeItem(self._minimap_common_label)
                except Exception:
                    pass
            self._minimap_widget.ci.addItem(new_bottom.common_label, row=1, col=0)
            new_bottom.common_label.setMaximumHeight(14)
            self._minimap_common_label = new_bottom.common_label
        # Keep the minimap axis on the same integer offset as the data we plot.
        self._minimap_plot.getAxis('bottom').set_offset(self._minimap_offset)
        # The minimap builds its own axis without the main plot's 'Time' label,
        # so tell it explicitly whether this is a relative-time axis (only then
        # does it render durations; otherwise plain numeric like the main axis).
        # Mirror the main bottom axis's relative-time decision (it was flagged
        # authoritatively when its 'Time' label was applied). Falls back to the
        # iplotlib axis label if the main axis can't report.
        _mm_is_time = False
        if not is_date_axis:
            try:
                _mm_is_time = main_plot.getAxis('bottom')._is_rel_time()
            except Exception:
                _mm_is_time = (bool(target_plot.axes)
                               and is_time_label(getattr(target_plot.axes[0], 'label', None)))
        self._minimap_plot.getAxis('bottom')._force_is_time = _mm_is_time
        for signals in target_plot.signals.values():
            for sig in signals:
                if not isinstance(sig, SignalXY):
                    continue
                x_data = getattr(sig, '_minimap_x_data', None)
                y_data = getattr(sig, '_minimap_y_data', None)
                if x_data is None or len(x_data) == 0:
                    x_data = getattr(sig, 'x_data', None)
                    y_data = getattr(sig, 'y_data', None)
                if x_data is None or y_data is None:
                    continue
                if len(x_data) == 0 or len(y_data) == 0:
                    continue
                # Plot relative to the minimap offset (keeps coordinates small).
                x_data = np.asarray(x_data) - self._minimap_offset
                color = sig.color or '#1976d2'
                pen = pg.mkPen(color, width=1)
                y_max = getattr(sig, '_minimap_y_max_data', None)
                y_avg = getattr(sig, '_minimap_y_avg_data', None)
                if (getattr(sig, 'envelope', False) and y_max is not None
                        and y_avg is not None and len(y_max) == len(x_data)
                        and len(y_avg) == len(x_data)):
                    c_min = self._minimap_plot.plot(x_data, y_data, pen=pg.mkPen(color, width=0))
                    c_max = self._minimap_plot.plot(x_data, y_max, pen=pg.mkPen(color, width=0))
                    qcolor = pg.mkColor(color)
                    qcolor.setAlphaF(0.3)
                    self._minimap_plot.addItem(pg.FillBetweenItem(c_min, c_max, brush=pg.mkBrush(qcolor)))
                    self._minimap_plot.plot(x_data, y_avg, pen=pen)
                else:
                    self._minimap_plot.plot(x_data, y_data, pen=pen)
        self._minimap_plot.getViewBox().setLimits(xMin=baseline[0] - self._minimap_offset,
                                                  xMax=baseline[1] - self._minimap_offset)
        self._minimap_plot.setXRange(baseline[0] - self._minimap_offset,
                                     baseline[1] - self._minimap_offset, padding=0)
        self._minimap_plot.getViewBox().disableAutoRange(axis=pg.ViewBox.XAxis)

        # Give the minimap a FIXED set of human-readable ticks derived from the
        # draw/baseline window. Pinning them with setTicks() means the labels
        # describe the queried time range and stay put while the main plot is
        # panned/zoomed, instead of inheriting the main axis's dynamic precision
        # (which collapsed to a repeated hour field, e.g. "15").
        self._apply_minimap_static_ticks(self._minimap_plot.getAxis('bottom'), baseline)
        self._apply_minimap_tick_font(fs)

        region = pg.LinearRegionItem(values=[cur_min - self._minimap_offset, cur_max - self._minimap_offset],
                                     movable=False,
                                     brush=pg.mkBrush(255, 179, 0, 120),
                                     pen=pg.mkPen('#e65100', width=2))
        region.setZValue(10)
        self._minimap_plot.addItem(region, ignoreBounds=True)
        self._minimap_viewport_item = region
        self._minimap_signature = signature
        full_span = baseline[1] - baseline[0]
        shows_full = full_span > 0 and abs(cur_min - baseline[0]) < full_span * 1e-6 and abs(cur_max - baseline[1]) < full_span * 1e-6
        region.setVisible(not shows_full)

        self._connect_minimap_signals(main_plot)

    def _connect_minimap_signals(self, main_plot):
        if self._minimap_connected_main_vb is main_plot:
            return
        self._disconnect_minimap_signals()
        main_plot.sigRangeChanged.connect(self._on_main_x_range_changed)
        self._minimap_connected_main_vb = main_plot

    def _apply_minimap_static_ticks(self, axis, baseline):
        """Pin the minimap's bottom axis to a fixed, human-readable set of date
        ticks computed once from the draw/baseline window.

        The minimap reuses the main NanosecondDateFormatter, whose label
        precision is driven by the *main* view, so its ticks collapsed to a
        repeated coarse field (e.g. "15"). Here we compute nice civil-time ticks
        for the fixed baseline range and install them with setTicks(), which
        bypasses the dynamic tickValues/tickStrings. The result: the minimap
        labels describe the queried time range and do not change while the main
        plot is panned or zoomed. setTicks persists across redraws, so the labels
        stay put until the next Draw replaces the baseline.
        """
        try:
            abs_lo, abs_hi = int(baseline[0]), int(baseline[1])
        except (TypeError, ValueError, IndexError):
            axis.setTicks(None)
            return
        if abs_hi <= abs_lo or not getattr(axis, 'is_date', True):
            axis.setTicks(None)
            return

        offset = int(getattr(self, '_minimap_offset', 0))
        n = getattr(axis, 'n_ticks', 7)
        step_ns, kind = _pick_interval(abs_hi - abs_lo, n)
        ticks_abs = _generate_ticks(abs_lo, abs_hi, step_ns, kind)
        if not ticks_abs:
            axis.setTicks(None)
            return

        cut = axis.lcp(abs_lo, abs_hi)
        end_seg = max(cut + 1, _segments_for_interval(step_ns, kind))
        major = [(t - offset, axis.date_fmt(t, cut + 1, end_seg)) for t in ticks_abs]

        # Shared prefix (date) goes in the common label, like the main axis.
        axis.cut_start = cut
        axis.offset_str = 'UTC:' + axis.date_fmt(abs_lo, axis.YEAR, cut,
                                                 postfix_end=axis.postfix_end,
                                                 postfix_start=axis.postfix_start)
        if getattr(axis, 'common_label', None) is not None:
            axis.common_label.setText(axis.offset_str)
        axis.setTicks([major, []])

    def _disconnect_minimap_signals(self):
        if self._minimap_connected_main_vb is not None:
            try:
                self._minimap_connected_main_vb.sigRangeChanged.disconnect(self._on_main_x_range_changed)
            except Exception:
                pass
            self._minimap_connected_main_vb = None

    def _on_main_x_range_changed(self, window, view_range):
        if self._minimap_viewport_item is None:
            return
        main_plot = self._get_main_plot_for_minimap()
        if main_plot is None:
            return
        x_lo, x_hi = self._parser.get_oaw_axis_limits(main_plot, 0)
        if x_lo is None or x_hi is None:
            return
        canvas = self.get_canvas()
        baseline = canvas.get_minimap_baseline() if canvas is not None else None
        if baseline is not None:
            full_span = baseline[1] - baseline[0]
            shows_full = full_span > 0 and abs(x_lo - baseline[0]) < full_span * 1e-6 and abs(x_hi - baseline[1]) < full_span * 1e-6
            self._minimap_viewport_item.setVisible(not shows_full)
        mm_off = getattr(self, '_minimap_offset', 0)
        self._minimap_viewport_item.setRegion((x_lo - mm_off, x_hi - mm_off))

    def _sync_minimap_viewport(self):
        main_plot = self._get_main_plot_for_minimap()
        if main_plot is None or self._minimap_viewport_item is None:
            return
        self._on_main_x_range_changed(main_plot, main_plot.getViewBox().viewRange())

    def get_base_plot(self) -> PlotItem:
        for stack in self._parser._layout_stacks.values():
            for plot in stack.values():
                return plot

    def get_canvas(self) -> Canvas:
        """Gets current iplotlib canvas"""
        return self._parser.canvas

    def _is_signal_visible(self, signal) -> bool:
        """Check if signal is visible (PyQtGraph implementation)."""
        if not hasattr(signal, 'lines') or not signal.lines:
            return True  # Assume visible if no lines yet (signal being processed)
        try:
            return signal.lines[0].isVisible()
        except (IndexError, AttributeError):
            return True

    def draw_marker_label(self, marker_name, plot_id, signal_uid, xy, color, modify):
        signal, ax = self.get_signal_marker(plot_id, signal_uid)  # type: PlotItem

        # Creation of the annotations
        if isinstance(signal, SignalXY) and ax:
            if not modify:
                # Create and draw marker
                x = self._parser.transform_value(ax, 0, xy[0], inverse=True)
                y = xy[1]

                marker_text = TextItem(anchor=(0.5, 0.5),
                                       html=f"""<div style="
                                       background-color:{color};
                                       color:black;
                                       border:1px solid black;
                                       border-radius:4px;
                                       padding:2px 5px;
                                       font-size:12pt;
                                       text-align:center;
                                        ">{marker_name}</div>""")
                marker_text.setPos(x, y)
                ax.addItem(marker_text)

                # Get marker row
                row = self.get_marker_row(signal, marker_name)

                # Set marker visibility
                signal.markers_list[row].visible = True
                signal.markers_list[row].color = color
            else:
                # Change marker color when it is visible
                annotations = [child for child in ax.items if isinstance(child, TextItem)]
                if annotations:
                    for annotation in annotations:
                        if annotation.toPlainText() == marker_name:
                            # Set new color property
                            new_html = f"""<div style="
                                            background-color:{color};
                                            color:black;
                                            border:1px solid black;
                                            border-radius:4px;
                                            padding:2px 5px;
                                            font-size:12pt;
                                            text-align:center;
                                        ">{marker_name}</div>"""

                            annotation.setHtml(new_html)
                            annotation.update()

                            # Get marker row
                            row = self.get_marker_row(signal, marker_name)
                            signal.markers_list[row].color = color

    def delete_marker_label(self, marker_name, plot_id, signal_uid, delete):
        signal, ax = self.get_signal_marker(plot_id, signal_uid)

        # Get annotations from the axis
        annotations = [child for child in ax.items if isinstance(child, TextItem)]

        # Get marker row
        row = self.get_marker_row(signal, marker_name)

        # Indicate if the marker will be removed or hidden
        if delete:
            signal.delete_marker(row)
        else:
            signal.markers_list[row].visible = False

        # Remove annotations
        if annotations:
            for annotation in annotations:
                if annotation.toPlainText() == marker_name:
                    ax.removeItem(annotation)
                    return

    def _get_plot_by_id(self, plot_id):
        return self._plot_at_canvas_position(plot_id)

    def _get_impl_plot_for_plot(self, plot):
        """Return the first impl PlotItem hosting *plot* (lowest stack key).

        The layout_stacks key is the 0-indexed (row_idx, col_idx) from the
        canvas grid iteration, which is not the same as plot.row / plot.col.
        """
        canvas = self._parser.canvas
        if canvas is None:
            return None
        for col_idx, col in enumerate(canvas.plots):
            for row_idx, p in enumerate(col):
                if p is plot:
                    stack_dict = self._parser._layout_stacks.get((row_idx, col_idx), {})
                    if not stack_dict:
                        return None
                    first_key = min(stack_dict.keys())
                    return stack_dict[first_key]
        return None

    def delete_ruler(self, name, plot_id, persist):
        plot = self._get_plot_by_id(plot_id)
        if plot is None:
            return
        impl_plot = self._get_impl_plot_for_plot(plot)
        if impl_plot is not None:
            # Removes the origin and its shared-x echoes across every plot.
            self._parser.remove_ruler_by_name(name)
        if persist:
            plot.remove_ruler(name)
        # The freed name may change what the next ruler will be called.
        self._clear_preview_ruler()
        self._preview_ruler_identity = None

    def toggle_ruler_visibility(self, name, plot_id, visible):
        plot = self._get_plot_by_id(plot_id)
        if plot is None:
            return
        ruler = plot.get_ruler(name)
        if ruler:
            ruler.visible = visible
        # Apply to the origin and its echoes (names are canvas-global unique).
        for r in self._parser.get_rulers():
            if r.name == name:
                r.set_visible(visible)

    def change_ruler_color(self, name, plot_id, color):
        plot = self._get_plot_by_id(plot_id)
        if plot is None:
            return
        ruler = plot.get_ruler(name)
        if ruler:
            ruler.color = color
        for r in self._parser.get_rulers():
            if r.name == name:
                r.set_color(color)

    def change_ruler_font_color(self, name, plot_id, color):
        plot = self._get_plot_by_id(plot_id)
        if plot is None:
            return
        ruler = plot.get_ruler(name)
        if ruler:
            ruler.font_color = color
        for r in self._parser.get_rulers():
            if r.name == name:
                r.set_font_color(color)

    def toggle_ruler_label(self, name, plot_id, show_label, show_val_label):
        plot = self._get_plot_by_id(plot_id)
        if plot is None:
            return
        ruler = plot.get_ruler(name)
        if ruler:
            ruler.show_label = show_label
            ruler.show_val_label = show_val_label
        for r in self._parser.get_rulers():
            if r.name == name:
                r.set_show_label(show_label)
                r.set_show_val_label(show_val_label)

    def _add_ruler_at(self, impl_plot, plot, x: float, y: float,
                      name: str = None, color: str = None):
        if name is None:
            name = self._ruler_window.next_name()
        if color is None:
            color = self._ruler_window.next_color(name)
        x_abs = self._parser.transform_value(impl_plot, 0, x)
        y_abs = self._parser.transform_value(impl_plot, 1, y)
        ruler = Ruler(name=name, xy=(x_abs, y_abs), color=color, visible=True)
        plot.add_ruler(ruler)
        # The ghost previewing this ruler is superseded by the real one.
        self._clear_preview_ruler()
        self._preview_ruler_identity = None
        self._parser.add_ruler(impl_plot, name, x, y, ruler.color)
        self._parser.create_ruler_echoes(impl_plot, name, x_abs, y_abs, ruler.color)
        is_date = bool(getattr(plot.axes[0], 'is_date', False))
        plot_id = self._canvas_position_of(plot) or (1, 1)
        self._ruler_window.set_canvas_columns(len(self._parser.canvas.plots))
        self._ruler_window.add_row(name, plot_id, (x_abs, y_abs), ruler.color,
                                    visible=True, is_date=is_date,
                                    signal_values=self._parser.ruler_signal_values_shared(impl_plot, x),
                                    x_is_time=self._plot_x_is_time(plot))
        if not self._ruler_window.isVisible():
            self._ruler_window.show()
        # Do not steal focus from the canvas.
        self.window().activateWindow()

    def _begin_ruler_drag(self, impl_plot, plot, ruler):
        """Grab an existing ruler (and gather its echoes) to drag across the plot."""
        self._clear_preview_ruler()
        self._ruler_drag = (impl_plot, plot, ruler)
        # Shared-x echoes move in lockstep with the origin during the drag.
        self._ruler_drag_echoes = [r for r in self._parser.get_rulers()
                                   if r.name == ruler.name and r is not ruler]

    def _drag_ruler_to(self, view_box, scene_pos):
        """Move the grabbed ruler and its shared-x echoes to the cursor (live)."""
        impl_plot, _, ruler = self._ruler_drag
        view_pos = view_box.mapSceneToView(scene_pos)
        x_abs = self._parser.transform_value(impl_plot, 0, view_pos.x())
        y_abs = self._parser.transform_value(impl_plot, 1, view_pos.y())
        ruler.abs_x = x_abs
        ruler.abs_y = y_abs
        ruler.xy = (view_pos.x(), view_pos.y())
        ruler.refresh_labels()
        for echo in self._ruler_drag_echoes:
            echo.abs_x = x_abs
            echo.abs_y = y_abs
            echo.xy = (self._parser.transform_value(echo.plot, 0, x_abs, inverse=True),
                       self._parser.transform_value(echo.plot, 1, y_abs, inverse=True))
            echo.refresh_labels()

    def _end_ruler_drag(self):
        """Persist the dragged ruler's new position to the model and the window.
        The model ruler and its window row live on the origin's plot, so route
        there even when a shared-x echo was the artist being dragged."""
        _, _, ruler = self._ruler_drag
        echoes = self._ruler_drag_echoes
        self._ruler_drag = None
        self._ruler_drag_echoes = []
        origin = next((r for r in [ruler] + echoes if not r.is_echo), ruler)
        self._persist_ruler_position(origin)

    def _persist_ruler_position(self, origin):
        """Write an origin ruler's current (abs_x, y) to its model ruler and its
        row in the Ruler window."""
        ci = self._parser._impl_plot_cache_table.get_cache_item(origin.plot)
        origin_plot = ci.plot() if ci else None
        if origin_plot is None:
            return
        x_abs, y_abs = origin.abs_x, origin.abs_y
        core = origin_plot.get_ruler(origin.name)
        if core is not None:
            core.xy = (x_abs, y_abs)
        plot_id = self._canvas_position_of(origin_plot) or (1, 1)
        self._ruler_window.update_row_xy(
            origin.name, plot_id, (x_abs, y_abs),
            signal_values=self._parser.ruler_signal_values_shared(origin.plot, origin.xy[0]))

    def _on_viewbox_resized(self, view_box):
        impl_plot = view_box.parentItem()
        if impl_plot is not None:
            self._parser.refresh_rulers(impl_plot)

    def _preview_identity_for_next(self):
        """Name/color the next ruler will get, so the ghost previews them."""
        if self._preview_ruler_identity is not None:
            return self._preview_ruler_identity
        name = self._ruler_window.next_name()
        return {'name': name, 'color': self._ruler_window.next_color(name)}

    def _show_preview_ruler(self, impl_plot, x: float, y: float):
        ident = self._preview_identity_for_next()
        existing = next((r for r in self._parser.get_rulers(impl_plot)
                         if r.name == self._PREVIEW_RULER_NAME), None)
        if existing is not None and self._preview_ruler_plot is impl_plot:
            existing.abs_x = self._parser.transform_value(impl_plot, 0, x)
            existing.abs_y = self._parser.transform_value(impl_plot, 1, y)
            existing.xy = (x, y)
            existing.refresh_labels()
            return
        self._clear_preview_ruler()
        ruler = self._parser.add_ruler(impl_plot, self._PREVIEW_RULER_NAME, x, y, ident['color'])
        ruler.set_label_text(ident['name'])
        self._preview_ruler_plot = impl_plot
        self._preview_ruler_identity = ident

    def _clear_preview_ruler(self):
        plots_with_preview = {r.plot for r in self._parser.get_rulers()
                              if r.name == self._PREVIEW_RULER_NAME}
        for plot in plots_with_preview:
            self._parser.remove_ruler(plot, self._PREVIEW_RULER_NAME)
        self._preview_ruler_plot = None

    def _connect_preview_scene(self):
        if self._preview_scene is not None:
            return
        for stack in self._parser._layout_stacks.values():
            for plot in stack.values():
                scene = plot.scene()
                if scene is not None and hasattr(scene, 'sigMouseMoved'):
                    scene.sigMouseMoved.connect(self._on_scene_mouse_moved)
                    self._preview_scene = scene
                    return

    def _disconnect_preview_scene(self):
        if self._preview_scene is None:
            return
        try:
            self._preview_scene.sigMouseMoved.disconnect(self._on_scene_mouse_moved)
        except (RuntimeError, TypeError):
            pass
        self._preview_scene = None

    def _plot_at_scene_pos(self, scene_pos):
        for stack in self._parser._layout_stacks.values():
            for plot in stack.values():
                vb = plot.getViewBox()
                if vb is not None and vb.sceneBoundingRect().contains(scene_pos):
                    return plot, vb
        return None, None

    def _on_scene_mouse_moved(self, scene_pos):
        if self._mmode != Canvas.MOUSE_MODE_RULER or self._ruler_drag is not None:
            return
        impl_plot, vb = self._plot_at_scene_pos(scene_pos)
        # No ghost off-plot or while hovering an existing ruler (a double-click
        # there grabs/ignores instead of creating).
        if impl_plot is None or self._find_ruler_near(impl_plot, scene_pos) is not None:
            self._clear_preview_ruler()
            return
        ci = self._parser._impl_plot_cache_table.get_cache_item(impl_plot)
        plot = ci.plot() if hasattr(ci, 'plot') else None
        if plot is None or isinstance(plot, (PlotContour, PlotContourWithSlider)):
            return
        view_pos = vb.mapSceneToView(scene_pos)
        self._show_preview_ruler(impl_plot, view_pos.x(), view_pos.y())

    def _find_ruler_near(self, impl_plot, scene_pos):
        rulers = self._parser.get_rulers(impl_plot)
        if not rulers:
            return None
        vb = impl_plot.getViewBox()
        best = None
        best_dist = float('inf')
        for r in rulers:
            if r.name == self._PREVIEW_RULER_NAME:
                continue
            ruler_scene_pt = vb.mapViewToScene(pg.Qt.QtCore.QPointF(r.xy[0], r.xy[1]))
            dx = abs(ruler_scene_pt.x() - scene_pos.x())
            dy = abs(ruler_scene_pt.y() - scene_pos.y())
            d = None
            if dx <= self.PICK_RADIUS_PX and dy <= self.PICK_RADIUS_PX:
                d = float(np.hypot(dx, dy))
            else:
                name_label = getattr(r, 'name_label', None)
                if name_label is not None and name_label.isVisible():
                    try:
                        if name_label.sceneBoundingRect().contains(scene_pos):
                            d = 0.0
                    except (RuntimeError, AttributeError):
                        pass
            if d is not None and d < best_dist:
                best_dist = d
                best = r
        return best

    def autoscale_y(self, impl_plot):
        """
            Autoscale the Y axis of a single PlotXY and store the action for undo/redo
        """
        ci = self._parser._impl_plot_cache_table.get_cache_item(impl_plot)
        if hasattr(ci, 'plot'):
            plot = ci.plot()
            if isinstance(plot, PlotXY):
                # Stage a command to obtain original view limits
                self.stage_view_lim_cmd(impl_plot)

                # Autoscale on Y axis for the given plot
                self._parser.autoscale_y_axis(impl_plot)

                # Commit staged command
                while len(self._staging_cmds):
                    self.commit_view_lim_cmd(impl_plot)

                # Push committed command
                while len(self._commitd_cmds):
                    self.push_view_lim_cmd()

                return

    def autoscale_all_y(self):
        """
            Autoscale the Y axis of all PlotXY instances in the figure and store the action for undo/redo
        """
        axes = self._parser.get_canvas_plots()
        for ax in axes:
            ci = self._parser._impl_plot_cache_table.get_cache_item(ax)
            if not hasattr(ci, 'plot'):
                continue
            plot = ci.plot()
            if not isinstance(plot, PlotXY):
                continue

            # Stage a command to obtain original view limits
            self.stage_view_lim_cmd(ax)

            # Autoscale on Y axis for the given plot
            self._parser.autoscale_y_axis(ax)

            # Commit staged command
            while len(self._staging_cmds):
                self.commit_view_lim_cmd(ax)

            # Push committed command
            while len(self._commitd_cmds):
                self.push_view_lim_cmd()

    def save_canvas_image(self, filename: str):
        """Use pyqtgraph exporters instead of QWidget.grab() for accurate rendering."""
        ext = os.path.splitext(filename)[1].lower()
        if ext == '.svg':
            self._save_svg(filename)
        else:
            from pyqtgraph.exporters import ImageExporter
            exporter = ImageExporter(self._parser.figure.scene())
            exporter.parameters()['width'] = self.width()
            exporter.export(filename)
        logger.info(f"Screenshot saved: {os.path.abspath(filename)}")

    def _save_svg(self, filename: str):
        from pyqtgraph.exporters import SVGExporter
        exporter = SVGExporter(self._parser.figure.scene())
        exporter.export(filename)

    def set_mouse_mode(self, mode: str):
        super().set_mouse_mode(mode)

        if self._mmode is None:
            return

        if mode != Canvas.MOUSE_MODE_RULER:
            self._clear_preview_ruler()
            self._preview_ruler_identity = None
            self._disconnect_preview_scene()

        if mode == Canvas.MOUSE_MODE_SELECT:
            self._parser.set_view_box()
        elif mode == Canvas.MOUSE_MODE_CROSSHAIR:
            self._parser.set_view_box_crosshair()
        elif mode == Canvas.MOUSE_MODE_PAN:
            self._parser.set_view_box_pan()
        elif mode == Canvas.MOUSE_MODE_ZOOM:
            self._parser.set_view_box_zoom()
        elif mode == Canvas.MOUSE_MODE_DIST:
            self._parser.set_view_box()
        elif mode == Canvas.MOUSE_MODE_MARKER:
            self._parser.set_view_box()
            if not self._marker_window.isVisible():
                self._marker_window.show()
            elif self._marker_window.isMinimized():
                self._marker_window.showNormal()
            else:
                self._marker_window.raise_()
                self._marker_window.activateWindow()
        elif mode == Canvas.MOUSE_MODE_RULER:
            self._parser.set_view_box()
            self._connect_preview_scene()
            if not self._ruler_window.isVisible():
                self._ruler_window.show()
            elif self._ruler_window.isMinimized():
                self._ruler_window.showNormal()
            # Open behind the canvas.
            self._ruler_window.lower()
            self.window().activateWindow()
            self.window().raise_()

    def undo(self):
        self._parser.undo()

    def redo(self):
        self._parser.redo()

    def _full_screen_mode_on(self, impl_plot):
        self._parser.set_focus_plot(impl_plot)
        canvas = self.get_canvas()
        if canvas is not None:
            canvas.snapshot_minimap_baseline(None, None)
        self.refresh()
        self.stats(self.get_canvas())
        self.focusChanged.emit()

    def _full_screen_mode_off(self):
        self._parser.set_focus_plot(None)
        canvas = self.get_canvas()
        if canvas is not None:
            canvas.snapshot_minimap_baseline(None, None)
        self.refresh()
        self.stats(self.get_canvas())
        self.focusChanged.emit()

    def _impl_mouse_press_handler(self, view_box, event):
        """Handle mouse press events in PyQtGraph."""
        impl_plot = view_box.parentItem()
        if not impl_plot:
            return

        ci = self._parser._impl_plot_cache_table.get_cache_item(impl_plot)
        plot = ci.plot()
        if not plot:
            self._dist_calculator.reset()
            return

        is_double_click = (
                event.type() == QEvent.Type.GraphicsSceneMouseDoubleClick
                or (hasattr(event, 'double') and callable(getattr(event, 'double', None)) and event.double())
        )

        if is_double_click:
            if self._mmode == Canvas.MOUSE_MODE_RULER:
                if event.button() == Qt.MouseButton.LeftButton:
                    if isinstance(plot, (PlotContour, PlotContourWithSlider)):
                        return
                    # Double-clicking on an existing ruler must not stack a new one on top.
                    if self._find_ruler_near(impl_plot, event.scenePos()) is not None:
                        event.accept()
                        return
                    # Double-click creates a ruler at the cursor.
                    system_coord = view_box.mapSceneToView(event.scenePos())
                    self._add_ruler_at(impl_plot, plot, system_coord.x(), system_coord.y())
                    event.accept()
                return
            if self._mmode in [Canvas.MOUSE_MODE_ZOOM, Canvas.MOUSE_MODE_PAN, Canvas.MOUSE_MODE_MARKER,
                               Canvas.MOUSE_MODE_CROSSHAIR]:
                if event.button() == Qt.MouseButton.RightButton:
                    return

                if isinstance(plot, (PlotContour, PlotContourWithSlider)):
                    logger.warning(f"Markers creation is not supported for {type(plot).__name__}")
                    return

                # Markers can only be created if the property 'marker' is not None
                if impl_plot.listDataItems()[0].opts['symbol'] is not None:
                    # Maps from scene coordinates to the coordinate system displayed inside the ViewBox
                    system_coord = view_box.mapSceneToView(event.scenePos())
                    x_value = system_coord.x()
                    y_value = system_coord.y()

                    new_marker, marker_signal, label_line = self._parser.add_marker_scaled(impl_plot, plot, x_value,
                                                                                           y_value)
                    if new_marker is not None:
                        if new_marker not in self._marker_window.get_markers():
                            self._marker_window.add_marker(marker_signal, new_marker, label_line)
                            if not self._marker_window.isVisible():
                                self._marker_window.show()
                            elif self._marker_window.isMinimized():
                                self._marker_window.showNormal()
                            else:
                                self._marker_window.raise_()
                                self._marker_window.activateWindow()
                        else:
                            logger.warning(f"The marker {new_marker} is already created")
                    else:
                        logger.warning(
                            f"Cannot add marker {new_marker}: found {marker_signal} samples, but the maximum allowed is 100")
                else:
                    logger.warning("Markers must be enabled in the plot to create signal markers")
        else:
            # Single click handling
            if self._mmode in [Canvas.MOUSE_MODE_ZOOM, Canvas.MOUSE_MODE_PAN]:
                if isinstance(plot, (PlotContour, PlotContourWithSlider)):
                    return
                if event.button() == Qt.MouseButton.RightButton:
                    return
                self.stage_view_lim_cmd(impl_plot)
                return

            elif self._mmode == Canvas.MOUSE_MODE_SELECT:
                # Handle drag shift with left click
                if event.button() == Qt.MouseButton.LeftButton:
                    signal, y_coord = self._find_signal_at_event(view_box, event)
                    if signal is not None and signal.envelope:
                        logger.warning("Shift is not supported for envelope signals.")
                    elif signal is not None:
                        try:
                            is_datetime = plot.axes[0].is_date
                        except (AttributeError, IndexError):
                            is_datetime = False
                        system_coord = view_box.mapSceneToView(event.scenePos())
                        x_coord = system_coord.x()
                        self._start_drag_shift(impl_plot, signal, y_coord, is_datetime, start_x=x_coord)
                        event.accept()
                    elif ci and hasattr(ci, 'signals') and ci.signals:
                        # Hit-test doesn't find envelope signals (no standard lines).
                        # Check if the plot has any envelope signals to inform the user.
                        for sig_ref in ci.signals:
                            sig = sig_ref()
                            if sig is not None and getattr(sig, 'envelope', False):
                                logger.warning("Shift is not supported for envelope signals.")
                                break

            elif self._mmode == Canvas.MOUSE_MODE_RULER:
                if isinstance(plot, (PlotContour, PlotContourWithSlider)):
                    logger.warning(f"Rulers are not supported for {type(plot).__name__}")
                    return
                if event.button() == Qt.MouseButton.LeftButton:
                    # Grab the nearest ruler to drag; empty space is a no-op.
                    hit = self._find_ruler_near(impl_plot, event.scenePos())
                    if hit is not None:
                        self._begin_ruler_drag(impl_plot, plot, hit)
                        event.accept()
                return

            elif self._mmode == Canvas.MOUSE_MODE_DIST:
                # Maps from scene coordinates to the coordinate system displayed inside the ViewBox
                system_coord = view_box.mapSceneToView(event.scenePos())
                x_value = system_coord.x()
                y_value = system_coord.y()

                if self._dist_calculator.plot1 is not None:
                    try:
                        is_date = plot.axes[0].is_date
                    except (AttributeError, IndexError):
                        is_date = False
                    x = self._parser.transform_value(impl_plot, 0, x_value)
                    self._dist_calculator.set_dst(x, y_value, plot, ci.stack_key)
                    self._dist_calculator.set_dx_is_datetime(is_date)
                    dx, dy, dz = self._dist_calculator.dist()
                    if any([dx, dy, dz]):
                        # Get visible signals from the current plot only
                        plot_signals = self.get_visible_plot_signals(plot)
                        dx_numeric = 0.0 if is_date else float(dx)
                        dialog = SignalShiftDialog(
                            self,
                            dx=dx_numeric,
                            dy=float(dy),
                            dz=float(dz) if dz else 0.0,
                            signals=plot_signals,
                            dx_is_datetime=is_date
                        )
                        if is_date:
                            dialog.set_dx_text(str(dx))
                        dialog.shiftRequested.connect(self.signalShiftRequested.emit)
                        dialog.exec()
                    else:
                        box = QMessageBox(self)
                        box.setWindowTitle('Distance')
                        box.setText("Invalid selection")
                        box.exec_()
                    self._dist_calculator.reset()
                else:
                    x = self._parser.transform_value(impl_plot, 0, x_value)
                    self._dist_calculator.set_src(x, y_value, plot, ci.stack_key)

    def _impl_mouse_release_handler(self, view_box, event):
        """Handle mouse release events in PyQtGraph."""
        impl_plot = view_box.parentItem()

        if self._ruler_drag is not None:
            self._end_ruler_drag()
            return

        # Handle drag shift completion in Select mode
        if self._drag_shift_active and self._mmode == Canvas.MOUSE_MODE_SELECT:
            if event is not None:
                system_coord = view_box.mapSceneToView(event.scenePos())
                x_value = system_coord.x()
                y_value = system_coord.y()
                self._end_drag_shift(y_value, x_value)
            else:
                self._cancel_drag_shift()
            return

        if self._mmode in [Canvas.MOUSE_MODE_ZOOM, Canvas.MOUSE_MODE_PAN]:
            # commit commands from staging.
            while len(self._staging_cmds):
                self.commit_view_lim_cmd(impl_plot)
            # push uncommitted changes onto the command stack.
            while len(self._commitd_cmds):
                self.push_view_lim_cmd()
            # Update statistics
            self.stats(self.get_canvas())
            self._sync_minimap_viewport()

        is_double = callable(getattr(event, 'double', None)) and event.double()
        if event is not None and event.button() == Qt.MouseButton.RightButton and not is_double:
            autoscale_menu = QMenu(self)
            if self._mmode == Canvas.MOUSE_MODE_RULER:
                hit = self._find_ruler_near(impl_plot, event.scenePos())
                if hit is not None:
                    ci_plot = self._parser._impl_plot_cache_table.get_cache_item(impl_plot)
                    plot = ci_plot.plot() if hasattr(ci_plot, 'plot') else None
                    if plot is not None:
                        plot_id = self._canvas_position_of(plot) or (1, 1)
                        autoscale_menu.addAction(
                            f"Remove ruler {hit.name}",
                            lambda n=hit.name, p=plot_id: self._remove_ruler_from_menu(n, p))
                        autoscale_menu.addSeparator()
            autoscale_menu.addAction("Autoscale", lambda: self.autoscale_y(impl_plot))
            autoscale_menu.addAction("Autoscale All", self.autoscale_all_y)
            autoscale_menu.addAction("Reset zoom/pan", lambda: self.reset_plot_view(impl_plot))
            if self._parser.canvas.focus_plot is None:
                autoscale_menu.addAction("Focus on plot",
                                         lambda: self._full_screen_mode_on(impl_plot))
            else:
                autoscale_menu.addAction("Unfocus plot", self._full_screen_mode_off)
            autoscale_menu.addSeparator()
            ci = self._parser._impl_plot_cache_table.get_cache_item(impl_plot)
            if ci:
                autoscale_menu.addAction("Preferences",
                                         lambda: self.openPlotPreferences.emit(ci.plot()))
            nearest_signal, _ = self._find_signal_at_event(view_box, event)
            if nearest_signal:
                autoscale_menu.addAction("Signal Preferences",
                                         lambda s=nearest_signal: self.openPlotPreferences.emit(s))
            screen_pos = event.screenPos()
            if hasattr(screen_pos, 'toPoint'):
                screen_pos = screen_pos.toPoint()
            autoscale_menu.popup(screen_pos)

    def mouse_clicked(self, event):
        if not event.currentItem:
            return
        plot = event.currentItem.parentItem()
        if not plot or not isinstance(plot, PlotItem):
            return
        if event.button() == Qt.MouseButton.LeftButton:
            if event.double():
                self._parser.set_focus_plot(plot)
            else:
                pass
        elif event.button() == Qt.MouseButton.RightButton:
            if event.double():
                pass
            else:
                pass

    def mouse_moved(self, pos):
        pass

    def _impl_mouse_drag_handler(self, view_box, event):
        """Handle mouse drag events for ruler drag and drag-shift preview."""
        if self._ruler_drag is not None:
            if event is not None and view_box.parentItem() is self._ruler_drag[0]:
                self._drag_ruler_to(view_box, event.scenePos())
            return
        if not self._drag_shift_active or self._drag_shift_signal is None:
            return

        impl_plot = view_box.parentItem()
        if impl_plot != self._drag_shift_impl_plot:
            return

        if event is None:
            return

        system_coord = view_box.mapSceneToView(event.scenePos())
        x_value = system_coord.x()
        y_value = system_coord.y()
        if y_value is not None:
            self._update_drag_shift(y_value, x_value)

    def _on_legend_right_click(self, signal, screen_pos):
        """Handle right-click on a legend item to open signal preferences."""
        menu = QMenu(self)
        menu.addAction("Signal Preferences", lambda s=signal: self.openPlotPreferences.emit(s))
        menu.popup(screen_pos.toPoint())

    def _find_signal_at_event(self, view_box, event):
        """
        Find the nearest signal to the event position using pixel-distance calculation.
        Returns (signal, y_data_coord) or (None, None).
        """
        impl_plot = view_box.parentItem()
        if not impl_plot:
            return None, None

        ci = self._parser._impl_plot_cache_table.get_cache_item(impl_plot)

        # Map pixel radius to data-coordinate tolerances for normalization
        scene_pos = event.scenePos()
        view_pos = view_box.mapSceneToView(scene_pos)
        click_x, click_y = view_pos.x(), view_pos.y()

        from PySide6.QtCore import QPointF
        p2 = view_box.mapSceneToView(QPointF(scene_pos.x(), scene_pos.y() + 1.0))
        p3 = view_box.mapSceneToView(QPointF(scene_pos.x() + 1.0, scene_pos.y()))
        # Data units per pixel — invert to get pixels per data unit
        data_per_px_x = abs(p3.x() - view_pos.x())
        data_per_px_y = abs(p2.y() - view_pos.y())
        sx = 1.0 / data_per_px_x if data_per_px_x > 0 else 1.0
        sy = 1.0 / data_per_px_y if data_per_px_y > 0 else 1.0
        click_norm = np.array([click_x * sx, click_y * sy])

        # Precompute x tolerance in data coords for early-exit range check
        tol_x = data_per_px_x * self.PICK_RADIUS_PX

        def get_line_pixel_data(line):
            """Normalize a pyqtgraph line to pixel-equivalent coords for distance calculation."""
            if not hasattr(line, 'getData'):
                return None
            x_data, y_data = line.getData()
            if x_data is None or y_data is None or len(x_data) == 0:
                return None
            x_min, x_max = x_data.min(), x_data.max()
            if not (x_min - tol_x <= click_x <= x_max + tol_x):
                return None
            pixel_coords = np.column_stack([x_data * sx, y_data * sy])
            return pixel_coords, click_norm

        result = self._find_nearest_signal(ci, get_line_pixel_data)
        if result is not None:
            _, signal = result
            return signal, click_y
        return None, None

    def _create_drag_preview(self, dy_offset, dx_offset=0.0):
        """Create/update preview line during drag for PyQtGraph."""
        if self._drag_shift_signal is None or self._drag_shift_impl_plot is None:
            return

        signal = self._drag_shift_signal
        impl_plot = self._drag_shift_impl_plot

        # Get original line data
        if not signal.lines:
            return

        original_line = signal.lines[0]
        x_data, y_data = original_line.getData()
        if x_data is None or y_data is None:
            return

        x_data_shifted = np.array(x_data) + dx_offset if abs(dx_offset) > 1e-10 else x_data
        y_data_shifted = np.array(y_data) + dy_offset

        # Remove old preview line if exists
        self._remove_drag_preview()

        # Get line style from original signal
        pen_color = 'b'
        pen_width = 2
        try:
            original_pen = original_line.opts.get('pen')
            if original_pen:
                pen_color = original_pen.color()
                pen_width = original_pen.width()
        except Exception:
            pass

        # Create preview line with dashed style
        pen = pg.mkPen(color=pen_color, width=pen_width, style=Qt.PenStyle.DashLine)
        self._drag_shift_preview_line = impl_plot.plot(x_data_shifted, y_data_shifted, pen=pen)

    def _remove_drag_preview(self):
        """Remove preview line for PyQtGraph."""
        if self._drag_shift_preview_line is not None:
            try:
                if self._drag_shift_impl_plot is not None:
                    self._drag_shift_impl_plot.removeItem(self._drag_shift_preview_line)
            except Exception:
                pass
            self._drag_shift_preview_line = None
