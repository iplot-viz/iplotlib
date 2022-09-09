"""
This module defines the `Canvas` object.
"""

from abc import ABC
from dataclasses import dataclass
from typing import List

from iplotlib.core.persistence import JSONExporter
from iplotlib.core.plot import Plot


@dataclass
class Canvas(ABC):
    """
    This class exposes visual properties of a canvas.
    """

    MOUSE_MODE_SELECT = "MM_SELECT"
    MOUSE_MODE_CROSSHAIR = 'MM_CROSSHAIR'
    MOUSE_MODE_PAN = 'MM_PAN'
    MOUSE_MODE_ZOOM = 'MM_ZOOM'
    MOUSE_MODE_DIST = 'MM_DIST'

    rows: int = 1 #: Number of rows in the grid. If specified the space for this nuber of rows should be reserved when rendering canvas since some of the plots can be empty
    cols: int = 1 #: Number of columns in the grid. If specified the space for this number of columns should be reserved when rendering canvas since some of the plots may be empty
    title: str = None #: Canvas title - should be shown above the canvas grid centered horizontally


    font_size: int = None #: default font size that will be cascaded across plots and axes of this canvas.
    font_color: str = None #: default font color that will be cascaded across plots and axes of this canvas.

    line_style: str = None #: default value for line plots - 'solid','dashed','dotted' defaults to 'solid'.
    line_size: int = None #: default line thickness for drawing line plots. Whether it is mapped to pixels or DPI independent points should be canvas impementation dependent

    marker: str = None #: default marker type to display. If set a marker is drawn at every point of the data sample. Markers and lines can be drawn together and are not mutually exclusive. Supported types: 'x','o', None, default: None (no markers are drawn)
    marker_size: int = None #: default marker size. Whether it is mapped to pixels or DPI independent points should be canvas impementation dependent

    step: str = None # default line style - 'post', 'mid', 'pre', 'None', defaults to 'None'.

    hi_precision_data: bool = False #: a boolean that suggests the data is sensitive to round off errors and requires special handling
    dec_samples: int = 1000 #: the default no. of samples for a data access fetch call.

    legend: bool = True #: a boolean that suggests the visibility of a plot legend box.
    grid: bool = False #: a boolean that suggests the visibility of a plot grid

    mouse_mode: str = MOUSE_MODE_SELECT #: the default mouse mode - 'select', 'zoom', 'pan', 'crosshair', defaults to 'select'

    plots: List[List[Plot]] = None #: A 22-level nested list of plots.

    crosshair_enabled: bool = False #: visibility of crosshair.
    crosshair_color: str = "red" #: color of the crosshair cursor lines.
    crosshair_line_width: int = 1 # width of the crosshair cursor lines.
    crosshair_horizontal: bool = True # visibility of the hori
    crosshair_vertical: bool = True
    crosshair_per_plot: bool = False

    streaming: bool = False
    shared_x_axis: bool = False
    autoscale: bool = True

    """Indicates that when we switch to full mode for a stacked plot we should put entire stacked plot in full mode or only one of the subplots"""
    full_mode_all_stack: bool = True

    """Auto redraw canvas every X seconds"""
    auto_refresh: int = 0

    _type: str = None

    def __post_init__(self):
        self._type = self.__class__.__module__+'.'+self.__class__.__qualname__
        if self.plots is None:
            self.plots = [[] for _ in range(self.cols)]

    def add_plot(self, plot, col=0):
        """
        Add a plot to this canvas.
        """
        if col >= len(self.plots):
            raise Exception("Cannot add plot to column {}: Canvas has only {} column(s)".format(col, len(self.plots)))
        if len(self.plots[col]) >= self.rows:
            raise Exception("Cannot add plot to column {}: Column is has {}/{} plots".format(col, len(self.plots[col]), self.rows))
        self.plots[col].append(plot)

    def set_mouse_mode(self, mode):
        """
        Set the current mouse mode.
        """
        self.mouse_mode = mode

    def enable_crosshair(self, color="red", linewidth=1, horizontal=False, vertical=True):
        """
        Enable the crosshair cursor.
        """
        self.crosshair_color = color
        self.crosshair_line_width = linewidth
        self.crosshair_enabled = True
        self.crosshair_vertical = vertical
        self.crosshair_horizontal = horizontal

    def to_dict(self) -> dict:
        return JSONExporter().to_dict(self)

    @staticmethod
    def from_dict(inp_dict):
        return JSONExporter().from_dict(inp_dict)

    def to_json(self):
        return JSONExporter().to_json(self)

    @staticmethod
    def from_json(inp_file):
        return JSONExporter().from_json(inp_file)

    def export_image(self, filename: str, **kwargs):
        """
        Export the canvas to an image file.
        """
        pass

    def reset_preferences(self):
        """
        Reset the preferences to default values.
        """
        self.font_size = Canvas.font_size
        self.shared_x_axis = Canvas.shared_x_axis
        self.grid = Canvas.grid
        self.legend = Canvas.legend
        self.font_color = Canvas.font_color
        self.line_style = Canvas.line_style
        self.line_size = Canvas.line_size
        self.marker = Canvas.marker
        self.marker_size = Canvas.marker_size
        self.step = Canvas.step
        self.full_mode_all_stack = Canvas.full_mode_all_stack
