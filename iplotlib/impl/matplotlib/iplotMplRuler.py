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

        self.v_line = ax.axvline(xy[0], color=color, linewidth=lw, linestyle='--',
                                  animated=animated, zorder=20)
        self.h_line = ax.axhline(xy[1], color=color, linewidth=lw, linestyle='--',
                                  animated=animated, zorder=20)

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
        self.v_line.set_visible(visible)
        self.h_line.set_visible(visible)
        self.x_label.set_visible(visible)
        self.y_label.set_visible(visible)
        self.name_label.set_visible(visible)

    def draw_artists(self):
        for a in (self.v_line, self.h_line, self.x_label, self.y_label, self.name_label):
            self.ax.draw_artist(a)

    def remove(self):
        for artist in (self.v_line, self.h_line, self.x_label, self.y_label, self.name_label):
            try:
                artist.remove()
            except (ValueError, NotImplementedError):
                pass
