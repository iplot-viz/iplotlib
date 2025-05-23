from typing import List
import numpy as np

from matplotlib.axes import Axes as MPLAxes
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.lines import Line2D
from matplotlib.text import Annotation
from matplotlib.widgets import Widget

from iplotlib.core import SignalContour
from iplotlib.core.impl_base import ImplementationPlotCacheTable
from iplotLogging import setupLogger

logger = setupLogger.get_logger(__name__)


class IplotMultiCursor(Widget):
    """
    Provide a vertical (default) and/or horizontal line cursor shared between
    multiple axes.

    For the cursor to remain responsive you must keep a reference to it.

    Parameters
    ----------
    canvas : `matplotlib.backend_bases.FigureCanvasQTAgg`
        The FigureCanvas that contains all the axes.

    axes : list of `matplotlib.axes.Axes`
        The `~.axes.Axes` to attach the cursor to.

    use_blit : bool, default: True
        Use blitting for faster drawing if supported by the backend.

    horiz_on : bool, default: False
        Whether to draw the horizontal line.

    vert_on: bool, default: True
        Whether to draw the vertical line.

    Other Parameters
    ----------------
    **line_props
        `.Line2D` properties that control the appearance of the lines.
        See also `~.Axes.axhline`.

    Examples
    --------
    See :doc:`/gallery/widgets/multicursor`.
    """

    def __init__(self, canvas: FigureCanvasQTAgg,
                 axes: List[MPLAxes],
                 x_label: bool = True,
                 y_label: bool = True,
                 val_label: bool = True,
                 use_blit: bool = True,
                 horiz_on: bool = False,
                 vert_on: bool = True,
                 val_tolerance: float = 0.05,
                 text_color: str = "white",
                 font_size: int = 8,
                 cache_table: ImplementationPlotCacheTable = None,
                 **line_props):

        self.canvas = canvas
        self.axes = axes
        self.horiz_on = horiz_on
        self.vert_on = vert_on
        self.x_label = x_label
        self.y_label = y_label
        self.value_label = val_label
        self.text_color = text_color
        self.font_size = font_size
        self._cache_table = cache_table
        # Tolerance for showing label with value on signal in %
        self.val_tolerance = val_tolerance

        x_min, x_max = axes[-1].get_xlim()
        y_min, y_max = axes[-1].get_ylim()
        x_mid = 0.5 * (x_min + x_max)
        y_mid = 0.5 * (y_min + y_max)

        self.use_blit = use_blit and self.canvas.supports_blit
        self.background = None
        self.need_clear = False

        if self.use_blit:
            line_props['animated'] = True

        self.x_arrows = []
        self.y_arrows = []
        self.value_annotations = []
        self.v_lines = []

        if vert_on:
            for ax in axes:
                y_min, y_max = ax.get_ybound()
                line = Line2D([x_mid, x_mid], [y_min, y_max], **line_props, label="CrossY")
                ax.add_artist(line)
                self.v_lines.append(line)

        self.h_lines = []
        if horiz_on:
            for ax in axes:
                x_min, x_max = ax.get_xbound()
                line = Line2D([x_min, x_max], [y_mid, y_mid], **line_props, label="CrossX")
                ax.add_artist(line)
                self.h_lines.append(line)

        axis_arrow_bbox_props = dict(boxstyle="round", pad=0.1, fill=True, color=line_props["color"])
        axis_arrow_props = dict(annotation_clip=False, clip_on=False, bbox=axis_arrow_bbox_props,
                                animated=self.use_blit, color=self.text_color, fontsize=self.font_size)

        value_arrow_bbox_props = dict(boxstyle="round", pad=0.1, fill=True, color="green")
        value_arrow_props = dict(annotation_clip=False, clip_on=False, bbox=value_arrow_bbox_props,
                                 animated=self.use_blit, color=self.text_color, fontsize=self.font_size)

        if self.x_label:
            for ax in axes:
                x_min, x_max = ax.get_xbound()
                y_min, y_max = ax.get_ybound()
                x_arrow = Annotation("", (x_min + (x_max - x_min) / 2, y_min),
                                     verticalalignment="top", horizontalalignment="center", **axis_arrow_props)
                ax.add_artist(x_arrow)
                self.x_arrows.append(x_arrow)

        if self.y_label:
            for ax in axes:
                y_min, y_max = ax.get_ybound()
                x_min, x_max = ax.get_xbound()
                y_arrow = Annotation("", (x_min, y_min + (y_max - y_min) / 2),
                                     verticalalignment="center", horizontalalignment="right", **axis_arrow_props)
                ax.add_artist(y_arrow)
                self.y_arrows.append(y_arrow)

        if self.value_label:
            for ax in axes:
                ci = self._cache_table.get_cache_item(ax)
                if hasattr(ci, "signals") and ci.signals is not None:
                    for signal in ci.signals:
                        if isinstance(signal(), SignalContour):
                            continue
                        x_min, x_max = ax.get_xbound()
                        y_min, y_max = ax.get_ybound()

                        for line in signal().lines:
                            value_annotation = Annotation("",
                                                          xy=(x_min + (x_max - x_min) / 2, y_min + (y_max - y_min) / 2),
                                                          xycoords="data",  # xytext=(-200, 0),
                                                          verticalalignment="top", horizontalalignment="left",
                                                          **value_arrow_props)
                            value_annotation.line = line
                            ax.add_artist(value_annotation)
                            self.value_annotations.append(value_annotation)

        # Needs to be done for blitting to work. As it saves current background
        self.clear(None)

        """Connect events."""
        self._cid_motion = self.canvas.mpl_connect('motion_notify_event', self.on_move)
        self._cid_draw = self.canvas.mpl_connect('draw_event', self.clear)

    def clear(self, event):
        """Clear the cursor."""
        if self.ignore(event):
            return
        if self.use_blit:
            self.background = (
                self.canvas.copy_from_bbox(self.canvas.figure.bbox))
        for line in self.v_lines + self.h_lines:
            line.set_visible(False)

        # In matplotlib 3.6, for the MultiCursor object type,
        # the way of storing certain information such as background is changed.
        if hasattr(self, "_canvas_infos"):
            self.background = self._canvas_infos[self.canvas]["background"]
        # self.background = None
        for arrow in self.x_arrows + self.y_arrows:
            arrow.set_visible(False)

        for annotation in self.value_annotations:
            annotation.set_visible(False)

    def remove(self):
        for arrow in self.x_arrows + self.y_arrows:
            arrow.set_visible(False)

        for annotation in self.value_annotations:
            annotation.set_visible(False)

        for line in self.v_lines + self.h_lines:
            line.set_visible(False)

        self._update()
        self.disconnect()

    def on_move(self, event):
        def get_values_from_line(lines, x_value):
            if len(lines) == 1:
                x, y = lines[0].get_xdata(), lines[0].get_ydata()
            else:
                x = lines[0].get_xdata()
                y = (lines[0].get_ydata() + lines[1].get_ydata()) / 2
            ix = np.searchsorted(x, x_value)
            if ix == len(x):
                ix = len(x) - 1

            # Either return values at index or values at index-1
            if ix > 0 and abs(x[ix - 1] - x_value) < abs(x[ix] - x_value):
                ix = ix - 1
            return x[ix], y[ix]

        if self.ignore(event):
            return
        if event.inaxes is None:
            return
        if not self.canvas.widgetlock.available(self):
            return
        self.need_clear = True
        if self.vert_on:
            for line in self.v_lines:
                line.set_xdata([event.xdata])
                line.set_visible(True)

        if self.horiz_on:
            for line in self.h_lines:
                line.set_ydata([event.ydata])
                line.set_visible(True)

        if self.x_label:
            for arrow, ax in zip(self.x_arrows, self.axes):
                x_min, x_max = ax.get_xbound()
                if x_min < event.xdata < x_max and ax.get_xaxis().get_visible():
                    arrow.set_position((event.xdata, arrow.get_position()[1]))
                    arrow.set_text(ax.format_xdata(event.xdata))
                    arrow.set_visible(True)
                else:
                    arrow.set_visible(False)

        if self.y_label:
            for arrow, ax in zip(self.y_arrows, self.axes):
                y_min, y_max = ax.get_ybound()
                if y_min < event.ydata < y_max and ax.get_yaxis().get_visible():
                    arrow.set_position((arrow.get_position()[0], event.ydata))
                    arrow.set_text(ax.format_ydata(event.ydata))
                    arrow.set_visible(True)
                else:
                    arrow.set_visible(False)

        if self.value_label:
            for annotation in self.value_annotations:
                if hasattr(annotation, "line"):
                    annotation.set_visible(True)
                    line = annotation.line
                    if line is not None and line[0].get_visible() and len(line[0].get_xdata()) > 0:
                        ax = annotation.axes

                        xvalue = event.xdata
                        values = get_values_from_line(line, xvalue)
                        logger.debug(F"Found {values} for xvalue: {xvalue}")
                        dx = abs(xvalue - values[0])
                        x_min, x_max = ax.get_xbound()
                        if dx < (x_max - x_min) * self.val_tolerance:
                            annotation.set_position(values)
                            annotation.set_text(ax.format_ydata(values[1]))
                        else:
                            annotation.set_visible(False)
                    else:
                        annotation.set_visible(False)
                else:
                    annotation.set_visible(False)
        self._update()

    def _update(self):
        if self.use_blit:
            if self.background is not None:
                self.canvas.restore_region(self.background)

            if self.vert_on:
                for ax, line in zip(self.axes, self.v_lines):
                    ax.draw_artist(line)

            if self.horiz_on:
                for ax, line in zip(self.axes, self.h_lines):
                    ax.draw_artist(line)

            if self.x_label:
                for ax, arrow in zip(self.axes, self.x_arrows):
                    ax.draw_artist(arrow)

            if self.y_label:
                for ax, arrow in zip(self.axes, self.y_arrows):
                    ax.draw_artist(arrow)

            if self.value_label:
                for annotation in self.value_annotations:
                    annotation.axes.draw_artist(annotation)
            self.canvas.blit()
        else:
            self.canvas.draw_idle()

    def disconnect(self):
        """Disconnect events."""
        self.canvas.mpl_disconnect(self._cid_motion)
        self.canvas.mpl_disconnect(self._cid_draw)