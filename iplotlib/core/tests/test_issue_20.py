import pytest
from iplotlib.core.plot import PlotXY
from iplotlib.core.signal import SignalXY

def test_signal_colors_construction():
    """Test that signals added during construction get different colors."""
    s1 = SignalXY(uid='1', name='s1')
    s2 = SignalXY(uid='2', name='s2')
    # Use signals in constructor
    p = PlotXY(signals={1: [s1, s2]})

    # Check that they have colors (currently they will be None)
    assert s1.color is not None, "Signal 1 should have a color assigned"
    assert s2.color is not None, "Signal 2 should have a color assigned"
    assert s1.color != s2.color, "Signals should have different colors"

def test_signal_colors_reset_preferences():
    """Test that colors are re-assigned after reset_preferences."""
    p = PlotXY()
    s1 = SignalXY(uid='1', name='s1')
    s2 = SignalXY(uid='2', name='s2')
    p.add_signal(s1)
    p.add_signal(s2)

    color1 = s1.color
    color2 = s2.color

    assert color1 is not None
    assert color2 is not None
    assert color1 != color2

    p.reset_preferences()

    # After reset, colors should be re-assigned and consistent with original colors
    assert s1.color == color1, "Signal 1 should keep its original color after reset"
    assert s2.color == color2, "Signal 2 should keep its original color after reset"

def test_signal_merge_preserves_cycle_colors():
    """Test that cycle-assigned colors are preserved during merge."""
    p1 = PlotXY()
    s1 = SignalXY(uid='1', name='s1')
    p1.add_signal(s1)
    color1 = s1.color

    state = {
        'plots': [[{
            'signals': {
                1: [{
                    'uid': '1', 'name': 's1', 'color': color1, 'original_color': color1, 'new_color': False,
                    'line_style': None, 'line_size': None, 'marker': None, 'marker_size': None, 'step': None
                }]
            },
            '_type': 'iplotlib.core.plot.PlotXY',
            'plot_title': None, 'legend': None, 'legend_position': None, 'legend_layout': None,
            'font_size': None, 'font_color': None, 'background_color': None, 'grid': None, 'log_scale': None,
            'axes': [], '_color_index': 1, 'line_style': None, 'line_size': None, 'marker': None, 'marker_size': None, 'step': None
        }]],
        'font_size': None, 'font_color': None, 'background_color': None, 'tick_number': None, 'log_scale': None,
        'line_style': None, 'line_size': None, 'marker': None, 'marker_size': None, 'step': None,
        'legend': None, 'legend_position': None, 'legend_layout': None, 'grid': None, 'autoscale': None,
        'contour_filled': None, 'legend_format': None, 'equivalent_units': None, 'color_map': None, 'contour_levels': None,
        'canvas_begin': None, 'canvas_end': None, 'title': None, 'shared_x_axis': None, 'round_hour': None, 'ticks_position': None,
        'enable_x_label_crosshair': None, 'enable_y_label_crosshair': None, 'enable_val_label_crosshair': None,
        'crosshair_color': None, 'full_mode_all_stack': None, 'focus_plot': None, 'max_diff': None
    }

    p2 = PlotXY()
    s1_new = SignalXY(uid='1', name='s1')
    p2.add_signal(s1_new)

    # Even if p2 assigned a different color (if order changed), merge should restore color1
    s1_new.color = "temporary_wrong_color"

    from iplotlib.core.canvas import Canvas
    c2 = Canvas()
    c2.add_plot(p2)
    c2.merge(state)

    assert s1_new.color == color1, f"Signal color should be {color1} after merge, but got {s1_new.color}"
