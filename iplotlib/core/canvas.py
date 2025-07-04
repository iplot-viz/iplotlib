# Copyright (c) 2020-2025 ITER Organization,
#               CS 90046
#               13067 St Paul Lez Durance Cedex
#               France
# Author IO
#
# This file is part of iplotlib module.
# iplotlib python module is free software: you can redistribute it and/or modify it under
# the terms of the MIT license.
#
# This file is part of ITER CODAC software.
# For the terms and conditions of redistribution or use of this software
# refer to the file LICENSE located in the top level directory
# of the distribution package
#


"""
This module defines the `Canvas` object.
"""

# Changelog:
#   Jan 2023:   -Added legend position and layout properties [Alberto Luengo]

from abc import ABC
from dataclasses import dataclass
from typing import List, Union, Dict

from iplotLogging import setupLogger
from iplotlib.core.persistence import JSONExporter
from iplotlib.core.plot import Plot, PlotXY, PlotContour, PlotXYWithSlider
from iplotlib.core.signal import Signal
import pandas as pd

logger = setupLogger.get_logger(__name__)


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
    max_diff: int
        Maximum allowed difference for comparing axis ranges between different plots
    autoscale : bool
        enables automatic scaling of the axis range to fit displayed data if set to True
    """

    MOUSE_MODE_SELECT = "MM_SELECT"
    MOUSE_MODE_CROSSHAIR = 'MM_CROSSHAIR'
    MOUSE_MODE_PAN = 'MM_PAN'
    MOUSE_MODE_ZOOM = 'MM_ZOOM'
    MOUSE_MODE_DIST = 'MM_DIST'
    MOUSE_MODE_MARKER = 'MM_MARKER'
    rows: int = 1
    cols: int = 1
    title: str = None
    ticks_position: bool = None
    mouse_mode: str = MOUSE_MODE_SELECT
    enable_x_label_crosshair: bool = None
    enable_y_label_crosshair: bool = None
    enable_val_label_crosshair: bool = None
    plots: List[List[Union[Plot, None]]] = None
    focus_plot: [Plot | None] = None
    crosshair_enabled: bool = False
    crosshair_color: str = None
    crosshair_line_width: int = 1
    crosshair_horizontal: bool = True
    crosshair_vertical: bool = True
    crosshair_per_plot: bool = False
    streaming: bool = False
    shared_x_axis: bool = None
    full_mode_all_stack: bool = None
    auto_refresh: int = 0
    undo_redo: bool = False
    max_diff: int = None
    _type: str = None
    font_size: int = None
    font_color: str = None
    background_color: str = None
    tick_number: int = None
    round_hour: bool = None
    log_scale: bool = None
    line_style: str = None
    line_size: int = None
    marker: str = None
    marker_size: int = None
    step: str = None
    legend: bool = None
    legend_position: str = None
    legend_layout: str = None
    grid: bool = None
    autoscale: bool = None
    contour_filled: bool = None
    legend_format: str = None
    equivalent_units: bool = None
    color_map: str = None
    contour_levels: int = None

    def __post_init__(self):
        self._type = self.__class__.__module__ + '.' + self.__class__.__qualname__
        if self.plots is None:
            self.plots = [[] for _ in range(self.cols)]

    def add_plot(self, plot, col=0):
        """
        Add a plot to this canvas.
        """
        if plot:
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

        # Propagated attributes
        self.font_size = Canvas.font_size
        self.font_color = Canvas.font_color
        self.background_color = Canvas.background_color
        self.tick_number = Canvas.tick_number
        self.log_scale = Canvas.log_scale
        self.line_style = Canvas.line_style
        self.line_size = Canvas.line_size
        self.marker = Canvas.marker
        self.marker_size = Canvas.marker_size
        self.step = Canvas.step
        self.legend = Canvas.legend
        self.legend_position = Canvas.legend_position
        self.legend_layout = Canvas.legend_layout
        self.grid = Canvas.grid
        self.autoscale = Canvas.autoscale
        self.contour_filled = Canvas.contour_filled
        self.legend_format = Canvas.legend_format
        self.equivalent_units = Canvas.equivalent_units
        self.color_map = Canvas.color_map
        self.contour_levels = Canvas.contour_levels
        # Specific attributes
        self.title = Canvas.title
        self.shared_x_axis = Canvas.shared_x_axis
        self.round_hour = Canvas.round_hour
        self.ticks_position = Canvas.ticks_position
        self.enable_x_label_crosshair = Canvas.enable_x_label_crosshair
        self.enable_y_label_crosshair = Canvas.enable_y_label_crosshair
        self.enable_val_label_crosshair = Canvas.enable_val_label_crosshair
        self.crosshair_color = Canvas.crosshair_color
        self.full_mode_all_stack = Canvas.full_mode_all_stack
        self.focus_plot = Canvas.focus_plot
        self.max_diff = Canvas.max_diff

        for _, col in enumerate(self.plots):
            for _, plot in enumerate(col):
                if isinstance(plot, PlotXY):
                    plot.reset_preferences()
                elif isinstance(plot, PlotContour):
                    plot.reset_preferences()
                else:
                    continue

    def merge(self, old_canvas: 'Canvas'):
        """
        Reset the preferences to default values.
        """

        # Propagated attributes
        self.font_size = old_canvas.font_size
        self.font_color = old_canvas.font_color
        self.background_color = old_canvas.background_color
        self.tick_number = old_canvas.tick_number
        self.log_scale = old_canvas.log_scale
        self.line_style = old_canvas.line_style
        self.line_size = old_canvas.line_size
        self.marker = old_canvas.marker
        self.marker_size = old_canvas.marker_size
        self.step = old_canvas.step
        self.legend = old_canvas.legend
        self.legend_position = old_canvas.legend_position
        self.legend_layout = old_canvas.legend_layout
        self.grid = old_canvas.grid
        self.autoscale = old_canvas.autoscale
        self.contour_filled = old_canvas.contour_filled
        self.legend_format = old_canvas.legend_format
        self.equivalent_units = old_canvas.equivalent_units
        self.color_map = old_canvas.color_map
        self.contour_levels = old_canvas.contour_levels
        # Specific attributes
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
        self.max_diff = old_canvas.max_diff

        for idxColumn, columns in enumerate(self.plots):
            for idxPlot, plot in enumerate(columns):
                if plot and idxColumn < len(old_canvas.plots) and idxPlot < len(old_canvas.plots[idxColumn]):
                    # Found matching plot
                    old_plot = old_canvas.plots[idxColumn][idxPlot]
                    if not old_plot:
                        continue

                    if type(plot) is type(old_plot):
                        plot.merge(old_plot)
                    else:
                        # Handle when it is a plot of a different type.
                        # Simplest way: Warning that a plot has been drawn where before there was a plot of a
                        # different type, therefore, the properties cannot be kept to make a merge. In this way,
                        # the new plot is drawn with its default properties.
                        logger.warning("Merge with different type of plots")

        # Gather all old signals into a map with uid as key
        def compute_signal_uniqkey(computed_signal: Signal):
            # Consider signal is same if it has the same row uid, name
            signal_key = computed_signal.uid + ";" + computed_signal.name
            return signal_key

        map_old_signals: Dict[str, Signal] = {}
        for columns in old_canvas.plots:
            for old_plot in columns:
                if not old_plot:
                    continue
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
                            if isinstance(row, PlotXYWithSlider):
                                timerange = pl_signal.time
                                y_data = pl_signal.y_data
                            else:
                                if pl_signal.ts_end is None:
                                    mask = pl_signal.x_data >= pl_signal.ts_start
                                else:
                                    mask = (pl_signal.x_data >= pl_signal.ts_start) & (
                                            pl_signal.x_data <= pl_signal.ts_end)
                                timerange = pl_signal.x_data[mask]
                                y_data = pl_signal.y_data[mask]

                            # Check min and max dates
                            if timerange.size > 0 and bool(min(timerange) > (1 << 53) and
                                                           max(timerange) < pd.Timestamp.max.value):
                                timestamps = [pd.Timestamp(value) for value in timerange]
                                format_ts = [ts.strftime("%Y-%m-%dT%H:%M:%S.%f") + "{:03d}".format(ts.nanosecond) + "Z"
                                             for ts in timestamps]
                            else:
                                format_ts = timerange

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
                                timeframe = pd.Series(format_ts, name=f"{col_name}.time")
                                if len(y_data[0]) > 1:
                                    dataframe = pd.DataFrame(y_data, columns=[f"{col_name}.data.{i}" for i in range(
                                        len(y_data[0]))])  # we could use x data in header
                                else:
                                    dataframe = pd.DataFrame(y_data, columns=[f"{col_name}.data"])
                                x = pd.concat([x, timeframe, dataframe], axis=1)
        return x.to_csv(index=False)

    def update_canvas_properties(self, properties: dict):
        for property_name, value in properties.items():
            if hasattr(self, property_name):
                setattr(self, property_name, value)
