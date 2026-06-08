"""
This module has a base class defined for all Qt canvas implementations.
"""

import os
from collections import defaultdict
from abc import abstractmethod
from contextlib import contextmanager
from typing import List, Tuple, Optional

import numpy as np
from PySide6.QtCore import QMetaObject, QSize, Qt, Signal, Slot
from PySide6.QtWidgets import QApplication, QWidget, QMessageBox
from iplotlib.core.signal import SignalXY
from iplotlib.core.canvas import Canvas
from iplotlib.core.plot import PlotXYWithSlider, PlotContourWithSlider
from iplotlib.core.command import IplotCommand
from iplotlib.core.drop_info import DropInfo
from iplotlib.core.commands.axes_range import IplotAxesRangeCmd
from iplotlib.core.impl_base import BackendParserBase
import iplotLogging.setupLogger as Sl
from iplotlib.qt.gui.IplotQtStatistics import IplotQtStatistics
from iplotlib.qt.gui.iplotQtMarker import IplotQtMarker
from iplotlib.qt.gui.iplotQtRuler import IplotQtRuler

logger = Sl.get_logger(__name__)


class IplotQtCanvas(QWidget):
    """
    Base class for all Qt related canvas implementations
    """
    cmdDone = Signal(IplotCommand)
    focusChanged = Signal()
    openPlotPreferences = Signal(object)
    signalShiftRequested = Signal(str, str, str, str, float, float, bool)
    # Unified shift signals (work for both drag and DIST)
    signalShiftApplied = Signal(str, float, float, str)  # (signal_uid, dx, dy, source)
    signalShiftUndone = Signal(str, float, float, str)   # (signal_uid, dx, dy, source)
    signalShiftPulseApplied = Signal(str, str, float, float, str)  # (signal_uid, pulse_id, dx, dy, source)
    signalShiftPulseUndone = Signal(str, str, float, float)  # (signal_uid, pulse_id, previous_dx, previous_dy)

    def __init__(self, parent=None, **kwargs):
        super().__init__(parent)
        self._mmode = None
        self._parser = None  # type: BackendParserBase
        self._staging_cmds = []  # type: List[IplotAxesRangeCmd]
        self._commitd_cmds = []  # type: List[IplotAxesRangeCmd]
        self.dropInfo = DropInfo()

        # Iplotlib markers
        self._marker_window = IplotQtMarker()
        self._marker_window.dropMarker.connect(self.draw_marker_label)
        self._marker_window.deleteMarker.connect(self.delete_marker_label)

        # Iplotlib rulers
        self._ruler_window = IplotQtRuler()
        self._ruler_window.deleteRuler.connect(self.delete_ruler)
        self._ruler_window.visibilityRuler.connect(self.toggle_ruler_visibility)
        self._ruler_window.colorRuler.connect(self.change_ruler_color)

        # Statistics
        self._stats_table = IplotQtStatistics()

        self.info_shared_x_dialog = False

        # Drag shift state
        self._drag_shift_active = False
        self._drag_shift_signal = None
        self._drag_shift_impl_plot = None
        self._drag_shift_start_x = None
        self._drag_shift_start_y = None
        self._drag_shift_is_datetime = False
        self._drag_shift_preview_line = None

    @abstractmethod
    def undo(self):
        """history: undo"""

    @abstractmethod
    def redo(self):
        """history: redo"""

    def unfocus_plot(self):
        """Remove focus from the current plot"""
        self._parser.set_focus_plot(None)
        self.info_shared_x_dialog = False

    def show_stats(self):
        if not self._stats_table.isVisible():
            self._stats_table.show()
        elif self._stats_table.isMinimized():
            self._stats_table.showNormal()
        else:
            self._stats_table.raise_()
            self._stats_table.activateWindow()

    def set_minimap(self, on: bool) -> None:
        if self._parser is None:
            return
        canvas = self.get_canvas()
        if canvas is None:
            return
        canvas.show_minimap = bool(on)
        if not on:
            canvas.snapshot_minimap_baseline(None, None)
        else:
            target = canvas.get_minimap_target_plot()
            if target is not None and target.axes:
                axis = target.axes[0]
                canvas.snapshot_minimap_baseline(axis.original_begin, axis.original_end)
        with self.view_retainer():
            self.refresh()

    def drop_history(self):
        """history: clear undo history. after this, can no longer undo"""
        return self._parser.drop_history()

    def can_undo(self) -> bool:
        return self._parser._hm.can_undo()

    def can_redo(self) -> bool:
        return self._parser._hm.can_redo()

    def get_next_undo_cmd_name(self) -> str:
        return self._parser._hm.get_next_undo_cmd_name()

    def get_next_redo_cmd_name(self) -> str:
        return self._parser._hm.get_next_redo_cmd_name()

    def draw_in_main_thread(self):
        import shiboken6
        if shiboken6.isValid(self):
            QMetaObject.invokeMethod(self, "flush_draw_queue")

    @Slot()
    def flush_draw_queue(self):
        if self._parser:
            self._parser.process_work_queue()

    @abstractmethod
    def refresh(self):
        """Refresh the canvas from the current iplotlib.core.Canvas instance.
        """
        self.set_canvas(self.get_canvas())

    @abstractmethod
    def reset(self):
        """Remove the current iplotlib.core.Canvas instance.
            Typical implementation would be a call to set_canvas with None argument.
        """
        self.set_canvas(None)

    @abstractmethod
    def set_mouse_mode(self, mode: str):
        """Sets mouse mode of this canvas"""
        logger.debug(f"MMode change {self._mmode} -> {mode}")
        self._mmode = mode
        if self._mmode == Canvas.MOUSE_MODE_CROSSHAIR:
            self.setCursor(Qt.CursorShape.CrossCursor)
        elif self._mmode == Canvas.MOUSE_MODE_DIST:
            self.setCursor(Qt.CursorShape.CrossCursor)
        elif self._mmode == Canvas.MOUSE_MODE_MARKER:
            self.setCursor(Qt.CursorShape.CrossCursor)
        elif self._mmode == Canvas.MOUSE_MODE_RULER:
            self.setCursor(Qt.CursorShape.CrossCursor)
        elif self._mmode == Canvas.MOUSE_MODE_PAN:
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        elif self._mmode == Canvas.MOUSE_MODE_SELECT:
            self.setCursor(Qt.CursorShape.ArrowCursor)
        elif self._mmode == Canvas.MOUSE_MODE_ZOOM:
            self.setCursor(Qt.CursorShape.CrossCursor)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)

    def save_canvas_image(self, filename: str):
        """Save the canvas to an image file (PNG, JPEG, or SVG)."""
        ext = os.path.splitext(filename)[1].lower()
        if ext == '.svg':
            self._save_svg(filename)
        else:
            pixmap = self.grab()
            if not pixmap.save(filename):
                logger.error(f"Failed to save image: {filename}")
                return
        logger.info(f"Screenshot saved: {os.path.abspath(filename)}")

    def _save_svg(self, filename: str):
        """SVG export — subclasses override for vector output."""
        from PySide6.QtSvg import QSvgGenerator
        from PySide6.QtGui import QPainter
        generator = QSvgGenerator()
        generator.setFileName(filename)
        generator.setSize(self.size())
        generator.setViewBox(self.rect())
        painter = QPainter(generator)
        self.render(painter)
        painter.end()

    @abstractmethod
    def set_canvas(self, canvas: Canvas):
        """Sets new version of iplotlib canvas and redraw"""
        if not canvas:
            return

        # Check if plots share time axis
        ranges = []
        plot_stack = []

        if not self._parser._pm.get_value(canvas, 'shared_x_axis'):
            self.info_shared_x_dialog = False
        else:
            if self.info_shared_x_dialog:
                return
            self.info_shared_x_dialog = True
            relative = False
            for row_idx, col in enumerate(canvas.plots, start=1):
                for col_idx, plot in enumerate(col, start=1):
                    if plot:
                        axis = plot.axes[0]
                        if not axis.is_date and not isinstance(plot, PlotXYWithSlider):
                            relative = True
                        ranges.append((axis.original_begin, axis.original_end))
                        plot_stack.append(f"{col_idx}.{row_idx}")

            dict_ranges = defaultdict(list)
            # Need to differentiate if it is absolute or relative
            if relative:
                max_diff_ns = self._parser._pm.get_value(canvas, 'max_diff')
            else:
                max_diff_ns = self._parser._pm.get_value(canvas, 'max_diff') * 1e9
            for idx, uniq_range in enumerate(ranges):
                if uniq_range == ranges[0]:
                    dict_ranges[uniq_range].append(plot_stack[idx])
                # If the difference of the ranges is less than 1 second, we consider them equal
                elif abs(uniq_range[0] - ranges[0][0]) <= max_diff_ns and abs(
                        uniq_range[1] - ranges[0][1]) <= max_diff_ns:
                    dict_ranges[ranges[0]].append(plot_stack[idx])
                else:
                    dict_ranges[uniq_range].append(plot_stack[idx])

            # If there is more than one element in the dictionary it means that there is more than one time
            # range
            if len(dict_ranges) > 1:
                box = QMessageBox()
                box.setIcon(QMessageBox.Icon.Information)
                message = "There are plots with different time range:\n"
                for i, stacks in enumerate(dict_ranges.values(), start=1):
                    plots_str = ", ".join(stacks)
                    message += f"Time range {i}: Plots {plots_str}\n"

                box.setText(message)
                box.exec_()

    def get_canvas(self) -> Canvas:
        """Gets current iplotlib canvas"""
        return self._parser.canvas

    def _canvas_position_of(self, plot) -> Optional[Tuple[int, int]]:
        """1-indexed (row, col) position of *plot* in the canvas grid, or None."""
        canvas = self._parser.canvas if self._parser else None
        if canvas is None:
            return None
        for col_idx, col in enumerate(canvas.plots):
            for row_idx, p in enumerate(col):
                if p is plot:
                    return (row_idx + 1, col_idx + 1)
        return None

    def _plot_at_canvas_position(self, plot_id) -> Optional[object]:
        """Plot at the 1-indexed (row, col) position, or None."""
        canvas = self._parser.canvas if self._parser else None
        if canvas is None or plot_id is None:
            return None
        target_row = plot_id[0] - 1
        target_col = plot_id[1] - 1
        if 0 <= target_col < len(canvas.plots):
            col = canvas.plots[target_col]
            if 0 <= target_row < len(col):
                return col[target_row]
        return None

    @abstractmethod
    def draw_marker_label(self, marker_name, plot_id, signal_uid, xy, color, modify):
        """"""

    @abstractmethod
    def delete_marker_label(self, marker_name, plot_id, signal_uid, delete):
        """"""

    @abstractmethod
    def delete_ruler(self, name, plot_id, persist):
        """Remove a ruler from the backend (and from Plot.rulers when persist=True)."""

    @abstractmethod
    def toggle_ruler_visibility(self, name, plot_id, visible):
        """Toggle a ruler's visibility on the backend."""

    @abstractmethod
    def change_ruler_color(self, name, plot_id, color):
        """Update a ruler's color on the backend."""

    def get_signals(self, canvas: Canvas):
        signal_list = []
        for row_idx, col in enumerate(canvas.plots, start=1):
            for col_idx, plot in enumerate(col, start=1):
                if plot:
                    for stack in plot.signals.values():
                        for signal in stack:
                            if isinstance(signal, SignalXY):
                                signal_list.append(signal)
        return signal_list

    def get_visible_plot_signals(self, plot) -> List[SignalXY]:
        """
        Get visible signals from a specific plot.
        Only returns SignalXY instances that are not hidden via legend.

        Args:
            plot: The plot to get signals from

        Returns:
            List of visible SignalXY instances
        """
        visible_signals = []
        if not plot or not hasattr(plot, 'signals'):
            return visible_signals

        for stack in plot.signals.values():
            for signal in stack:
                if isinstance(signal, SignalXY) and self._is_signal_visible(signal):
                    visible_signals.append(signal)
        return visible_signals

    @abstractmethod
    def _is_signal_visible(self, signal: SignalXY) -> bool:
        """
        Check if a signal is currently visible (not hidden via legend).
        Backend-specific implementations must override this method.

        Args:
            signal: The signal to check

        Returns:
            True if visible, False if hidden
        """

    def check_markers(self, canvas: Canvas):
        # Check if there are signals in the table that are no longer used
        markers_signals = self.get_signals(canvas)
        markers_signals_uid = [signal.uid for signal in markers_signals]

        for signal_uid in self._marker_window.get_markers_signal():
            if signal_uid not in markers_signals_uid:
                self._marker_window.remove_signal(signal_uid)
            else:
                # Check signal markers stack
                prev_stack = self._marker_window.get_stack(signal_uid)
                idx = markers_signals_uid.index(signal_uid)
                signal_element = markers_signals[idx]
                current_stack = signal_element.get_stack()
                if prev_stack != current_stack:
                    self._marker_window.refresh_stack(signal_element, current_stack)

    def get_signal_marker(self, plot_id, signal_uid):
        # Get signal and ax
        for idxCol, col in enumerate(self._parser.canvas.plots):
            for idxPlot, plot in enumerate(col):
                if not plot or [plot.col, plot.row] != plot_id:
                    continue
                # Get signal
                for signals in plot.signals.values():
                    for signal in signals:
                        if signal.uid == signal_uid and isinstance(signal, SignalXY):
                            ax = self._parser._signal_impl_plot_lut.get(signal.uid)
                            return signal, ax

    def get_marker_row(self, signal: SignalXY, marker_name: str):
        for i, marker in enumerate(signal.markers_list):
            if marker.name == marker_name:
                return i

    def stats(self, canvas: Canvas):
        """
        Computes and displays statistics for each signal in the current iplotlib canvas.
        Envelope data is used if available (min, max, mean arrays); otherwise, raw y-data is used.
        """
        info_stats = []
        signals = self.get_signals(canvas)
        if signals:
            for signal in signals:
                if (isinstance(signal,
                               SignalXY) and signal.status_info.result == 'Success' and signal.parent is not None):
                    impl_plot = self._parser._signal_impl_plot_lut.get(signal.uid)
                    if impl_plot is None:
                        continue
                    plot_id = self._canvas_position_of(signal.parent()) or (1, 1)
                    info_stats.append((signal, impl_plot, plot_id))
            self._stats_table.set_canvas_columns(len(canvas.plots))
            self._stats_table.fill_table(info_stats)

    @contextmanager
    def view_retainer(self):
        try:
            current_lims = self._parser.get_all_plot_limits()
            cmd = IplotAxesRangeCmd('_TmpPrefUpd_', current_lims, parser=self._parser)
            self._parser._hm.done(cmd)
            yield None
        finally:
            self._parser._hm.undo()

    def stage_view_lim_cmd(self, impl_plot):
        """stage a view command"""

        name = self._mmode[3:]
        old_limits = [self._parser.get_plot_limits(impl_plot)]
        cmd = IplotAxesRangeCmd(name.capitalize(), old_limits, parser=self._parser)
        self._staging_cmds.append(cmd)
        logger.debug(f"Staged {cmd}")

    def commit_view_lim_cmd(self, impl_plot):
        """commit a view command"""
        cmd = self._staging_cmds.pop()
        cmd.new_lim = [self._parser.get_plot_limits(impl_plot)]
        assert len(cmd.new_lim) == len(cmd.old_lim)

        # Check if any limit actually changed
        if any([lim1 != lim2 for lim1, lim2 in zip(cmd.old_lim, cmd.new_lim)]):
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            QApplication.processEvents()
            QApplication.restoreOverrideCursor()

            # Update new limits after data refresh.
            # Focus case: If focus plot is active and X-axis is shared, retrieve synchronized limits across
            # all shared plots.
            # if self._parser.canvas.focus_plot and self._parser.canvas.shared_x_axis:
            #     cmd.new_lim = self._parser.get_all_plot_limits_focus()
            # else:
            #     cmd.new_lim = self._parser.get_all_plot_limits()

            self._commitd_cmds.append(cmd)
            logger.debug(f"Committed {cmd}")
        else:
            logger.debug(f"Rejected {cmd}")

    def push_view_lim_cmd(self):
        """push a view command onto their history manager"""
        try:
            cmd = self._commitd_cmds.pop()
            self._parser._hm.done(cmd)
            logger.debug(f"Pushed {cmd}")
            self.cmdDone.emit(cmd)
        except IndexError:
            return

    def clean_canvas(self):
        """
        Resets the slider attribute of all PlotXYWithSlider instances in the canvas to None in preparation
        for serialization
        """
        for col in self.get_canvas().plots:
            for plot in col:
                if isinstance(plot, PlotXYWithSlider) or isinstance(plot, PlotContourWithSlider):
                    plot.clean_slider()

    def sizeHint(self):
        return QSize(900, 400)

    # ------------------------------------------------------------------
    # Nearest-line signal selection
    # ------------------------------------------------------------------

    PICK_RADIUS_PX = 10  # Max pixel distance to consider a hit

    @staticmethod
    def _min_distance_to_segments(pixel_coords: np.ndarray, click_px: np.ndarray) -> float:
        """Minimum distance from *click_px* to the polyline defined by *pixel_coords*.

        Both arrays are expected in pixel-equivalent (uniform scale) space.
        """
        if len(pixel_coords) == 1:
            return float(np.linalg.norm(pixel_coords[0] - click_px))
        seg_starts = pixel_coords[:-1]
        seg_ends = pixel_coords[1:]
        seg_vec = seg_ends - seg_starts
        pt_vec = click_px - seg_starts
        seg_len_sq = np.sum(seg_vec ** 2, axis=1)
        seg_len_sq = np.where(seg_len_sq < 1e-12, 1.0, seg_len_sq)
        t = np.clip(np.sum(pt_vec * seg_vec, axis=1) / seg_len_sq, 0.0, 1.0)
        projections = seg_starts + t[:, np.newaxis] * seg_vec
        return float(np.linalg.norm(projections - click_px, axis=1).min())

    def _find_nearest_signal(self, ci, get_line_pixel_data) -> Optional[Tuple]:
        """Find the nearest visible signal in *ci* using a backend-supplied callable.

        Args:
            ci: Cache item with a ``signals`` list of weak-refs.
            get_line_pixel_data: ``(line) -> (pixel_coords, click_px) | None``
                Backend-specific function that, given a matplotlib Line2D or
                pyqtgraph PlotDataItem, returns the line points and click
                position both in pixel-equivalent (uniform scale) space,
                or *None* to skip the line.

        Returns:
            ``(distance, signal)`` of the nearest hit within *PICK_RADIUS_PX*,
            or *None* if nothing was close enough.
        """
        if not ci or not hasattr(ci, 'signals') or not ci.signals:
            return None

        best = None  # (dist, signal)
        for signal_ref in ci.signals:
            signal = signal_ref()
            if signal is None or not isinstance(signal, SignalXY):
                continue
            if not self._is_signal_visible(signal):
                continue
            if not hasattr(signal, 'lines') or not signal.lines:
                continue

            for line in signal.lines:
                result = get_line_pixel_data(line)
                if result is None:
                    continue
                pixel_coords, click_px = result
                dist = self._min_distance_to_segments(pixel_coords, click_px)
                if dist <= self.PICK_RADIUS_PX and (best is None or dist < best[0]):
                    best = (dist, signal)
                break  # One line per signal is enough

        return best

    def _start_drag_shift(self, impl_plot, signal, start_y, is_datetime=False, start_x=None):
        """Initialize drag shift state. Called by backend after successful hit-test."""
        self._drag_shift_active = True
        self._drag_shift_signal = signal
        self._drag_shift_impl_plot = impl_plot
        self._drag_shift_start_x = start_x
        self._drag_shift_start_y = start_y
        self._drag_shift_is_datetime = is_datetime

    def _update_drag_shift(self, current_y, current_x=None):
        """Update drag preview during drag. Called by backend on mouse move."""
        if not self._drag_shift_active or self._drag_shift_signal is None:
            return
        dy_offset = current_y - self._drag_shift_start_y
        dx_offset = 0.0
        if not self._drag_shift_is_datetime and self._drag_shift_start_x is not None and current_x is not None:
            dx_offset = current_x - self._drag_shift_start_x
        self._create_drag_preview(dy_offset, dx_offset)

    def _end_drag_shift(self, end_y, end_x=None):
        """Finalize drag shift by storing offset in signal metadata and creating undo command."""
        if not self._drag_shift_active or self._drag_shift_signal is None:
            self._cancel_drag_shift()
            return

        dy = end_y - self._drag_shift_start_y

        # Calculate X offset (only if X is not datetime)
        dx = 0.0
        if not self._drag_shift_is_datetime and self._drag_shift_start_x is not None and end_x is not None:
            dx = end_x - self._drag_shift_start_x

        # Remove preview line first
        self._remove_drag_preview()

        # Only apply if there was meaningful movement
        if abs(dy) > 1e-10 or abs(dx) > 1e-10:
            from iplotlib.core.commands.shift import ShiftCommand

            signal = self._drag_shift_signal
            signal_uid = signal.uid

            # Detect pulse mode
            pulse_id = getattr(signal, 'pulse_nb', None)
            is_pulse_mode = pulse_id is not None and str(pulse_id).strip() != ''
            if is_pulse_mode:
                pulse_id = str(pulse_id)

            cmd = ShiftCommand(
                signal=signal,
                dx=dx,
                dy=dy,
                parser=self._parser,
                qt_canvas=self,
                is_pulse_isolation=is_pulse_mode,
                pulse_id=pulse_id if is_pulse_mode else None,
                source='drag'
            )

            # Apply offset via metadata (works for both modes now)
            previous_dx = getattr(signal, '_drag_shift_dx', 0.0)
            previous_dy = getattr(signal, '_drag_shift_dy', 0.0)
            if abs(dx) > 1e-10:
                signal._drag_shift_dx = previous_dx + dx
            if abs(dy) > 1e-10:
                signal._drag_shift_dy = previous_dy + dy
            self._parser.process_ipl_signal(signal)

            # Update legend to trigger draw_idle (for matplotlib)
            impl_plot = self._parser._signal_impl_plot_lut.get(signal_uid)
            plot = signal.parent() if hasattr(signal, 'parent') and callable(signal.parent) else None
            if impl_plot and plot and hasattr(self._parser, 'rebuild_legend'):
                self._parser.rebuild_legend(impl_plot, plot)

            # Register with history manager for undo/redo
            self._parser._hm.done(cmd)
            self.cmdDone.emit(cmd)

            # Emit signal for table update
            if is_pulse_mode:
                self.signalShiftPulseApplied.emit(signal_uid, pulse_id, dx, dy, 'drag')
            else:
                self.signalShiftApplied.emit(signal_uid, dx, dy, 'drag')

        self._reset_drag_shift_state()

    def _cancel_drag_shift(self):
        """Cancel drag shift without applying changes."""
        self._remove_drag_preview()
        self._reset_drag_shift_state()

    def _reset_drag_shift_state(self):
        """Reset all drag shift state variables."""
        self._drag_shift_active = False
        self._drag_shift_signal = None
        self._drag_shift_impl_plot = None
        self._drag_shift_start_x = None
        self._drag_shift_start_y = None
        self._drag_shift_is_datetime = False

    @abstractmethod
    def _create_drag_preview(self, dy_offset, dx_offset=0.0):
        """Create/update preview line during drag. Backend-specific."""
        pass

    @abstractmethod
    def _remove_drag_preview(self):
        """Remove preview line. Backend-specific."""
        pass

    def export_dict(self):
        self.clean_canvas()
        return self.get_canvas().to_dict() if self.get_canvas() else None

    def import_dict(self, input_dict):
        self.set_canvas(Canvas.from_dict(input_dict))

    def export_json(self):
        return self.get_canvas().to_json() if self.get_canvas() is not None else None

    def import_json(self, json):
        self.set_canvas(Canvas.from_json(json))
