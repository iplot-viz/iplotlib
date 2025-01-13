from dataclasses import dataclass

default_property: dict = {
    # LinearAxis
    'font_size': 10,
    'font_color': '#000000',
    'tick_number': 7,
    'autoscale': True,
    # Plot
    'background_color': '#FFFFFF',
    'legend': True,
    'legend_position': 'upper right',
    'legend_layout': 'vertical',
    'grid': True,
    'log_scale': False,
    # PlotContour
    'contour_filled': False,
    'legend_format': 'color_bar',
    'equivalent_units': False,
    # SignalContour
    'color_map': "viridis",
    'contour_levels': 10,
    # SignalXY
    'color': None,
    'line_style': 'Solid',
    'line_size': 1,
    'marker': None,
    'marker_size': 1,
    'step': "default"
}

@dataclass
class Property:
    parent = None

    def __getattribute__(self, item):
        if item == "parent":
            return object.__getattribute__(self, "parent")

        value = object.__getattribute__(self, item)
        if value is not None:
            return value

        parent = self.parent
        if parent:
            return getattr(parent, item, default_property.get(item, None))

        return default_property.get(item, None)

    def get_real_value(self, item):
        return object.__getattribute__(self, item)


@dataclass
class SignalXYProp(Property):
    color: str = None
    line_style: str = None
    line_size: int = None
    marker: str = None
    marker_size: int = None
    step: str = None

    def reset_preferences(self):
        self.color = SignalXYProp.color
        self.line_style = SignalXYProp.line_style
        self.line_size = SignalXYProp.line_size
        self.marker = SignalXYProp.marker
        self.marker_size = SignalXYProp.marker_size
        self.step = SignalXYProp.step

    def merge(self, old_signal: 'SignalXYProp'):
        self.color = old_signal.color
        self.line_style = old_signal.line_style
        self.line_size = old_signal.line_size
        self.marker = old_signal.marker
        self.marker_size = old_signal.marker_size
        self.step = old_signal.step


@dataclass
class SignalContourProp(Property):
    color_map: str = None
    contour_levels: int = None

    def reset_preferences(self):
        self.color_map = SignalContourProp.color_map
        self.contour_levels = SignalContourProp.contour_levels

    def merge(self, old_signal: 'SignalContourProp'):
        self.color_map = old_signal.color_map
        self.contour_levels = old_signal.contour_levels


@dataclass
class PlotProp(Property):
    background_color: str = None
    legend: bool = None
    legend_position: str = None
    legend_layout: str = None
    grid: bool = None
    log_scale: bool = None

    def reset_preferences(self):
        self.background_color = PlotProp.background_color
        self.legend = PlotProp.legend
        self.legend_position = PlotProp.legend_position
        self.legend_layout = PlotProp.legend_layout
        self.grid = PlotProp.grid
        self.log_scale = PlotProp.log_scale

    def merge(self, old_plot: 'PlotProp'):
        self.background_color = old_plot.background_color
        self.legend = old_plot.legend
        self.legend_position = old_plot.legend_position
        self.legend_layout = old_plot.legend_layout
        self.grid = old_plot.grid
        self.log_scale = old_plot.log_scale


@dataclass
class PlotXYProp(PlotProp, SignalXYProp):
    pass

    def reset_preferences(self):
        super().reset_preferences()

    def merge(self, old_plot: 'PlotXYProp'):
        super().merge(old_plot)


@dataclass
class PlotContourProp(PlotProp, SignalContourProp):
    legend_format: str = None
    equivalent_units: bool = None

    def reset_preferences(self):
        super().reset_preferences()
        self.legend_format = PlotContourProp.legend_format
        self.equivalent_units = PlotContourProp.equivalent_units

    def merge(self, old_plot: 'PlotContourProp'):
        super().merge(old_plot)
        self.legend_format = old_plot.legend_format
        self.equivalent_units = old_plot.equivalent_units


@dataclass
class AxisProp(Property):
    font_size: int = None
    font_color: str = None
    tick_number: int = None
    autoscale: bool = None

    def reset_preferences(self):
        self.font_size = AxisProp.font_size
        self.font_color = AxisProp.font_color
        self.tick_number = AxisProp.tick_number
        self.autoscale = AxisProp.autoscale

    def merge(self, old_axis: 'AxisProp'):
        self.font_size = old_axis.font_size
        self.font_color = old_axis.font_color
        self.tick_number = old_axis.tick_number
        self.autoscale = old_axis.autoscale


@dataclass
class CanvasProp(PlotXYProp, PlotContourProp, AxisProp):
    title: str = None
    shared_x_axis: bool = None
    round_hour: bool = None
    ticks_position: bool = None
    enable_x_label_crosshair: bool = None
    enable_y_label_crosshair: bool = None
    enable_val_label_crosshair: bool = None
    crosshair_color: str = None

    def reset_preferences(self):
        self.title = CanvasProp.title
        self.shared_x_axis = CanvasProp.shared_x_axis
        self.round_hour = CanvasProp.round_hour
        self.ticks_position = CanvasProp.ticks_position
        self.enable_x_label_crosshair = CanvasProp.enable_x_label_crosshair
        self.enable_y_label_crosshair = CanvasProp.enable_y_label_crosshair
        self.enable_val_label_crosshair = CanvasProp.enable_val_label_crosshair
        self.crosshair_color = CanvasProp.crosshair_color

    def merge(self, old_canvas: 'CanvasProp'):
        super().merge(old_canvas)
        self.title = old_canvas.title
        self.shared_x_axis = old_canvas.shared_x_axis
        self.round_hour = old_canvas.round_hour
        self.ticks_position = old_canvas.ticks_position
        self.enable_x_label_crosshair = old_canvas.enable_x_label_crosshair
        self.enable_y_label_crosshair = old_canvas.enable_y_label_crosshair
        self.enable_val_label_crosshair = old_canvas.enable_val_label_crosshair
        self.crosshair_color = old_canvas.crosshair_color


x = CanvasProp()
print(x)
