from abc import ABC
from dataclasses import dataclass
from typing import List

from iplotlib.core.Plot import Plot


@dataclass
class Canvas(ABC):

    MOUSE_MODE_SELECT = "MM_SELECT"
    MOUSE_MODE_CROSSHAIR = 'MM_CROSSHAIR'
    MOUSE_MODE_PAN = 'MM_PAN'
    MOUSE_MODE_ZOOM = 'MM_ZOOM'

    rows: int = 1
    cols: int = 1
    title: str = None

    font_size: int = None
    font_color: str = None

    line_style: str = None
    line_size: int = None
    marker: str = None
    marker_size: int = None
    step: str = None

    dec_samples: int = 1000

    legend: bool = True
    grid: bool = False


    mouse_mode: str = MOUSE_MODE_SELECT
    plots: List[List[Plot]] = None

    crosshair_enabled: bool = False
    crosshair_color: str = "red"
    crosshair_line_width: int = 1
    crosshair_horizontal: bool = True
    crosshair_vertical: bool = True
    crosshair_per_plot: bool = False

    streaming: bool = False
    shared_x_axis: bool = False
    autoscale: bool = True

    _type:str = None

    def __post_init__(self):
        self._type = self.__class__.__module__+'.'+self.__class__.__qualname__
        if self.plots is None:
            self.plots = [[] for _ in range(self.cols)]

    def add_plot(self, plot, col=0, rowspan=1, colspan=1):
        if col >= len(self.plots):
            raise Exception("Cannot add plot to column {}: Canvas has only {} column(s)".format(col, len(self.plots)))
        if len(self.plots[col]) >= self.rows:
            raise Exception("Cannot add plot to column {}: Column is has {}/{} plots".format(col, len(self.plots[col]), self.rows))
        self.plots[col].append(plot)

    def set_mouse_mode(self, mode):
        self.mouse_mode = mode

    def enable_crosshair(self, color="red", linewidth=1, horizontal=False, vertical=True):
        self.crosshair_color = color
        self.crosshair_line_width = linewidth
        self.crosshair_enabled = True
        self.crosshair_vertical = vertical
        self.crosshair_horizontal = horizontal
        pass

    # def __repr__(self):
    #     return self.__class__.__name__ + "(" + str(self.plots) + ")"
