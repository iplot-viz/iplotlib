default_property: dict = {
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

    # PlotXY

    # SignalXY
    'color': None,
    'line_style': 'Solid',
    'line_size': 1,
    'marker': None,
    'marker_size': 1,
    'step': "default",

    # PlotContour
    'contour_filled': False,
    'legend_format': 'color_bar',
    'axis_prop': False,

    # SignalContour
    'color_map': "viridis",
    'contour_levels': 10,
}


class PropertyManager:
    """
    This class provides an API that returns attributes in the iplotlib hierarchy.
    """

    def get_value(self, obj: any, attr_name: str):
        value = getattr(obj, attr_name, None)
        if value is not None:
            return value
        if hasattr(obj, 'parent'):
            return self.get_value(obj.parent, attr_name)
        return default_property.get(attr_name, None)
