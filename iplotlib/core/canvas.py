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

from iplotlib.core.hierarchical_property import HierarchicalProperty


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
    title : str
        It is shown above the canvas grid centered horizontally
    round_hour : bool
        Rounds timestamps to the nearest hour if set to True
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
    title: str = None
    round_hour: bool = False
    ticks_position: bool = False
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

    # Axis
    font_size = HierarchicalProperty('font_size', default=10)
    font_color = HierarchicalProperty('font_color', default='#000000')
    tick_number = HierarchicalProperty('tick_number', default=7)
    autoscale = HierarchicalProperty('autoscale', default=True)

    # Plot
    background_color = HierarchicalProperty('background_color', default='#FFFFFF')
    legend = HierarchicalProperty('legend', default=True)
    legend_position = HierarchicalProperty('legend_position', default='upper right')
    legend_layout = HierarchicalProperty('legend_layout', default='vertical')
    grid = HierarchicalProperty('grid', default=True)

    # PlotXY
    log_scale = HierarchicalProperty('log_scale', default=False)

    # SignalXY
    color = HierarchicalProperty('color', default=None)
    line_style = HierarchicalProperty('line_style', default='Solid')
    line_size = HierarchicalProperty('line_size', default=1)
    marker = HierarchicalProperty('marker', default=None)
    marker_size = HierarchicalProperty('marker_size', default=0)
    step = HierarchicalProperty('step', default="linear")

    # PlotContour
    contour_filled = HierarchicalProperty('contour_filled', default=False)  # Set if the plot is filled or not
    legend_format = HierarchicalProperty('legend_format', default='color_bar')
    axis_prop = HierarchicalProperty('axis_prop', default=False)  # Set the aspect ratio of the graphic

    # SignalContour
    color_map = HierarchicalProperty('color_map', default="viridis")
    contour_levels = HierarchicalProperty('contour_levels', default=10)

    def __post_init__(self):
        self._type = self.__class__.__module__ + '.' + self.__class__.__qualname__
        if self.plots is None:
            self.plots = [[] for _ in range(self.cols)]

    def add_plot(self, plot, col=0):
        """
        Add a plot to this canvas.
        """
        plot.parent = self
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
        self.title = old_canvas.title
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
                        if type(plot) is type(old_plot):
                            plot.merge(old_plot)
                        else:
                            # Handle when it is a plot of a different type.
                            # Simplest way: Warning that a plot has been drawn where before there was a plot of a
                            # different type, therefore, the properties cannot be kept to make a merge. In this way,
                            # the new plot is drawn with its default properties.
                            pass
                            # logging.warning("Merge with different type of plots")

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
