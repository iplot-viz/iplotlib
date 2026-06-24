"""Frozen crosshair (Ruler) anchored to a single Matplotlib Axes."""

from typing import Tuple

from matplotlib.axes import Axes as MPLAxes


class iplotMplRuler:
    """A frozen vertical + horizontal line pair anchored at (x, y) of an Axes."""

    def __init__(self,
                 ax: MPLAxes,
                 name: str,
                 xy: Tuple[float, float],
                 color: str = "#FFFFFF",
                 lw: int = 1,
                 font_size: int = 8,
                 animated: bool = False):
        self.ax = ax
        self.name = name
        self.xy = xy
        self.color = color
        self.font_size = font_size
        self.animated = animated
        self.visible = True

        self.v_line = ax.axvline(xy[0], color=color, linewidth=lw, linestyle='--',
                                  animated=animated, zorder=20, label='_RulerLine')
        self.h_line = ax.axhline(xy[1], color=color, linewidth=lw, linestyle='--',
                                  animated=animated, zorder=20, label='_RulerLine')

        bbox = dict(boxstyle="round", pad=0.1, fill=True, color=color)
        text_kwargs = dict(annotation_clip=False, clip_on=False, bbox=bbox,
                            color="white", fontsize=font_size, zorder=21,
                            animated=animated)

        self.x_label = ax.annotate(self._format_x(xy[0]), xy=(xy[0], 0),
                                    xycoords=('data', 'axes fraction'),
                                    verticalalignment="top", horizontalalignment="center",
                                    **text_kwargs)
        self.y_label = ax.annotate(f"{xy[1]:.6g}", xy=(0, xy[1]),
                                    xycoords=('axes fraction', 'data'),
                                    verticalalignment="center", horizontalalignment="right",
                                    **text_kwargs)
        self.name_label = ax.annotate(name, xy=xy, xycoords='data',
                                       verticalalignment="bottom", horizontalalignment="left",
                                       **text_kwargs)

        self._apply_view_visibility()

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
        self.name_label.xy = (x, y)
        self.name_label.set_position((x, y))
        self._apply_view_visibility()

    def _apply_view_visibility(self):
        """Hide the whole crosshair when x leaves the time window, and the horizontal
        part when y is off-screen. Honours a user-hidden ruler."""
        if not self.visible:
            return
        x, y = self.xy
        xmin, xmax = sorted(self.ax.get_xlim())
        ymin, ymax = sorted(self.ax.get_ylim())
        in_x = xmin <= x <= xmax
        in_y = ymin <= y <= ymax
        self.v_line.set_visible(in_x)
        self.x_label.set_visible(in_x)
        self.h_line.set_visible(in_x and in_y)
        self.y_label.set_visible(in_x and in_y)
        self.name_label.set_visible(in_x and in_y)

    def set_label_text(self, text: str):
        self.name_label.set_text(text)

    def set_color(self, color: str):
        self.color = color
        self.v_line.set_color(color)
        self.h_line.set_color(color)
        for label in (self.x_label, self.y_label, self.name_label):
            label.get_bbox_patch().set_facecolor(color)
            label.get_bbox_patch().set_edgecolor(color)

    def set_visible(self, visible: bool):
        self.visible = visible
        for artist in (self.v_line, self.h_line, self.x_label, self.y_label, self.name_label):
            artist.set_visible(visible)
        if visible:
            self._apply_view_visibility()

    def draw_artists(self):
        for a in (self.v_line, self.h_line, self.x_label, self.y_label, self.name_label):
            self.ax.draw_artist(a)

    def remove(self):
        for artist in (self.v_line, self.h_line, self.x_label, self.y_label, self.name_label):
            try:
                artist.remove()
            except (ValueError, NotImplementedError):
                pass
