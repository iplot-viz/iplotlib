"""Frozen crosshair (Ruler) anchored to a single Matplotlib Axes."""

from typing import List, Tuple

from matplotlib.axes import Axes as MPLAxes
from matplotlib.colors import to_hex, to_rgb

from iplotlib.core.ruler import contrast_text_color
from iplotlib.impl.matplotlib.iplotMultiCursor import get_values_from_line


class iplotMplRuler:
    """A frozen vertical + horizontal line pair anchored at (x, y) of an Axes."""

    # Same tolerance as the crosshair: a signal value label only shows when the
    # nearest sample is within this fraction of the visible X range.
    VAL_TOLERANCE = 0.05

    def __init__(self,
                 ax: MPLAxes,
                 name: str,
                 xy: Tuple[float, float],
                 color: str = "#FFFFFF",
                 font_color: str = "#FFFFFF",
                 lw: int = 1,
                 font_size: int = 8,
                 animated: bool = False,
                 value_lines: List = None,
                 is_echo: bool = False):
        self.ax = ax
        self.name = name
        self.xy = xy
        # Absolute (offset-free) X and Y; re-projected to the axis offsets on each
        # refresh so zoom/pan keep the ruler anchored to its data position.
        self.abs_x = xy[0]
        self.abs_y = xy[1]
        self.is_echo = is_echo
        self.color = color
        self.font_color = font_color
        self.font_size = font_size
        self.animated = animated
        self.visible = True
        self.show_label = True
        self.show_val_label = True

        self.v_line = ax.axvline(xy[0], color=color, linewidth=lw, linestyle='--',
                                  animated=animated, zorder=20, label='_RulerLine')
        self.h_line = ax.axhline(xy[1], color=color, linewidth=lw, linestyle='--',
                                  animated=animated, zorder=20, label='_RulerLine')

        bbox = dict(boxstyle="round", pad=0.1, fill=True, color=color)
        text_kwargs = dict(annotation_clip=False, clip_on=False, bbox=bbox,
                            color=font_color, fontsize=font_size, zorder=21,
                            animated=animated)

        self.x_label = ax.annotate(self._format_x(xy[0]), xy=(xy[0], 0),
                                    xycoords=('data', 'axes fraction'),
                                    verticalalignment="top", horizontalalignment="center",
                                    **text_kwargs)
        self.y_label = ax.annotate(f"{xy[1]:.6g}", xy=(0, xy[1]),
                                    xycoords=('axes fraction', 'data'),
                                    verticalalignment="center", horizontalalignment="right",
                                    **text_kwargs)
        # Name sits to the left of the vertical line so it never overlaps the value
        # label, which hangs to the right of the crossing.
        self.name_label = ax.annotate(name, xy=xy, xycoords='data',
                                       verticalalignment="bottom", horizontalalignment="right",
                                       **text_kwargs)

        # One value annotation per signal line, styled like the crosshair's.
        value_bbox = dict(boxstyle="round", pad=0.1, fill=True, color="green")
        value_kwargs = dict(annotation_clip=False, clip_on=False, bbox=value_bbox,
                             color=font_color, fontsize=font_size, zorder=21,
                             animated=animated)
        self.value_labels = []
        for lines in value_lines or []:
            annotation = ax.annotate("", xy=xy, xycoords='data',
                                      verticalalignment="top", horizontalalignment="left",
                                      **value_kwargs)
            annotation.line = lines
            self.value_labels.append(annotation)

        self._apply_text_colors()
        self._apply_view_visibility()

    def _text_color_for(self, background) -> str:
        """Label text colour: an explicit (non-default) font colour wins;
        otherwise auto-contrast with the label background so light rulers stay
        legible."""
        if self.font_color and to_hex(self.font_color).upper() != "#FFFFFF":
            return self.font_color
        r, g, b = (int(round(v * 255)) for v in to_rgb(background))
        return contrast_text_color((r, g, b))

    def _apply_text_colors(self):
        # Name/X/Y sit on the ruler colour; value tags sit on green.
        name_xy = self._text_color_for(self.color)
        for label in (self.x_label, self.y_label, self.name_label):
            label.set_color(name_xy)
        value = self._text_color_for("green")
        for label in self.value_labels:
            label.set_color(value)

    def _format_x(self, x: float) -> str:
        try:
            return self.ax.format_xdata(x)
        except Exception:
            return f"{x:.6g}"

    def refresh_labels(self):
        x, y = self.xy
        self.v_line.set_xdata([x, x])
        self.h_line.set_ydata([y, y])
        self.x_label.set_text(self._format_x(x))
        self.x_label.xy = (x, 0)
        self.x_label.set_position((x, 0))
        self.y_label.set_text(f"{y:.6g}")
        self.y_label.xy = (0, y)
        self.y_label.set_position((0, y))
        self._apply_view_visibility()

    def _apply_view_visibility(self):
        """Show X whenever it is in the time window; show the horizontal line and
        Y value only when y is in range. The name sits at the X·Y intersection, or
        drops to the bottom of the plot when y is out of range. Honours a hidden
        ruler."""
        if not self.visible:
            return
        x, y = self.xy
        xmin, xmax = sorted(self.ax.get_xlim())
        ymin, ymax = sorted(self.ax.get_ylim())
        in_x = xmin <= x <= xmax
        # A mirrored copy carries the owner's Y against an unrelated scale, so it
        # keeps the time line only.
        in_y = (ymin <= y <= ymax) and not self.is_echo
        self.v_line.set_visible(in_x)
        self.x_label.set_visible(in_x)
        self.h_line.set_visible(in_x and in_y)
        self.y_label.set_visible(in_x and in_y)
        self.name_label.set_visible(in_x and self.show_label)
        name_y = y if in_y else ymin
        self.name_label.xy = (x, name_y)
        self.name_label.set_position((x, name_y))
        self._refresh_value_labels(in_x, xmin, xmax, ymin, ymax)

    def _refresh_value_labels(self, in_x, xmin, xmax, ymin, ymax):
        """Pin each signal's value label to the sample nearest to the ruler X,
        following the crosshair behaviour (tolerance, hidden when off-signal)."""
        x = self.xy[0]
        for annotation in self.value_labels:
            lines = annotation.line
            shown = False
            if (self.show_val_label and in_x and lines
                    and lines[0].get_visible() and len(lines[0].get_xdata()) > 0):
                x_sig, y_sig = get_values_from_line(lines, x)
                if (abs(x - x_sig) < (xmax - xmin) * self.VAL_TOLERANCE
                        and ymin <= y_sig <= ymax):
                    annotation.xy = (x_sig, y_sig)
                    annotation.set_position((x_sig, y_sig))
                    # 6 significant digits, like the pyqtgraph labels and the ruler
                    # window cells; format_ydata's precision follows the tick step.
                    annotation.set_text(f"{y_sig:.6g}")
                    shown = True
            annotation.set_visible(shown)

    def set_label_text(self, text: str):
        self.name_label.set_text(text)

    def set_color(self, color: str):
        self.color = color
        self.v_line.set_color(color)
        self.h_line.set_color(color)
        for label in (self.x_label, self.y_label, self.name_label):
            label.get_bbox_patch().set_facecolor(color)
            label.get_bbox_patch().set_edgecolor(color)
        # A new background may flip the auto-contrast text colour.
        self._apply_text_colors()

    def set_font_color(self, color: str):
        self.font_color = color
        self._apply_text_colors()

    def set_show_label(self, show: bool):
        self.show_label = show
        if self.visible:
            self._apply_view_visibility()

    def set_show_val_label(self, show: bool):
        self.show_val_label = show
        if self.visible:
            self._apply_view_visibility()

    def set_visible(self, visible: bool):
        self.visible = visible
        for artist in (self.v_line, self.h_line, self.x_label, self.y_label,
                       self.name_label, *self.value_labels):
            artist.set_visible(visible)
        if visible:
            self._apply_view_visibility()

    def draw_artists(self):
        for a in (self.v_line, self.h_line, self.x_label, self.y_label,
                  self.name_label, *self.value_labels):
            self.ax.draw_artist(a)

    def remove(self):
        for artist in (self.v_line, self.h_line, self.x_label, self.y_label,
                       self.name_label, *self.value_labels):
            try:
                artist.remove()
            except (ValueError, NotImplementedError):
                pass
