# Description: A concrete Qt GUI for a matplotlib canvas.
# Author: Piotr Mazur
# Changelog:
#   Sept 2021:  -Fix orphaned matplotlib figure. [Jaswant Sai Panchumarti]
#               -Fix draw_in_main_thread for when C++ object might have been deleted. [Jaswant Sai Panchumarti]
#               -Refactor qt classes [Jaswant Sai Panchumarti]
#               -Port to PySide2 [Jaswant Sai Panchumarti]
#   Jan 2022:   -Introduce custom HistoryManagement for zooming and panning with git style revision control
#                [Jaswant Sai Panchumarti]
#               -Introduce distance calculator. [Jaswant Sai Panchumarti]
#               -Refactor and let superclass methods refresh, reset use set_canvas, get_canvas [Jaswant Sai Panchumarti]
#   May 2022:   -Port to PySide6 and use new backend_qtagg from matplotlib[Leon Kos]
import functools
import typing
from collections.abc import Collection

import numpy as np
from PySide6.QtCore import QMargins, Qt, Slot, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QMessageBox, QSizePolicy, QSplitter, QVBoxLayout, QMenu

import matplotlib.pyplot as plt
from matplotlib.axes import Axes as MPLAxes
from matplotlib.backend_bases import _Mode, DrawEvent, Event, MouseButton, MouseEvent
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qtagg import NavigationToolbar2QT as NavigationToolbar
from matplotlib.figure import Figure
from matplotlib.patches import Rectangle

from iplotlib.core import PlotContour, SignalXY, PlotXY, PlotXYWithSlider, PlotContourWithSlider
from iplotlib.core.canvas import Canvas
from iplotlib.core.distance import DistanceCalculator
from iplotlib.core.ruler import Ruler
from iplotlib.impl.matplotlib.matplotlibCanvas import MatplotlibParser
from iplotlib.impl.matplotlib.dateFormatter import NanosecondDateFormatter, NiceNanosecondLocator, \
    ExponentScalarFormatter, RelativeTimeLocator, is_time_label
from iplotlib.qt.gui.iplotQtCanvas import IplotQtCanvas
from iplotlib.qt.gui.iplotSignalShiftDialog import SignalShiftDialog
import iplotLogging.setupLogger as Sl

logger = Sl.get_logger(__name__)


