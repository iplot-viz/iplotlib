"""
This module defines the `Canvas` object.
"""

# Changelog:
#   Jan 2023:   -Added legend position and layout properties [Alberto Luengo]

from abc import ABC
from dataclasses import dataclass
from typing import List, Union, Dict

from iplotlib.core.persistence import JSONExporter
from iplotlib.core.plot import Plot
from iplotlib.core.signal import Signal
import pandas as pd


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

    #: Number of rows in the grid. If specified the space for this nuber of rows should be reserved
    # when rendering canvas since some plots can be empty
    rows: int = 1
    #: Number of columns in the grid. If specified the space for this number of columns should be reserved
    # when rendering canvas since some plots may be empty
    cols: int = 1
    title: str = None  #: Canvas title - should be shown above the canvas grid centered horizontally

    font_size: int = None  #: default font size that will be cascaded across plots and axes of this canvas.
    font_color: str = '#000000'  #: default font color that will be cascaded across plots and axes of this canvas.
    background_color: str = '#FFFFFF'  # default background color will be white for each plot
    # previous background color used to keep consistency between Canvas and Plot preferences
    prev_background_color = '#FFFFFF'
    tick_number: int = 7  # default number of ticks for each plot
    prev_tick_number = 7

    round_hour: bool = False

    line_style: str = None  #: default value for line plots - 'solid','dashed','dotted' defaults to 'solid'.
    # default line thickness for drawing line plots. Whether it is mapped to pixels or DPI independent
    # points should be canvas implementation dependent
    line_size: int = None

    #: default marker type to display. If set a marker is drawn at every point of the data sample.
    # Markers and lines can be drawn together and are not mutually exclusive.
    # Supported types: 'x','o', None, default: None (no markers are drawn)
    marker: str = None
    #: default marker size. Whether it is mapped to pixels or DPI independent points should
    # be canvas implementation dependent
    marker_size: int = None

    step: str = None  # default line style - 'post', 'mid', 'pre', 'None', defaults to 'None'.

    #: a boolean that suggests the data is sensitive to round off errors and requires special handling
    hi_precision_data: bool = False
    dec_samples: int = 1000  #: the default no. of samples for a data access fetch call.

    legend: bool = True  #: a boolean that suggests the visibility of a plot legend box.
    legend_position: str = 'upper right'  #: indicate the location of the plot legend
    legend_layout: str = 'vertical'  #: indicate the layout of the plot legend
    grid: bool = False  #: a boolean that suggests the visibility of a plot grid
    ticks_position: bool = False

    #: the default mouse mode - 'select', 'zoom', 'pan', 'crosshair', defaults to 'select'
    mouse_mode: str = MOUSE_MODE_SELECT
    enable_Xlabel_crosshair: bool = True
    enable_Ylabel_crosshair: bool = True
    enable_ValLabel_crosshair: bool = True

    plots: List[List[Union[Plot, None]]] = None  #: A 22-level nested list of plots.
    focus_plot: Plot = None

    crosshair_enabled: bool = False  #: visibility of crosshair.
    crosshair_color: str = "red"  #: color of the crosshair cursor lines.
    crosshair_line_width: int = 1  # width of the crosshair cursor lines.
    crosshair_horizontal: bool = True  # visibility of the hori
    crosshair_vertical: bool = True
    crosshair_per_plot: bool = False

    streaming: bool = False
    shared_x_axis: bool = False
    autoscale: bool = True

    contour_levels: int = 30
    contour_filled: bool = False

    """Indicates that when we switch to full mode for a stacked plot we should put entire stacked plot in full mode or only one of the subplots"""
    full_mode_all_stack: bool = True

    """Auto redraw canvas every X seconds"""
    auto_refresh: int = 0

    _type: str = None

    def __post_init__(self):
        self._type = self.__class__.__module__ + '.' + self.__class__.__qualname__
        if self.plots is None:
            self.plots = [[] for _ in range(self.cols)]

    def add_plot(self, plot, col=0):
        """
        Add a plot to this canvas.
        """
        if col >= len(self.plots):
            raise Exception("Cannot add plot to column {}: Canvas has only {} column(s)".format(col, len(self.plots)))
        if len(self.plots[col]) >= self.rows:
            raise Exception(
                "Cannot add plot to column {}: Column is has {}/{} plots".format(col, len(self.plots[col]), self.rows))
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
    def from_dict(inp_dict) -> 'Canvas':
        return JSONExporter().from_dict(inp_dict)

    def to_json(self):
        return JSONExporter().to_json(self)

    @staticmethod
    def from_json(inp_file) -> 'Canvas':
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
        self.legend_position = Canvas.legend_position
        self.legend_layout = Canvas.legend_layout
        self.enable_Xlabel_crosshair = Canvas.enable_Xlabel_crosshair
        self.enable_Ylabel_crosshair = Canvas.enable_Ylabel_crosshair
        self.enable_ValLabel_crosshair = Canvas.enable_ValLabel_crosshair
        self.crosshair_color = Canvas.crosshair_color
        self.font_color = Canvas.font_color
        self.background_color = Canvas.background_color
        self.tick_number = Canvas.tick_number
        self.prev_tick_number = Canvas.prev_tick_number
        self.line_style = Canvas.line_style
        self.line_size = Canvas.line_size
        self.marker = Canvas.marker
        self.marker_size = Canvas.marker_size
        self.step = Canvas.step
        self.full_mode_all_stack = Canvas.full_mode_all_stack
        self.contour_levels = Canvas.contour_levels
        self.contour_filled = Canvas.contour_filled
        self.focus_plot = Canvas.focus_plot

    def merge(self, old_canvas: 'Canvas'):
        """
        Reset the preferences to default values.
        """
        self.title = old_canvas.title
        self.font_size = old_canvas.font_size
        self.shared_x_axis = old_canvas.shared_x_axis
        self.grid = old_canvas.grid
        self.legend = old_canvas.legend
        self.legend_position = old_canvas.legend_position
        self.legend_layout = old_canvas.legend_layout
        self.enable_Xlabel_crosshair = old_canvas.enable_Xlabel_crosshair
        self.enable_Ylabel_crosshair = old_canvas.enable_Ylabel_crosshair
        self.enable_ValLabel_crosshair = old_canvas.enable_ValLabel_crosshair
        self.crosshair_color = old_canvas.crosshair_color
        self.font_color = old_canvas.font_color
        self.background_color = old_canvas.background_color
        self.tick_number = old_canvas.tick_number
        self.prev_tick_number = old_canvas.prev_tick_number
        self.line_style = old_canvas.line_style
        self.line_size = old_canvas.line_size
        self.marker = old_canvas.marker
        self.marker_size = old_canvas.marker_size
        self.step = old_canvas.step
        self.full_mode_all_stack = old_canvas.full_mode_all_stack
        self.focus_plot = old_canvas.focus_plot

        for idxColumn, columns in enumerate(self.plots):
            for idxPlot, plot in enumerate(columns):
                if plot and idxColumn < len(old_canvas.plots) and idxPlot < len(old_canvas.plots[idxColumn]):
                    # Found matching plot
                    old_plot = old_canvas.plots[idxColumn][idxPlot]
                    if old_plot:
                        plot.merge(old_plot)

        # Gather all old signals into a map with uid as key
        def compute_signal_uniqkey(computed_signal: Signal):
            # Consider signal is same if it has the same row uid, name
            signal_key = computed_signal.uid + ";" + computed_signal.name
            return signal_key

        map_old_signals: Dict[str, Signal] = {}
        for columns in old_canvas.plots:
            for old_plot in columns:
                if old_plot:
                    for old_signals in old_plot.signals.values():
                        for old_signal in old_signals:
                            key = compute_signal_uniqkey(old_signal)
                            map_old_signals[key] = old_signal

        # Merge signals at canvas level to handle move between plots
        for columns in self.plots:
            for plot in columns:
                if plot:
                    for signals in plot.signals.values():
                        for signal in signals:
                            key = compute_signal_uniqkey(signal)
                            if key in map_old_signals:
                                signal.merge(map_old_signals[key])

    def get_signals_as_csv(self):
        x = pd.DataFrame()
        focus_plot = self.focus_plot
        for c, column in enumerate(self.plots):
            for r, row in enumerate(column):
                if row and (not focus_plot or row == focus_plot):
                    for p, plot in enumerate(row.signals.values()):
                        for s, pl_signal in enumerate(plot):
                            col_name = f"plot{r + 1}.{c + 1}"
                            if len(row.signals) > 1:
                                col_name += f".{p + 1}"
                            if pl_signal.alias:
                                col_name += f"_{pl_signal.alias}"
                            else:
                                col_name += f"_{pl_signal.name}"

                            # Refresh limits
                            mask = (pl_signal.x_data >= pl_signal.ts_start) & (pl_signal.x_data <= pl_signal.ts_end)
                            pl_signal.x_data = pl_signal.x_data[mask]
                            pl_signal.y_data = pl_signal.y_data[mask]

                            # Check min and max dates
                            if pl_signal.x_data.size > 0 and bool(min(pl_signal.x_data) > (1 << 53) and
                                                                  max(pl_signal.x_data) < pd.Timestamp.max.value):

                                timestamps = [pd.Timestamp(value) for value in pl_signal.x_data]
                                format_ts = [ts.strftime("%Y-%m-%dT%H:%M:%S.%f") + "{:03d}".format(ts.nanosecond) + "Z"
                                             for ts in timestamps]
                            else:
                                format_ts = pl_signal.x_data

                            if pl_signal.envelope:
                                result = []
                                for i in range(len(pl_signal.y_data)):
                                    min_values = pl_signal.y_data[i]
                                    max_values = pl_signal.z_data[i]
                                    avg_values = pl_signal.data_store[3][i]
                                    result.append(f"({min_values};{avg_values};{max_values})")
                                x[f"{col_name}.time"] = pd.Series(format_ts, name=f"{col_name}.time")
                                x[f"{col_name}.data"] = pd.Series(result, name=f"{col_name}.data")
                            else:

                                x[f"{col_name}.time"] = pd.Series(format_ts, name=f"{col_name}.time")
                                x[f"{col_name}.data"] = pd.Series(pl_signal.y_data, name=f"{col_name}.data")
        return x.to_csv(index=False)
