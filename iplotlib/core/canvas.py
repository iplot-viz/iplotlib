from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List

from iplotlib.core.persistence import JSONExporter
from iplotlib.core.plot import Plot


@dataclass
class Canvas(ABC):

    MOUSE_MODE_SELECT = "MM_SELECT"
    MOUSE_MODE_CROSSHAIR = 'MM_CROSSHAIR'
    MOUSE_MODE_PAN = 'MM_PAN'
    MOUSE_MODE_ZOOM = 'MM_ZOOM'

    """Number of rows in the grid. If specified the space for this nuber of rows should be reserved when rendering canvas since some 
    of the plots can be empty"""
    rows: int = 1
    """Number of columns in the grid. If specified the space for this number of columns should be reserved when rendering canvas since 
    some of the plots may be empty"""
    cols: int = 1
    """Canvas title - should be presented above the canvas grid centerer horizontally"""
    title: str = None


    font_size: int = None
    font_color: str = None

    """Default line style for drawing line plots. Possible values: 'solid','dashed','dotted' defaults to 'solid'"""
    line_style: str = None

    """Default line thickness for drawing line plots. Whether it is mapped to pixels or DPI independent points should 
    be canvas impementation dependent"""
    line_size: int = None

    """Marker type to display. If set a marker is drawn at every point of the data sample. Markers and lines can be drawn
    together and are not mutually exclusive. Supported types: 'x','o', None, default: None (no markers are drawn)"""
    marker: str = None

    """Marker size when drawn. Whether it is mapped to pixels or DPI independent points should be canvas 
    impementation dependent"""
    marker_size: int = None


    step: str = None

    hi_precision_data: bool = None
    dec_samples: int = 1000
    """Should the plot legend be shown"""
    legend: bool = True

    """Should plot grid be shown"""
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

    """Indicates that when we switch to full mode for a stacked plot we should put entire stacked plot in full mode or only one of the subplots"""
    full_mode_all_stack = True

    """Auto redraw canvas every X seconds"""
    auto_refresh: int = 0

    _type: str = None

    def __post_init__(self):
        self._type = self.__class__.__module__+'.'+self.__class__.__qualname__
        if self.plots is None:
            self.plots = [[] for _ in range(self.cols)]

    def add_plot(self, plot, col=0):
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

    def to_json(self):
        return JSONExporter().to_json(self)

    @staticmethod
    def from_json(json):
        return JSONExporter().from_json(json)

    def export_image(self, filename: str, **kwargs):
        pass