class QtMatplotlibCanvas(IplotQtCanvas):
    """Qt widget that internally uses a matplotlib canvas backend"""

    dropSignal = Signal(object)
    _PREVIEW_RULER_NAME = "__preview__"

    def __init__(self, parent=None, tight_layout=True, **kwargs):
        super().__init__(parent, **kwargs)

        self._dist_calculator = DistanceCalculator()
        self._draw_call_counter = 0
        # Ruler grabbed for dragging, and its blit background captured on first motion.
        self._ruler_drag = None
        self._ruler_drag_bg = None
        self._ruler_drag_echoes = []
        # Ghost ruler previewing where a double-click would place the next one.
        self._preview_ruler_ax = None
        self._preview_ruler_identity = None
        self._preview_background = None
        self._preview_cid_draw = None

        self._mpl_size_pol = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._parser = MatplotlibParser(tight_layout=tight_layout, impl_flush_method=self.draw_in_main_thread, **kwargs)
        self._mpl_renderer = FigureCanvas(self._parser.figure)
        self._mpl_renderer.setParent(self)
        self._mpl_renderer.setSizePolicy(self._mpl_size_pol)
        self._mpl_toolbar = NavigationToolbar(self._mpl_renderer, self)
        self._mpl_toolbar.setVisible(False)

        self._minimap_figure = Figure()
        self._minimap_renderer = FigureCanvas(self._minimap_figure)
        self._minimap_renderer.setParent(self)
        self._minimap_renderer.setSizePolicy(self._mpl_size_pol)
        self._minimap_renderer.setMinimumHeight(110)
        self._minimap_renderer.setVisible(False)
        self._minimap_axes = None
        self._minimap_viewport_patch = None
        self._minimap_xlim_cid = None
        self._minimap_ylim_cid = None
        self._minimap_connected_main_ax = None
        self._minimap_signature = None

        self._splitter = QSplitter(Qt.Orientation.Vertical, self)
        self._splitter.setContentsMargins(QMargins())
        self._splitter.setChildrenCollapsible(False)
        self._splitter.addWidget(self._mpl_renderer)
        self._splitter.addWidget(self._minimap_renderer)
        self._splitter.setStretchFactor(0, 4)
        self._splitter.setStretchFactor(1, 1)

        self._vlayout = QVBoxLayout(self)
        self._vlayout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._vlayout.setContentsMargins(QMargins())
        self._vlayout.addWidget(self._splitter)

        # GUI event handlers
        self._mpl_renderer.mpl_connect('draw_event', self._mpl_draw_finish)
        self._mpl_renderer.mpl_connect('button_press_event', self._mpl_mouse_press_handler)
        self._mpl_renderer.mpl_connect('button_release_event', self._mpl_mouse_release_handler)
        self._mpl_renderer.mpl_connect('motion_notify_event', self._mpl_mouse_motion_handler)
        self._mpl_renderer.mpl_connect('pick_event', self.on_pick_legend)

        self.setLayout(self._vlayout)
        self.set_canvas(kwargs.get('canvas'))
        self.setAcceptDrops(True)

        self._mouse_impl = None

    # Implement basic superclass functionality
    def set_canvas(self, canvas: Canvas):
        """Sets new iplotlib canvas and redraw"""
        prev_canvas = self._parser.canvas

        if prev_canvas != canvas and prev_canvas is not None and canvas is not None:
            self.unfocus_plot()

        self._parser.deactivate_cursor()
        self._parser.process_ipl_canvas(canvas)

        if canvas:
            self.set_mouse_mode(self._mmode or canvas.mouse_mode)
        else:
            self.render()
            self._update_minimap()
            return

        self.render()
        self._update_minimap()
        super().set_canvas(canvas)
        self._repaint_rulers_from_canvas()

    def _get_main_axes_for_minimap(self):
        canvas = self.get_canvas()
        if canvas is None:
            return None
        target = canvas.get_minimap_target_plot()
        if target is None:
            return None
        impl_list = self._parser._plot_impl_plot_lut.get(id(target))
        if not impl_list:
            return None
        return impl_list[-1]

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

    def _disconnect_minimap_xlim(self):
        if self._minimap_connected_main_ax is not None:
            for cid in (self._minimap_xlim_cid, self._minimap_ylim_cid):
                if cid is None:
                    continue
                try:
                    self._minimap_connected_main_ax.callbacks.disconnect(cid)
                except Exception:
                    pass
        self._minimap_xlim_cid = None
        self._minimap_ylim_cid = None
        self._minimap_connected_main_ax = None

    def _update_minimap(self):
        canvas = self.get_canvas()
        show = canvas is not None and canvas.show_minimap and canvas.is_minimap_eligible()
        self._minimap_renderer.setVisible(show)
        if show:
            total = max(self._splitter.height(), 1)
            minimap_h = max(int(total * 0.22), 110)
            self._splitter.setSizes([total - minimap_h, minimap_h])
        if not show:
            self._disconnect_minimap_xlim()
            self._minimap_figure.clear()
            self._minimap_axes = None
            self._minimap_viewport_patch = None
            self._minimap_signature = None
            self._minimap_renderer.draw_idle()
            return

        main_ax = self._get_main_axes_for_minimap()
        if main_ax is None:
            return

        target_plot = canvas.get_minimap_target_plot()
        baseline = canvas.get_minimap_baseline()
        if baseline is None:
            x_min, x_max = self._parser.get_oaw_axis_limits(main_ax, 0)
            canvas.snapshot_minimap_baseline(x_min, x_max)
            baseline = canvas.get_minimap_baseline()

        # Mirror the main plot's font size so the minimap ticks stay legible and
        # track font-size changes (issue #141). Part of the signature so a change
        # forces a rebuild that re-applies it.
        fs = self._minimap_font_size(target_plot)
        signature = (id(target_plot), baseline, fs)
        if self._minimap_signature != signature or self._minimap_axes is None:
            self._disconnect_minimap_xlim()
            self._minimap_figure.clear()
            ax = self._minimap_figure.add_subplot(111)
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
                    color = sig.color or '#1976d2'
                    y_max = getattr(sig, '_minimap_y_max_data', None)
                    y_avg = getattr(sig, '_minimap_y_avg_data', None)
                    if (getattr(sig, 'envelope', False) and y_max is not None
                            and y_avg is not None and len(y_max) == len(x_data)
                            and len(y_avg) == len(x_data)):
                        ax.plot(x_data, y_data, linewidth=0, color=color)
                        ax.plot(x_data, y_max, linewidth=0, color=color)
                        ax.fill_between(x_data, y_data, y_max, alpha=0.6, color=color, linewidth=0)
                        ax.plot(x_data, y_avg, linewidth=0.7, color=color)
                    else:
                        ax.plot(x_data, y_data, linewidth=0.7, color=color)
            ax.relim()
            ax.autoscale_view(scalex=False, scaley=True)
            ax.set_xlim(baseline[0], baseline[1], auto=False)
            ax.set_autoscalex_on(False)
            ax.tick_params(axis='x', labelsize=fs)
            ax.tick_params(axis='y', labelsize=fs)
            ax.set_facecolor('#f5f5f5')
            main_x_formatter = main_ax.xaxis.get_major_formatter()
            if isinstance(main_x_formatter, NanosecondDateFormatter):
                # Give the minimap its OWN nice locator over the fixed baseline
                # range, and link the formatter to it so the label precision
                # tracks the minimap's span (e.g. HH:MM for a few minutes). The
                # minimap xlim is pinned to the draw window, so these ticks are
                # stable: they describe the queried time range and do not change
                # when the main plot is panned/zoomed.
                #
                # Previously the minimap reused the main view's label_segments
                # with matplotlib's default locator, so every tick collapsed to
                # the hour field (e.g. "15").
                # Same tick target as the main axis, so both stay in step when
                # the user configures the number of ticks.
                mm_locator = NiceNanosecondLocator(
                    ax_idx=0, offset_lut=None,
                    target_ticks=getattr(main_ax.xaxis, '_ipl_tick_number', 6))
                clone = NanosecondDateFormatter(
                    ax_idx=0,
                    label_segments=main_x_formatter.label_segments,
                    postfix_end=main_x_formatter.postfix_end,
                    postfix_start=main_x_formatter.postfix_start,
                    offset_lut=None,
                    roundh=main_x_formatter._round,
                    nice_locator=mm_locator,
                )
                ax.xaxis.set_major_locator(mm_locator)
                ax.xaxis.set_major_formatter(clone)
            elif isinstance(main_x_formatter, ExponentScalarFormatter) and \
                    is_time_label(main_ax.get_xlabel()):
                # Relative-time axis (main x label is 'Time'): give the minimap
                # its own RelativeTimeLocator + ExponentScalarFormatter over the
                # pinned baseline so ticks read as human-readable durations (1d,
                # 12h, 36ms250us, ...). The minimap axis doesn't carry the 'Time'
                # label, so force the time behaviour explicitly. A non-time
                # relative axis falls through to the default numeric formatter.
                ax.xaxis.set_major_locator(RelativeTimeLocator(force_time=True))
                ax.xaxis.set_major_formatter(ExponentScalarFormatter(is_time=True))

            # The UTC prefix is rendered as the x-axis offset text; size it too
            # (after the formatter is set), like the main axis does
            # (matplotlibCanvas.process_ipl_axis_params).
            ax.xaxis.get_offset_text().set_fontsize(fs)

            rect = Rectangle((baseline[0], 0), baseline[1] - baseline[0], 1,
                             facecolor='#ffb300', edgecolor='#e65100',
                             alpha=0.5, linewidth=2.0, zorder=10,
                             transform=ax.get_xaxis_transform(), clip_on=False)
            ax.add_patch(rect)
            self._minimap_viewport_patch = rect
            self._minimap_axes = ax
            self._minimap_figure.tight_layout()
            self._minimap_signature = signature

        if self._minimap_connected_main_ax is not main_ax:
            self._disconnect_minimap_xlim()
            update_rect = functools.partial(self._viewlims_update_rect, self._minimap_viewport_patch)
            self._minimap_xlim_cid = main_ax.callbacks.connect('xlim_changed', update_rect)
            self._minimap_ylim_cid = main_ax.callbacks.connect('ylim_changed', update_rect)
            self._minimap_connected_main_ax = main_ax
        self._viewlims_update_rect(self._minimap_viewport_patch, main_ax)

    def _viewlims_update_rect(self, rect, ax):
        x_lo, x_hi = self._parser.get_oaw_axis_limits(ax, 0)
        if x_lo is None or x_hi is None:
            return
        canvas = self.get_canvas()
        baseline = canvas.get_minimap_baseline() if canvas is not None else None
        if baseline is not None:
            full_span = baseline[1] - baseline[0]
            shows_full = full_span > 0 and abs(x_lo - baseline[0]) < full_span * 1e-6 and abs(x_hi - baseline[1]) < full_span * 1e-6
            rect.set_visible(not shows_full)
        rect.set_x(x_lo)
        rect.set_width(x_hi - x_lo)
        self._minimap_renderer.draw_idle()

    def _is_signal_visible(self, signal) -> bool:
        """Check if signal is visible (Matplotlib implementation)."""
        if not hasattr(signal, 'lines') or not signal.lines:
            return True  # Assume visible if no lines yet (signal being processed)
        try:
            lines = signal.lines
            if isinstance(lines[0], Collection):
                return lines[0][0].get_visible()  # visibility min data
            else:
                return lines[0].get_visible()
        except (IndexError, AttributeError):
            return True

    def draw_marker_label(self, marker_name, plot_id, signal_uid, xy, color, modify):
        signal, ax = self.get_signal_marker(plot_id, signal_uid)  # type: MPLAxes

        # Creation of the annotations
        if isinstance(signal, SignalXY) and ax:
            if not modify:
                # Create and draw marker
                x = self._parser.transform_value(ax, 0, xy[0], inverse=True)
                y = xy[1]
                ax.annotate(text=marker_name,
                            xy=(x, y),
                            xytext=(x, y),
                            bbox=dict(boxstyle="round,pad=0.3", edgecolor="black", facecolor=color))

                # Get marker row
                row = self.get_marker_row(signal, marker_name)

                # Set marker visibility
                signal.markers_list[row].visible = True
                signal.markers_list[row].color = color
                self._parser.figure.canvas.draw()
            else:
                # Change marker color when it is visible
                annotations = [child for child in ax.get_children() if isinstance(child, plt.Annotation)]
                if annotations:
                    for annotation in annotations:
                        if annotation.get_text() == marker_name:
                            # Set new color property
                            annotation.set_bbox(dict(boxstyle="round,pad=0.3", edgecolor="black", facecolor=color))
                            # Get marker row
                            row = self.get_marker_row(signal, marker_name)
                            signal.markers_list[row].color = color
                            self._parser.figure.canvas.draw()

    def delete_marker_label(self, marker_name, plot_id, signal_uid, delete):
        signal, ax = self.get_signal_marker(plot_id, signal_uid)

        # Get annotations from the axis
        annotations = [child for child in ax.get_children() if isinstance(child, plt.Annotation)]

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
                if annotation.get_text() == marker_name:
                    annotation.remove()
                    self._parser.figure.canvas.draw()
                    return

    def _get_plot_by_id(self, plot_id):
        return self._plot_at_canvas_position(plot_id)

    def _get_impl_plot_for_plot(self, plot):
        """Return the matplotlib Axes hosting *plot* (first matching axes)."""
        for ax in self._parser.figure.axes:
            ci = self._parser._impl_plot_cache_table.get_cache_item(ax)
            if ci and hasattr(ci, 'plot') and ci.plot() is plot:
                return ax
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
        self.render_deferred()

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
        self.render_deferred()

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
        self.render_deferred()

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
        self.render_deferred()

    def toggle_ruler_label(self, name, plot_id, show_label, show_val_label):
        plot = self._get_plot_by_id(plot_id)
        if plot is None:
            return
        ruler = plot.get_ruler(name)
        if ruler:
            ruler.show_label = show_label
            ruler.show_val_label = show_val_label
        # Unlike visibility or colour, labels are decluttered per plot: each plot
        # the ruler spans has its own row, so this stays on that plot alone.
        for r in self._parser.get_rulers(self._get_impl_plot_for_plot(plot)):
            if r.name == name:
                r.set_show_label(show_label)
                r.set_show_val_label(show_val_label)
        self.render_deferred()

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
        self._ruler_window.set_canvas_columns(len(self._parser.canvas.plots))
        with self._ruler_window.bulk_update():
            for entry in self._ruler_window_rows(impl_plot, x, (x_abs, y_abs)):
                self._ruler_window.add_row(name, entry['plot_id'], entry['xy'], ruler.color,
                                            visible=True, is_date=entry['is_date'],
                                            signal_values=entry['signal_values'],
                                            x_is_time=entry['x_is_time'])
        if not self._ruler_window.isVisible():
            self._ruler_window.show()
        # Do not steal focus from the canvas.
        self.window().activateWindow()

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
        if existing is not None and self._preview_ruler_ax is impl_plot:
            existing.abs_x = self._parser.transform_value(impl_plot, 0, x)
            existing.abs_y = self._parser.transform_value(impl_plot, 1, y)
            existing.xy = (x, y)
            existing.refresh_labels()
            self._blit_preview()
            return
        previous_background = self._preview_background
        self._clear_preview_ruler()
        ruler = self._parser.add_ruler(impl_plot, self._PREVIEW_RULER_NAME,
                                        x, y, ident['color'], animated=True)
        ruler.set_label_text(ident['name'])
        self._preview_ruler_ax = impl_plot
        self._preview_ruler_identity = ident
        if self._preview_cid_draw is None:
            self._preview_cid_draw = self._mpl_renderer.mpl_connect(
                'draw_event', self._on_draw_capture_bg)
        # Reuse the background when moving to another plot: capturing it again
        # here would take in the ghost just drawn on the plot being left.
        self._preview_background = previous_background or self._mpl_renderer.copy_from_bbox(
            self._parser.figure.bbox)
        self._blit_preview()

    def _on_draw_capture_bg(self, event):
        # A full redraw invalidates the blit background; recapture it.
        if self._preview_ruler_ax is None:
            return
        self._preview_background = self._mpl_renderer.copy_from_bbox(
            self._parser.figure.bbox)

    def _blit_preview(self):
        if self._preview_background is None or self._preview_ruler_ax is None:
            return
        self._mpl_renderer.restore_region(self._preview_background)
        for r in self._parser.get_rulers(self._preview_ruler_ax):
            if r.name == self._PREVIEW_RULER_NAME:
                r.draw_artists()
        self._mpl_renderer.blit(self._parser.figure.bbox)

    def _erase_preview_ruler(self):
        """Drop the ghost and paint over it from the blit background, which holds
        the plots without it; redraw them only when there is no background."""
        if self._preview_ruler_ax is None:
            return
        background = self._preview_background
        self._clear_preview_ruler()
        if background is None:
            self._mpl_renderer.draw_idle()
            return
        self._mpl_renderer.restore_region(background)
        self._mpl_renderer.blit(self._parser.figure.bbox)

    def _clear_preview_ruler(self):
        axes_with_preview = {r.ax for r in self._parser.get_rulers()
                             if r.name == self._PREVIEW_RULER_NAME}
        for ax in axes_with_preview:
            self._parser.remove_ruler(ax, self._PREVIEW_RULER_NAME)
        self._preview_ruler_ax = None
        self._preview_background = None
        if self._preview_cid_draw is not None:
            self._mpl_renderer.mpl_disconnect(self._preview_cid_draw)
            self._preview_cid_draw = None

    def _begin_ruler_drag(self, impl_plot, plot, ruler):
        """Grab a ruler for dragging; blit background is captured lazily on first motion."""
        self._clear_preview_ruler()
        self._ruler_drag = (impl_plot, plot, ruler)
        self._ruler_drag_bg = None
        # Shared-x echoes move in lockstep with the origin during the drag.
        self._ruler_drag_echoes = [r for r in self._parser.get_rulers()
                                   if r.name == ruler.name and r is not ruler]

    def _drag_ruler_to(self, x: float, y: float):
        """Move the grabbed ruler (and its shared-x echoes) to (x, y) and blit."""
        impl_plot, _, ruler = self._ruler_drag
        echoes = self._ruler_drag_echoes
        if self._ruler_drag_bg is None:
            # First motion: capture a clean background without the moving artists.
            ruler.set_visible(False)
            for echo in echoes:
                echo.set_visible(False)
            self._mpl_renderer.draw()
            self._ruler_drag_bg = self._mpl_renderer.copy_from_bbox(self._parser.figure.bbox)
            ruler.set_visible(True)
            for echo in echoes:
                echo.set_visible(True)
        x_abs = self._parser.transform_value(impl_plot, 0, x)
        y_abs = self._parser.transform_value(impl_plot, 1, y)
        ruler.abs_x = x_abs
        ruler.abs_y = y_abs
        ruler.xy = (x, y)
        ruler.refresh_labels()
        for echo in echoes:
            echo.abs_x = x_abs
            echo.abs_y = y_abs
            echo.xy = (self._parser.transform_value(echo.ax, 0, x_abs, inverse=True),
                       self._parser.transform_value(echo.ax, 1, y_abs, inverse=True))
            echo.refresh_labels()
        self._mpl_renderer.restore_region(self._ruler_drag_bg)
        ruler.draw_artists()
        for echo in echoes:
            echo.draw_artists()
        self._mpl_renderer.blit(self._parser.figure.bbox)

    def _end_ruler_drag(self):
        """Persist the dragged ruler's position to the model and the window. The
        model ruler and its window row live on the origin's plot, so route there
        even when a shared-x echo was the artist being dragged."""
        _, _, ruler = self._ruler_drag
        echoes = self._ruler_drag_echoes
        moved = self._ruler_drag_bg is not None
        self._ruler_drag = None
        self._ruler_drag_bg = None
        self._ruler_drag_echoes = []
        if not moved:
            return  # click without motion: nothing to persist
        origin = next((r for r in [ruler] + echoes if not r.is_echo), ruler)
        self._persist_ruler_position(origin)
        # The blit already shows the ruler where it was dropped.
        self.render_deferred()

    def _persist_ruler_position(self, origin):
        """Write an origin ruler's current (abs_x, y) to its model ruler and to
        its rows in the Ruler window, one per plot it spans."""
        ci = self._parser._impl_plot_cache_table.get_cache_item(origin.ax)
        origin_plot = ci.plot() if ci else None
        if origin_plot is None:
            return
        x_abs, y_abs = origin.abs_x, origin.abs_y
        core = origin_plot.get_ruler(origin.name)
        if core is not None:
            core.xy = (x_abs, y_abs)
        self._ruler_window.update_ruler_rows(
            origin.name, self._ruler_window_rows(origin.ax, origin.xy[0], (x_abs, y_abs)))

    def _find_ruler_near(self, impl_plot, event):
        rulers = self._parser.get_rulers(impl_plot)
        if not rulers or event.x is None or event.y is None:
            return None
        best = None
        best_dist = float('inf')
        renderer = self._mpl_renderer.get_renderer() if hasattr(self._mpl_renderer, 'get_renderer') else None
        for r in rulers:
            if r.name == self._PREVIEW_RULER_NAME:
                continue
            try:
                ruler_px = impl_plot.transData.transform((r.xy[0], r.xy[1]))
            except (ValueError, TypeError):
                continue
            dx = abs(ruler_px[0] - event.x)
            dy = abs(ruler_px[1] - event.y)
            d = None
            if dx <= self.PICK_RADIUS_PX and dy <= self.PICK_RADIUS_PX:
                d = float(np.hypot(dx, dy))
            else:
                name_label = getattr(r, 'name_label', None)
                if name_label is not None and name_label.get_visible():
                    try:
                        bbox = name_label.get_window_extent(renderer)
                        if bbox.contains(event.x, event.y):
                            d = 0.0
                    except (RuntimeError, AttributeError):
                        pass
            if d is not None and d < best_dist:
                best_dist = d
                best = r
        return best

    def _repaint_rulers_from_canvas(self):
        self._clear_preview_ruler()
        self._preview_ruler_identity = None
        self._ruler_window.clear_info()
        canvas = self._parser.canvas
        if not canvas:
            return
        self._ruler_window.set_canvas_columns(len(canvas.plots))
        added = False
        with self._ruler_window.bulk_update():
            for col_idx, col in enumerate(canvas.plots):
                for row_idx, plot in enumerate(col):
                    if not plot or not getattr(plot, 'rulers', None):
                        continue
                    impl_plot = self._get_impl_plot_for_plot(plot)
                    if impl_plot is None:
                        continue
                    for ruler in plot.rulers:
                        x_view = self._parser.transform_value(impl_plot, 0, ruler.xy[0], inverse=True)
                        y_view = self._parser.transform_value(impl_plot, 1, ruler.xy[1], inverse=True)
                        self._parser.add_ruler(impl_plot, ruler.name, x_view, y_view, ruler.color)
                        self._parser.create_ruler_echoes(impl_plot, ruler.name,
                                                         ruler.xy[0], ruler.xy[1], ruler.color)
                        for entry in self._ruler_window_rows(impl_plot, x_view, ruler.xy):
                            self._ruler_window.add_row(ruler.name, entry['plot_id'], entry['xy'],
                                                        ruler.color, ruler.visible, entry['is_date'],
                                                        ruler.font_color, ruler.show_label,
                                                        ruler.show_val_label,
                                                        entry['signal_values'],
                                                        x_is_time=entry['x_is_time'])
                        self._apply_ruler_state(ruler)
                        added = True
                    self._ruler_window.count = max(self._ruler_window.count, len(plot.rulers))
        # Only re-draw when rulers were actually restored.
        if added:
            self.render()

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

                # Redraw canvas to reflect changes
                self._parser.figure.canvas.draw()

    def autoscale_all_y(self):
        """
            Autoscale the Y axis of all PlotXY instances in the figure and store the action for undo/redo
        """
        axes = self._parser.figure.axes
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

        # Redraw canvas to reflect changes
        self._parser.figure.canvas.draw()

    def _save_svg(self, filename: str):
        self._parser.figure.savefig(filename, format='svg', bbox_inches='tight')

    def set_mouse_mode(self, mode: str):
        super().set_mouse_mode(mode)

        if self._mpl_toolbar:
            self._mpl_toolbar.mode = _Mode.NONE
            self._parser.deactivate_cursor()
        else:
            return
        if self._mmode is None:
            return

        if mode != Canvas.MOUSE_MODE_RULER and self._preview_ruler_ax is not None:
            self._clear_preview_ruler()
            self._preview_ruler_identity = None
            self.render()

        if mode == Canvas.MOUSE_MODE_SELECT:
            self._mpl_toolbar.canvas.widgetlock.release(self._mpl_toolbar)
        elif mode == Canvas.MOUSE_MODE_CROSSHAIR:
            self._mpl_toolbar.canvas.widgetlock.release(self._mpl_toolbar)
            self._parser.activate_cursor()
        elif mode == Canvas.MOUSE_MODE_PAN:
            self._mpl_toolbar.pan()
        elif mode == Canvas.MOUSE_MODE_ZOOM:
            self._mpl_toolbar.zoom()
        elif mode == Canvas.MOUSE_MODE_MARKER:
            if not self._marker_window.isVisible():
                self._marker_window.show()
            elif self._marker_window.isMinimized():
                self._marker_window.showNormal()
            else:
                self._marker_window.raise_()
                self._marker_window.activateWindow()
        elif mode == Canvas.MOUSE_MODE_RULER:
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
        self.render()

    def redo(self):
        self._parser.redo()
        self.render()

    @Slot()
    def render(self):
        self._mpl_renderer.draw()

    def render_deferred(self):
        """Ask for a repaint instead of forcing one, so bursts of ruler changes
        fold into a single draw of the canvas."""
        self._mpl_renderer.draw_idle()

    def _flush_view(self):
        self.render()

    # custom event handlers
    def _mpl_draw_finish(self, event: DrawEvent):
        self._draw_call_counter += 1
        self._debug_log_event(event, f"Draw call {self._draw_call_counter}")

    def on_pick_legend(self, event):
        # Right-click on legend → open signal preferences
        if hasattr(event, 'mouseevent') and event.mouseevent.button == MouseButton.RIGHT:
            self._show_signal_prefs_menu(event.artist, event.mouseevent)
            return

        legend_line = event.artist
        ax_lines = self._parser.map_legend_to_ax.get(legend_line)
        if ax_lines is None:
            return
        self._toggle_legend_line(legend_line, ax_lines)

    def _show_signal_prefs_menu(self, legend_line, event):
        signal = self._parser._legend_signal_lut.get(legend_line)
        if signal is None:
            return
        menu = QMenu(self)
        menu.addAction("Signal Preferences",
                       lambda s=signal: self.openPlotPreferences.emit(s))
        menu.popup(event.guiEvent.globalPos())

    def _toggle_legend_line(self, legend_line, ax_lines):
        if isinstance(ax_lines, Collection):
            visible = True
            for ax_line in ax_lines:  # Envelope case
                visible = not ax_line.get_visible()
                ax_line.set_visible(visible)
        else:
            visible = not ax_lines.get_visible()
            ax_lines.set_visible(visible)
        legend_line.set_alpha(1.0 if visible else 0.2)
        self._parser.figure.canvas.draw()

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

    def _create_drag_preview(self, dy_offset, dx_offset=0.0):
        """Create/update preview line during drag for Matplotlib."""
        if self._drag_shift_signal is None or self._drag_shift_impl_plot is None:
            return

        signal = self._drag_shift_signal
        ax = self._drag_shift_impl_plot

        # Get the original line's data in display coordinates, then offset
        if not signal.lines:
            return

        original_line = signal.lines[0]
        if isinstance(original_line, typing.List):
            original_line = original_line[0]  # min data
        x_data, y_data = original_line.get_data()
        x_data_shifted = np.array(x_data) + dx_offset if abs(dx_offset) > 1e-10 else x_data
        y_data_shifted = np.array(y_data) + dy_offset

        # Remove old preview line if exists
        if self._drag_shift_preview_line is not None:
            try:
                for line in self._drag_shift_preview_line:
                    line.remove()
            except ValueError:
                pass

        # Create preview line with dashed style matching original color
        self._drag_shift_preview_line = ax.plot(
            x_data_shifted, y_data_shifted,
            linestyle='--',
            alpha=0.6,
            color=original_line.get_color(),
            linewidth=original_line.get_linewidth()
        )
        self._parser.figure.canvas.draw_idle()

    def _remove_drag_preview(self):
        """Remove preview line for Matplotlib."""
        if self._drag_shift_preview_line is not None:
            try:
                for line in self._drag_shift_preview_line:
                    line.remove()
            except ValueError:
                pass
            self._drag_shift_preview_line = None
            if self._parser and self._parser.figure:
                self._parser.figure.canvas.draw_idle()

    def _find_signal_at_event(self, event):
        """
        Find the nearest signal to the mouse event using pixel-distance calculation.
        Returns (signal, impl_plot, y_data_coord) or (None, None, None).
        """
        if event.inaxes is None:
            return None, None, None

        ax = event.inaxes
        ci = self._parser._impl_plot_cache_table.get_cache_item(ax)
        click_px = np.array([event.x, event.y])

        def get_line_pixel_data(line):
            """Transform a matplotlib line to pixel coords for distance calculation."""
            lines_to_check = line if isinstance(line, typing.List) else [line]
            for l in lines_to_check:
                xdata = l.get_xdata()
                ydata = l.get_ydata()
                if xdata is None or ydata is None or len(xdata) == 0:
                    continue
                try:
                    data_coords = np.column_stack([xdata, ydata])
                    pixel_coords = ax.transData.transform(data_coords)
                except (ValueError, TypeError):
                    continue
                return pixel_coords, click_px
            return None

        result = self._find_nearest_signal(ci, get_line_pixel_data)
        if result is not None:
            _, signal = result
            return signal, ax, event.ydata
        return None, None, None

    def _mpl_mouse_motion_handler(self, event: MouseEvent):
        """Handle mouse motion for ruler drag, ruler ghost preview and drag shift."""
        if self._ruler_drag is not None:
            impl_plot = self._ruler_drag[0]
            if (event.inaxes is impl_plot
                    and event.xdata is not None and event.ydata is not None):
                self._drag_ruler_to(event.xdata, event.ydata)
            return
        if self._mmode == Canvas.MOUSE_MODE_RULER:
            if event.inaxes is None or event.xdata is None or event.ydata is None:
                self._erase_preview_ruler()
                return
            ci = self._parser._impl_plot_cache_table.get_cache_item(event.inaxes)
            plot = ci.plot() if hasattr(ci, 'plot') else None
            if plot is None or isinstance(plot, (PlotContour, PlotContourWithSlider)):
                return
            # No ghost while hovering an existing ruler (a double-click there
            # grabs/ignores instead of creating).
            if self._find_ruler_near(event.inaxes, event) is not None:
                self._erase_preview_ruler()
                return
            self._show_preview_ruler(event.inaxes, event.xdata, event.ydata)
            return
        if not self._drag_shift_active or self._drag_shift_signal is None:
            return
        if event.inaxes != self._drag_shift_impl_plot:
            return
        if event.ydata is not None:
            self._update_drag_shift(event.ydata, event.xdata)

    def _mpl_mouse_press_handler(self, event: MouseEvent):
        """Additional callback to allow for focusing on one plot and returning home after double click"""
        self._debug_log_event(event, "Mouse pressed")

        on_legend = (event.inaxes and event.inaxes.get_legend()
                     and event.inaxes.get_legend().contains(event)[0])

        if (on_legend and event.button in (MouseButton.LEFT, MouseButton.RIGHT)
                and self._mmode in [Canvas.MOUSE_MODE_ZOOM, Canvas.MOUSE_MODE_PAN]):
            for legend_line, ax_lines in self._parser.map_legend_to_ax.items():
                contains, _ = legend_line.contains(event)
                if contains:
                    if getattr(self._mpl_toolbar, '_zoom_info', None) is not None:
                        self._mpl_toolbar.release_zoom(event)
                    if getattr(self._mpl_toolbar, '_pan_info', None) is not None:
                        self._mpl_toolbar.release_pan(event)
                    if event.button == MouseButton.LEFT:
                        self._toggle_legend_line(legend_line, ax_lines)
                    else:
                        self._show_signal_prefs_menu(legend_line, event)
                    return

        # If the mouse is over the legend it ignores it
        if on_legend:
            return

        if event.dblclick:
            if (self._mmode == Canvas.MOUSE_MODE_RULER
                    and event.button == MouseButton.LEFT
                    and event.inaxes is not None
                    and event.xdata is not None and event.ydata is not None):
                ci = self._parser._impl_plot_cache_table.get_cache_item(event.inaxes)
                plot = ci.plot() if hasattr(ci, 'plot') else None
                if plot is None or isinstance(plot, (PlotContour, PlotContourWithSlider)):
                    return
                # Double-clicking on an existing ruler must not stack a new one on top.
                if self._find_ruler_near(event.inaxes, event) is not None:
                    return
                # Double-click creates a ruler at the cursor.
                self._add_ruler_at(event.inaxes, plot, event.xdata, event.ydata)
                self.render()
                return
            if self._mmode in [Canvas.MOUSE_MODE_ZOOM, Canvas.MOUSE_MODE_PAN] and event.button == MouseButton.RIGHT:
                mpl_axes = event.inaxes
                if not isinstance(mpl_axes, MPLAxes):
                    return
                ci = self._parser._impl_plot_cache_table.get_cache_item(event.inaxes)
                plot = ci.plot()
                if not plot:
                    return

                # Stage a command to obtain original view limits
                self.stage_view_lim_cmd(event.inaxes)

                # Reset plot to original view limits
                original_limits = self._parser.get_plot_limits(mpl_axes)
                self._parser.set_plot_limits(original_limits)

                # Commit it.
                while len(self._staging_cmds):
                    self.commit_view_lim_cmd(event.inaxes)

                # Push it.
                while len(self._commitd_cmds):
                    self.push_view_lim_cmd()

                self.render()
            elif self._mmode == Canvas.MOUSE_MODE_MARKER and event.button == MouseButton.LEFT:
                mpl_axes = event.inaxes
                if not isinstance(mpl_axes, MPLAxes):
                    return
                ci = self._parser._impl_plot_cache_table.get_cache_item(event.inaxes)
                if not hasattr(ci, 'plot'):
                    return
                plot = ci.plot()
                x_value = event.xdata
                y_value = event.ydata

                # Markers can only be created if the property 'marker' is not None
                if mpl_axes.get_lines()[0].get_marker() != 'None':
                    # Check if the marker coordinates are correct and if the marker has not already been created
                    new_marker, marker_signal, label_line = self._parser.add_marker_scaled(mpl_axes, plot, x_value,
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
                            f"Cannot add marker {new_marker}: found {marker_signal} samples, but the maximum allowed"
                            f" is 100")
                else:
                    logger.warning("Markers must be enabled in the plot to create signal markers")
        else:
            if event.inaxes is None:
                return
            self._mouse_impl = event.inaxes
            ci = self._parser._impl_plot_cache_table.get_cache_item(event.inaxes)

            # Slider event
            if event.inaxes.get_label() == 'slider':
                self.stats(self.get_canvas())
                return

            if not hasattr(ci, 'plot'):
                return
            plot = ci.plot()
            if self._mmode == Canvas.MOUSE_MODE_RULER and event.button == MouseButton.LEFT:
                if isinstance(plot, (PlotContour, PlotContourWithSlider)):
                    logger.warning(f"Rulers are not supported for {type(plot).__name__}")
                    return
                if event.xdata is None or event.ydata is None:
                    return
                # Grab the nearest ruler to drag; empty space is a no-op.
                hit = self._find_ruler_near(event.inaxes, event)
                if hit is not None:
                    self._begin_ruler_drag(event.inaxes, plot, hit)
                return
            if event.button == MouseButton.RIGHT:
                if getattr(self._mpl_toolbar, '_zoom_info', None) is not None:
                    self._mpl_toolbar.release_zoom(event)
                if getattr(self._mpl_toolbar, '_pan_info', None) is not None:
                    self._mpl_toolbar.release_pan(event)
                self._show_autoscale_menu(event)
                return
            if self._mmode in [Canvas.MOUSE_MODE_ZOOM, Canvas.MOUSE_MODE_PAN]:
                # Stage a command to obtain original view limits
                # Disable Zoom and Pan for PlotContour and for PlotContourWithSlider
                if isinstance(plot, PlotContour) or isinstance(plot, PlotContourWithSlider):
                    return
                self.stage_view_lim_cmd(event.inaxes)
                # Zoom drags only draw the rubber band, so deferring is
                # pan-specific.
                if self._mmode == Canvas.MOUSE_MODE_PAN and event.button == MouseButton.LEFT:
                    self._parser.begin_interactive_pan()
                return

            # Handle drag shift in Select mode with left click - use native hit-testing
            if self._mmode == Canvas.MOUSE_MODE_SELECT and event.button == MouseButton.LEFT:
                signal, impl_plot, y_coord = self._find_signal_at_event(event)
                if signal is not None and signal.envelope:
                    logger.warning("Shift is not supported for envelope signals.")
                elif signal is not None:
                    # Check if X axis is datetime
                    try:
                        is_datetime = plot.axes[0].is_date
                    except (AttributeError, IndexError):
                        is_datetime = False
                    # Get x coordinate for pulse mode dx support
                    x_coord = event.xdata
                    self._start_drag_shift(impl_plot, signal, y_coord, is_datetime, start_x=x_coord)
                    return
                elif signal is None and event.inaxes is not None:
                    # Hit-test doesn't find envelope signals (no standard lines).
                    # Check if the plot has any envelope signals to inform the user.
                    ci = self._parser._impl_plot_cache_table.get_cache_item(event.inaxes)
                    if ci and hasattr(ci, 'signals') and ci.signals:
                        for sig_ref in ci.signals:
                            sig = sig_ref()
                            if sig is not None and getattr(sig, 'envelope', False):
                                logger.warning("Shift is not supported for envelope signals.")
                                break

            if event.button != MouseButton.LEFT:
                return
            if not plot:
                self._dist_calculator.reset()
                return
            if self._mmode == Canvas.MOUSE_MODE_DIST:
                if self._dist_calculator.plot1 is not None:
                    try:
                        is_date = plot.axes[0].is_date
                    except (AttributeError, IndexError):
                        is_date = False
                    x = self._parser.transform_value(event.inaxes, 0, event.xdata)
                    self._dist_calculator.set_dst(x, event.ydata, plot, ci.stack_key)
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
                    x = self._parser.transform_value(event.inaxes, 0, event.xdata)
                    self._dist_calculator.set_src(x, event.ydata, plot, ci.stack_key)

    def _mpl_mouse_release_handler(self, event: MouseEvent):
        self._debug_log_event(event, "Mouse released")
        if self._ruler_drag is not None:
            self._end_ruler_drag()
            return
        if event.dblclick:
            pass
        else:
            # Handle drag shift completion in Select mode
            if self._drag_shift_active and self._mmode == Canvas.MOUSE_MODE_SELECT:
                if event.ydata is not None:
                    self._end_drag_shift(event.ydata, event.xdata)
                else:
                    self._cancel_drag_shift()
                self.render()
                return

            if self._mmode in [Canvas.MOUSE_MODE_ZOOM, Canvas.MOUSE_MODE_PAN]:
                # Re-request the data once for the final pan window before the
                # view command is committed and statistics recomputed.
                self._parser.end_interactive_pan()
                # commit commands from staging.
                while len(self._staging_cmds):
                    self.commit_view_lim_cmd(self._mouse_impl)
                # push uncommitted changes onto the command stack.
                while len(self._commitd_cmds):
                    self.push_view_lim_cmd()
                # Update statistics
                self.stats(self.get_canvas())

    def _show_autoscale_menu(self, event: MouseEvent):
        if event.inaxes is None:
            return
        ci = self._parser._impl_plot_cache_table.get_cache_item(event.inaxes)
        autoscale_menu = QMenu(self)
        if self._mmode == Canvas.MOUSE_MODE_RULER and hasattr(ci, 'plot'):
            hit = self._find_ruler_near(event.inaxes, event)
            if hit is not None:
                plot_id = self._canvas_position_of(ci.plot()) or (1, 1)
                autoscale_menu.addAction(
                    f"Remove ruler {hit.name}",
                    lambda n=hit.name, p=plot_id: self._remove_ruler_from_menu(n, p))
                autoscale_menu.addSeparator()
        autoscale_menu.addAction("Autoscale", lambda: self.autoscale_y(event.inaxes))
        autoscale_menu.addAction("Autoscale All", self.autoscale_all_y)
        autoscale_menu.addAction("Reset zoom/pan", lambda: self.reset_plot_view(event.inaxes))
        if self._parser.canvas.focus_plot is None:
            autoscale_menu.addAction("Focus on plot", lambda: self._full_screen_mode_on(event.inaxes))
        else:
            autoscale_menu.addAction("Unfocus plot", self._full_screen_mode_off)
        autoscale_menu.addSeparator()
        if ci:
            autoscale_menu.addAction("Preferences",
                                     lambda: self.openPlotPreferences.emit(ci.plot()))
        nearest_signal, _, _ = self._find_signal_at_event(event)
        if nearest_signal:
            autoscale_menu.addAction("Signal Preferences",
                                     lambda s=nearest_signal: self.openPlotPreferences.emit(s))
        extender = getattr(self._parser, 'context_menu_extender', None)
        if callable(extender):
            try:
                extender(autoscale_menu, ci.plot() if ci else None)
            except Exception:
                logger.exception("context_menu_extender failed")
        autoscale_menu.popup(event.guiEvent.globalPos())

    def keyPressEvent(self, event: QKeyEvent):
        if event.text() == 'n':
            self.redo()
        elif event.text() == 'p':
            self.undo()

    def _debug_log_event(self, event: Event, msg: str):
        logger.debug(f"{self.__class__.__name__}({hex(id(self))}) {msg} | {event}")

    def dragEnterEvent(self, event):
        """
        This function will detect the drag enter event from the mouse on the main window
        """
        super(QtMatplotlibCanvas, self).dragEnterEvent(event)
        event.accept()

    def dragMoveEvent(self, event):
        """
        This function will detect the drag move event on the main window
        """
        x = event.position().x()
        y = event.position().y()
        height = self._parser.figure.bbox.height
        for axe in self._parser.figure.axes:
            if axe.bbox.x0 < x < axe.bbox.x1 and height - axe.bbox.y0 > y > height - axe.bbox.y1:
                event.accept()
                return
        event.ignore()

    def dropEvent(self, event):
        """
        This function will enable the drop file directly on to the
        main window. The file location will be stored in the self.filename
        """
        super(QtMatplotlibCanvas, self).dropEvent(event)
        plot = self.get_plot(event)

        row, col = self.get_position(plot)
        self.dropInfo.row = row
        self.dropInfo.col = col
        self.dropInfo.dragged_item = event.source().dragged_item
        self.dropSignal.emit(self.dropInfo)
        # row, col = self.get_position(plot)
        # new_data = pd.DataFrame([['codacuda', f"{dragged_item.key}", f'{col}.{row}']],
        #                       columns=['DS', 'Variable', 'Stack'])
        # self.parent().parent().parent().parent().sigCfgWidget._model.append_dataframe(new_data)
        # self.parent().parent().parent().parent().drawClicked()
        event.ignore()

    def get_plot(self, event):
        x = event.position().x()
        y = event.position().y()
        height = self._parser.figure.bbox.height
        for axe in self._parser.figure.axes:
            if axe.bbox.x0 < x < axe.bbox.x1 and height - axe.bbox.y0 > y > height - axe.bbox.y1:
                return self._parser._impl_plot_cache_table.get_cache_item(axe).plot()

    def get_position(self, plot):
        all_plots = self._parser.canvas.plots
        for column, col_plots in enumerate(all_plots):
            for row, row_plot in enumerate(col_plots):
                if row_plot.col == plot.col and row_plot.row == plot.row:
                    return row + 1, column + 1
