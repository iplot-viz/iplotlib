from abc import abstractmethod
from typing import Collection, List

from PySide2.QtCore import QSize
from PySide2.QtWidgets import QWidget
from iplotlib.core.axis import RangeAxis

from iplotlib.core.canvas import Canvas
from iplotlib.core.commands.axes_range import IplotAxesRangeCmd
from iplotlib.core.impl_base import BackendParserBase
import iplotLogging.setupLogger as sl

logger = sl.get_logger(__name__)

class IplotQtCanvas(QWidget):
    """
    Base class for all Qt related canvas implementaions
    """

    def __init__(self, parent=None, **kwargs):
        super().__init__(parent)
        self._mmode = None
        self._parser = None # type: BackendParserBase
        self._staging_cmds = [] #type: List[IplotAxesRangeCmd]
        self._commitd_cmds = [] #type: List[IplotAxesRangeCmd]
        self._refresh_original_ranges = True

    @abstractmethod
    def undo(self):
        """history: undo"""

    @abstractmethod
    def redo(self):
        """history: redo"""

    @abstractmethod
    def drop_history(self):
        """history: clear undo history. after this, can no longer undo"""

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

    @abstractmethod
    def set_canvas(self, canvas: Canvas):
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
                        elif isinstance(axes, RangeAxis):
                            axis = axes
                            impl_plot = self._parser._axis_impl_plot_lut.get(id(axis))
                            self._parser.update_range_axis(axis, ax_idx, impl_plot, which='original')

    @abstractmethod
    def get_canvas(self) -> Canvas:
        """Gets current iplotlib canvas"""

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
        cmd.new_lim = self._parser.get_all_plot_limits()
        assert len(cmd.new_lim) == len(cmd.old_lim)
        if any([lim1 != lim2 for lim1, lim2 in zip(cmd.old_lim, cmd.new_lim)]):
            self._commitd_cmds.append(cmd)
            logger.debug(f"Commited {cmd}")
        else:
            logger.debug(f"Rejected {cmd}")

    def push_view_lim_cmd(self):
        """push a view command onto their history manager"""
        try:
            cmd = self._commitd_cmds.pop()
            self._parser._hm.done(cmd)
            logger.debug(f"Pushed {cmd}")
            self._parser.refresh_data()
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
