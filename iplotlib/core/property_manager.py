from iplotlib.core.axis import Axis
from iplotlib.core.canvas import Canvas
from iplotlib.core.plot import Plot, PlotXY
from iplotlib.core.signal import Signal, ArraySignal

class PropertyManager:
    """This class provides an API to update properties in the iplotlib hierarchy
        such that the lower level constructs inherit properties from higher level
        constructs. (unless the properties of lower level constructs are explicitly
        specified)

        Usage:
        ...
        ...
        ..Somewhere in your code..
        prop_manager = PropertyManager()
        prop_manager.update(canvas)
        ...
        ...
    """
    def update(self, canvas: Canvas):
        """Update attributes downward.
            Canvas > [Plot > Signals], Axis
        """
        for column in canvas.plots:
            for plot in column:
                if isinstance(plot, Plot):
                    self.acquire_plot_from_canvas(canvas, plot)

    def acquire_plot_from_canvas(self, canvas: Canvas, plot: Plot):
        """Update attributes downward.
            Canvas -> Plot -> [Axis, Signals]
        """
        if plot.font_color is None:
            plot.font_color = canvas.font_color
        if plot.font_size is None:
            plot.font_size = canvas.font_size
        if plot.legend is None:
            plot.legend = canvas.legend
        if isinstance(plot, PlotXY):
            if plot.grid is None:
                plot.grid = canvas.grid
            if plot.line_size is None:
                plot.line_size = canvas.line_size
            if plot.line_style is None:
                plot.line_style = canvas.line_style
            if plot.marker is None:
                plot.marker = canvas.marker
            if plot.marker_size is None:
                plot.marker_size = canvas.marker_size
            if plot.step is None:
                plot.step = canvas.step
            if plot.dec_samples is None:
                plot.dec_samples = canvas.dec_samples
            if plot.hi_precision_data is None:
                plot.hi_precision_data = canvas.hi_precision_data
        for signals in plot.signals.values():
            for signal in signals:
                self.acquire_signal_from_plot(plot, signal)
        if plot.axes is not None:
            for ax in plot.axes:
                self.acquire_axis_from_plot(plot, ax)
         
    def acquire_axis_from_plot(self, plot: Plot, ax: Axis):
        """Update attributes downward.
            Plot -> Axis
        """
        if ax.font_color is None:
            ax.font_color = plot.font_color
        if ax.font_size is None:
            ax.font_size = plot.font_size

    def acquire_signal_from_plot(self, plot: Plot, signal: Signal):
        """Update attributes downward.
            Plot -> Signal
        """
        if isinstance(signal, ArraySignal) and isinstance(plot, PlotXY):
            if signal.line_size is None:
                signal.line_size = plot.line_size
            if signal.line_style is None:
                signal.line_style = plot.line_style
            if signal.marker is None:
                signal.marker = plot.marker
            if signal.marker_size is None:
                signal.marker_size = plot.marker_size
            if signal.step is None:
                signal.step = plot.step
            if signal.hi_precision_data is None:
                signal.hi_precision_data = plot.hi_precision_data