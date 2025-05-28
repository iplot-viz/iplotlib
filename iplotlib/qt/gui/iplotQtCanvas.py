"""
This module has a base class defined for all Qt canvas implementations.
"""

from abc import abstractmethod
from contextlib import contextmanager
from typing import Collection, List

from PySide6.QtCore import QMetaObject, QSize, Qt, Signal, Slot
from PySide6.QtWidgets import QApplication, QWidget
from iplotlib.core.axis import RangeAxis
from iplotlib.core.canvas import Canvas
from iplotlib.core.plot import PlotXYWithSlider
from iplotlib.core.command import IplotCommand
from iplotlib.core.drop_info import DropInfo
from iplotlib.core.commands.axes_range import IplotAxesRangeCmd
from iplotlib.core.impl_base import BackendParserBase
import iplotLogging.setupLogger as Sl

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

    @abstractmethod
    def undo(self):
        """history: undo"""

    @abstractmethod
    def redo(self):
        """history: redo"""

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
            self.setCursor(Qt.CrossCursor)
        elif self._mmode == Canvas.MOUSE_MODE_DIST:
            self.setCursor(Qt.PointingHandCursor)
        elif self._mmode == Canvas.MOUSE_MODE_MARKER:
            self.setCursor(Qt.CursorShape.CrossCursor)
        elif self._mmode == Canvas.MOUSE_MODE_PAN:
            self.setCursor(Qt.OpenHandCursor)
        elif self._mmode == Canvas.MOUSE_MODE_SELECT:
            self.setCursor(Qt.CrossCursor)
        elif self._mmode == Canvas.MOUSE_MODE_ZOOM:
            self.setCursor(Qt.CrossCursor)
        else:
            self.setCursor(Qt.ArrowCursor)

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

    @abstractmethod
    def get_canvas(self) -> Canvas:
        """Gets current iplotlib canvas"""

    @abstractmethod
    def stats(self, canvas: Canvas):
        """
        Computes and displays statistics for each signal in the current iplotlib canvas.
        Envelope data is used if available (min, max, mean arrays); otherwise, raw y-data is used.
        """

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
            QApplication.setOverrideCursor(Qt.WaitCursor)
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

    def sizeHint(self):
        return QSize(900, 400)

    def export_dict(self):
        return self.get_canvas().to_dict() if self.get_canvas() else None

    def import_dict(self, input_dict):
        self.set_canvas(Canvas.from_dict(input_dict))

    def export_json(self):
        return self.get_canvas().to_json() if self.get_canvas() is not None else None

    def import_json(self, json):
        self.set_canvas(Canvas.from_json(json))
