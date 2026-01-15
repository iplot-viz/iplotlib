"""
This module has a base class defined for all Qt canvas implementations.
"""

from collections import defaultdict
from abc import abstractmethod
from contextlib import contextmanager
from typing import List

from PySide6.QtCore import QMetaObject, QSize, Qt, Signal, Slot
from PySide6.QtWidgets import QApplication, QWidget, QMessageBox
from iplotlib.core.signal import SignalXY
from iplotlib.core.canvas import Canvas
from iplotlib.core.plot import PlotXYWithSlider
from iplotlib.core.command import IplotCommand
from iplotlib.core.drop_info import DropInfo
from iplotlib.core.commands.axes_range import IplotAxesRangeCmd
from iplotlib.core.impl_base import BackendParserBase
import iplotLogging.setupLogger as Sl
from iplotlib.qt.gui.IplotQtStatistics import IplotQtStatistics
from iplotlib.qt.gui.iplotQtMarker import IplotQtMarker

logger = Sl.get_logger(__name__)


class IplotQtCanvas(QWidget):
    """
    Base class for all Qt related canvas implementations
    """
    cmdDone = Signal(IplotCommand)
    # Signal emitted when user requests to shift a signal: (signal_uid, dx, dy)
    signalShiftRequested = Signal(str, float, float)

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

        # Statistics
        self._stats_table = IplotQtStatistics()

        self.info_shared_x_dialog = False

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
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        elif self._mmode == Canvas.MOUSE_MODE_MARKER:
            self.setCursor(Qt.CursorShape.CrossCursor)
        elif self._mmode == Canvas.MOUSE_MODE_PAN:
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        elif self._mmode == Canvas.MOUSE_MODE_SELECT:
            self.setCursor(Qt.CursorShape.ArrowCursor)
        elif self._mmode == Canvas.MOUSE_MODE_ZOOM:
            self.setCursor(Qt.CursorShape.CrossCursor)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)

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

    @abstractmethod
    def draw_marker_label(self, marker_name, plot_id, signal_uid, xy, color, modify):
        """"""

    @abstractmethod
    def delete_marker_label(self, marker_name, plot_id, signal_uid, delete):
        """"""

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
                    info_stats.append((signal, impl_plot))
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
                if isinstance(plot, PlotXYWithSlider):
                    plot.clean_slider()

    def sizeHint(self):
        return QSize(900, 400)

    def export_dict(self):
        self.clean_canvas()
        return self.get_canvas().to_dict() if self.get_canvas() else None

    def import_dict(self, input_dict):
        self.set_canvas(Canvas.from_dict(input_dict))

    def export_json(self):
        return self.get_canvas().to_json() if self.get_canvas() is not None else None

    def import_json(self, json):
        self.set_canvas(Canvas.from_json(json))
