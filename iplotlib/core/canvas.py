"""
This module defines the `Canvas` object.
"""

# Changelog:
#   Jan 2023:   -Added legend position and layout properties [Alberto Luengo]

from abc import ABC
from dataclasses import dataclass
from typing import List, Union, Dict

from iplotlib.core.persistence import JSONExporter
from iplotlib.core.plot import Plot, PlotXY
from iplotlib.core.signal import Signal
import pandas as pd


@dataclass
class Canvas(ABC):
    """
    This class exposes visual properties of a canvas.

    Attributes
    ----------
    MOUSE_MODE_SELECT : str
        Defines the mouse mode for selecting elements in the canvas
    MOUSE_MODE_CROSSHAIR : str
       Defines the mouse mode that activates the crosshair cursor
    MOUSE_MODE_PAN : str
        Sets the mouse mode for panning
    MOUSE_MODE_ZOOM : str
        Sets the mouse mode for zooming
    MOUSE_MODE_DIST : str
        Activates distance measurement mode for calculating distances on the canvas.
    rows : int
        Number of rows in the grid. If specified the space for this nuber of rows should be reserved when rendering
        canvas since some plots can be empty
    cols : int
        Number of columns in the grid. If specified the space for this number of columns should be reserved when
        rendering canvas since some plots may be empty
    canvas_title : str
        It is shown above the canvas grid centered horizontally
    round_hour : bool
        Rounds timestamps to the nearest hour if set to True
    hi_precision_data : bool
        a boolean that suggests the data is sensitive to round off errors and requires special handling
    dec_samples : int
        the default no. of samples for a data access fetch call.
    ticks_position : bool
        a boolean that indicates if the plot has to show all the ticks in all the axis (top and right included)
    mouse_mode : str
        the default mouse mode - 'select', 'zoom', 'pan', 'crosshair', defaults to 'select'
    enable_x_label_crosshair : bool
        Shows a crosshair-aligned label for the x-axis if True
    enable_y_label_crosshair : bool
        Shows a crosshair-aligned label for the y-axis if True
    enable_val_label_crosshair : bool
        Displays a label with the data value at the crosshair position if True
    plots : List[List[Union[Plot, None]]]
        A 22-level nested list of plots.
    focus_plot : Plot
        The plot currently focused
    crosshair_enabled : bool
        visibility of crosshair
    crosshair_color : str
        color of the crosshair cursor lines
    crosshair_line_width : int
        width of the crosshair cursor lines
    crosshair_horizontal : bool
        visibility of the horizontal line in the crosshair
    crosshair_vertical : bool
        visibility of the vertical line in the crosshair
    crosshair_per_plot : bool
        Crosshair for each plot in the canvas
    streaming : bool
        Enables real-time streaming updates to the canvas when True
    shared_x_axis : bool
        When True, all plots share a common x-axis for synchronized display
    full_mode_all_stack : bool
        Indicates that when we switch to full mode for a stacked plot we should put entire stacked plot in full mode or
        only one of the subplots
    auto_refresh : int
        Auto redraw canvas every X seconds
    _type : str
        type of the canvas
    _attribute_hierarchy : dict
         inherited attributes specific to plot properties
    """

    MOUSE_MODE_SELECT = "MM_SELECT"
    MOUSE_MODE_CROSSHAIR = 'MM_CROSSHAIR'
    MOUSE_MODE_PAN = 'MM_PAN'
    MOUSE_MODE_ZOOM = 'MM_ZOOM'
    MOUSE_MODE_DIST = 'MM_DIST'
    rows: int = 1
    cols: int = 1
    canvas_title: str = None
    round_hour: bool = False  # Check if it was decided to set the attribute in this Canvas Level
    hi_precision_data: bool = False
    dec_samples: int = 1000
    ticks_position: bool = False  # Check if it was decided to set the attribute in this Canvas Level
    mouse_mode: str = MOUSE_MODE_SELECT
    enable_x_label_crosshair: bool = True
    enable_y_label_crosshair: bool = True
    enable_val_label_crosshair: bool = True
    plots: List[List[Union[Plot, None]]] = None
    focus_plot: Plot = None
    crosshair_enabled: bool = False
    crosshair_color: str = "red"
    crosshair_line_width: int = 1
    crosshair_horizontal: bool = True
    crosshair_vertical: bool = True
    crosshair_per_plot: bool = False
    streaming: bool = False
    shared_x_axis: bool = False
    full_mode_all_stack: bool = True
    auto_refresh: int = 0
    undo_redo: bool = False
    _type: str = None
    _attribute_hierarchy = PlotXY().__dict__

    def __new__(cls, *args, **kwargs):
        instance = super().__new__(cls)
        instance.__dict__.update(cls._attribute_hierarchy)
        return instance

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

    def __setattr__(self, key, value):
        super().__setattr__(key, value)
        if key in self._attribute_hierarchy.keys() and self.plots:
            for column in self.plots:
                for plot in column:
                    if plot is not None:
                        setattr(plot, key, value)

    def reset_preferences(self):
        """
        Reset the preferences to default values.
        """
        self.shared_x_axis = Canvas.shared_x_axis
        self.round_hour = Canvas.round_hour
        self.ticks_position = Canvas.ticks_position
        self.enable_x_label_crosshair = Canvas.enable_x_label_crosshair
        self.enable_y_label_crosshair = Canvas.enable_y_label_crosshair
        self.enable_val_label_crosshair = Canvas.enable_val_label_crosshair
        self.crosshair_color = Canvas.crosshair_color
        self.full_mode_all_stack = Canvas.full_mode_all_stack
        self.focus_plot = Canvas.focus_plot

    def merge(self, old_canvas: 'Canvas'):
        """
        Reset the preferences to default values.
        """
        for attr in self._attribute_hierarchy.keys():
            super().__setattr__(attr, getattr(old_canvas, attr))
        self.canvas_title = old_canvas.canvas_title
        self.shared_x_axis = old_canvas.shared_x_axis
        self.round_hour = old_canvas.round_hour
        self.ticks_position = old_canvas.ticks_position
        self.enable_x_label_crosshair = old_canvas.enable_x_label_crosshair
        self.enable_y_label_crosshair = old_canvas.enable_y_label_crosshair
        self.enable_val_label_crosshair = old_canvas.enable_val_label_crosshair
        self.crosshair_color = old_canvas.crosshair_color
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
                            # Now when using pulses, if no start time or end time are specified, the default is set to
                            # 0 and None respectively. For that reason, it is necessary to check the ts_end of the
                            # different signals and create the mask depending on the circumstances.
                            if pl_signal.ts_end is None:
                                mask = pl_signal.x_data >= pl_signal.ts_start
                            else:
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
