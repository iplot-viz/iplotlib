"""
This module has a base class defined for all Qt canvas implementations.
"""

from abc import abstractmethod
from contextlib import contextmanager
from typing import Collection, List

from PySide6.QtCore import QMetaObject, QSize, Qt, Signal, Slot, QPointF
from PySide6.QtWidgets import QApplication, QWidget, QMenu
from iplotlib.core.signal import SignalXY
from iplotlib.core.axis import RangeAxis
from iplotlib.core.canvas import Canvas
from iplotlib.core.plot import PlotXYWithSlider
from iplotlib.core.command import IplotCommand
from iplotlib.core.drop_info import DropInfo
from iplotlib.core.commands.axes_range import IplotAxesRangeCmd
from iplotlib.core.impl_base import BackendParserBase
import iplotLogging.setupLogger as Sl
from iplotlib.qt.gui.IplotQtStatistics import IplotQtStatistics

logger = Sl.get_logger(__name__)


class IplotQtCanvas(QWidget):
    """
    Base class for all Qt related canvas implementations
    """
    cmdDone = Signal(IplotCommand)

    def __init__(self, parent=None, **kwargs):
        super().__init__(parent)
        self._mmode = None
        self._parser = None  # type: BackendParserBase
        self._staging_cmds = []  # type: List[IplotAxesRangeCmd]
        self._commitd_cmds = []  # type: List[IplotAxesRangeCmd]
        self._refresh_original_ranges = True
        self.dropInfo = DropInfo()

        # Statistics
        self._stats_table = IplotQtStatistics()

    @abstractmethod
    def undo(self):
        """history: undo"""

    @abstractmethod
    def redo(self):
        """history: redo"""

    def show_stats(self):
        if not self._stats_table.isVisible():
            self._stats_table.show()
        elif self._stats_table.isMinimized():
            self._stats_table.showNormal()
        else:
            self._stats_table.raise_()
            self._stats_table.activateWindow()

    @abstractmethod
    def drop_history(self):
        """history: clear undo history. after this, can no longer undo"""

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
    def set_canvas(self, canvas):
        """Sets new version of iplotlib canvas and redraw"""

        # Do some post processing stuff here.
        # 1. Update the original begin, end for each axis.
        if not canvas:
            return
        if self._refresh_original_ranges:
            for col in canvas.plots:
                for plot in col:
                    if not plot:
                        continue
                    for ax_idx, axes in enumerate(plot.axes):
                        if isinstance(axes, Collection):
                            for axis in axes:
                                if isinstance(axis, RangeAxis):
                                    impl_plot = self._parser._axis_impl_plot_lut.get(id(axis))
                                    self._parser.update_range_axis(axis, ax_idx, impl_plot, which='original')
                                    self._parser.update_range_axis(axis, ax_idx, impl_plot, which='current')
                        elif isinstance(axes, RangeAxis) and axes.original_begin is None and axes.original_end is None:
                            axis = axes
                            impl_plot = self._parser._axis_impl_plot_lut.get(id(axis))

                            if isinstance(plot, PlotXYWithSlider):
                                if not isinstance(axis, RangeAxis) or impl_plot is None:
                                    continue
                                limits = plot.signals[1][0].z_data[0], plot.signals[1][0].z_data[-1]
                                axis.set_limits(*limits, 'original')
                            else:
                                self._parser.update_range_axis(axis, ax_idx, impl_plot, which='original')

    def get_canvas(self) -> Canvas:
        """Gets current iplotlib canvas"""
        return self._parser.canvas

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

    def stage_view_lim_cmd(self):
        """stage a view command"""

        name = self._mmode[3:]
        old_limits = self._parser.get_all_plot_limits()
        cmd = IplotAxesRangeCmd(name.capitalize(), old_limits, parser=self._parser)
        self._staging_cmds.append(cmd)
        logger.debug(f"Staged {cmd}")

    def commit_view_lim_cmd(self):
        """commit a view command"""
        cmd = self._staging_cmds.pop()
        cmd.new_lim = self._parser.get_all_plot_limits()  # New limits based on the current view
        assert len(cmd.new_lim) == len(cmd.old_lim)

        # Check if any limit actually changed
        if any([lim1 != lim2 for lim1, lim2 in zip(cmd.old_lim, cmd.new_lim)]):
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            QApplication.processEvents()
            self._parser.refresh_data()
            QApplication.restoreOverrideCursor()

            # Update new limits after data refresh.
            # Focus case: If focus plot is active and X-axis is shared, retrieve synchronized limits across
            # all shared plots.
            if self._parser.canvas.focus_plot and self._parser.canvas.shared_x_axis:
                cmd.new_lim = self._parser.get_all_plot_limits_focus()
            else:
                cmd.new_lim = self._parser.get_all_plot_limits()

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

    def _context_menu_for_plot(self, impl_plot, screen_pos, *, plot_specific_unfocus: bool = False):

        if isinstance(screen_pos, QPointF):
            screen_pos = screen_pos.toPoint()

        menu = QMenu(self)
        a_autoscale = menu.addAction("Autoscale")
        a_autoscale_all = menu.addAction("Autoscale All")

        focused_impl = getattr(self._parser, "_focus_plot", None)
        canvas_focus = getattr(self._parser.canvas, "focus_plot", None)

        if plot_specific_unfocus:
            if focused_impl is impl_plot:
                a_unfocus = menu.addAction("Unfocus on plot")
                a_focus = None
            else:
                a_focus = menu.addAction("Focus on plot")
                a_unfocus = None
        else:
            if (focused_impl is not None) or (canvas_focus is not None):
                a_unfocus = menu.addAction("Unfocus plot")
                a_focus = None
            else:
                a_focus = menu.addAction("Focus on plot")
                a_unfocus = None

        chosen = menu.exec(screen_pos)
        if chosen is None:
            return

        if chosen is a_autoscale:
            self.autoscale_y(impl_plot)
        elif chosen is a_autoscale_all:
            self.autoscale_all_y()
        elif a_focus is not None and chosen is a_focus:
            self._full_screen_mode_on(impl_plot)
        elif a_unfocus is not None and chosen is a_unfocus:
            self._full_screen_mode_off()

        self._parser.unstale_cache_items()
