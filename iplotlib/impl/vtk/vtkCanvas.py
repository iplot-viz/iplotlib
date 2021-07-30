import numpy as np
import typing
from dataclasses import dataclass

from iplotlib.core.canvas import Canvas
from iplotlib.core.plot import Plot
from iplotlib.core.signal import Signal
from iplotlib.impl.vtk import utils as vtkImplUtils

# needed for runtime vtk-opengl libs
import vtkmodules.vtkRenderingOpenGL2
# needed for runtime vtk-opengl libs
import vtkmodules.vtkRenderingContextOpenGL2
from vtkmodules.vtkCommonDataModel import vtkTable, vtkVector2i
from vtkmodules.vtkViewsContext2D import vtkContextView
from vtkmodules.vtkChartsCore import vtkAxis, vtkChartMatrix, vtkChart, vtkPlot, vtkPlotLine
from vtkmodules.util import numpy_support

from iplotLogging import setupLogger as sl
logger = sl.get_logger(__name__, "DEBUG")


class InvalidPlotException(Exception):
    def __init__(self, *args: object) -> None:
        super().__init__(*args)


@dataclass
class VTKCanvas(Canvas):
    """A concrete implementation of iplotlib.core.canvas.Canvas
    """

    def __post_init__(self):
        """Initialize underlying vtk classes.
        """
        super().__post_init__()

        self.view = vtkContextView()
        self.scene = self.view.GetScene()

        self.matrix = vtkChartMatrix()
        self.matrix.SetGutterX(50)
        self.matrix.SetGutterY(50)

        self.scene.AddItem(self.matrix)

        self._plot_lookup = dict()

    def clear(self):
        self.matrix.SetSize(vtkVector2i(0, 0))

    def refresh(self):
        """This method analyzes the iplotlib canvas data structure and maps it
        onto a vtkChartMatrix
        """

        # 1. Clear layout.
        self.clear()

        # 2. Allocate
        self.matrix.SetSize(vtkVector2i(self.cols, self.rows))

        # 3. Fill canvas with charts
        for i, column in enumerate(self.plots):

            j = 0

            for plot in column:
                
                self.refresh_plot(plot, i, j)

                # Increment row number carefully. (for next iteration)
                j += plot.row_span if isinstance(plot, Plot) else 1


    def get_internal_row_id(self, r: int, plot: Plot) -> int:
        """This method accounts for the difference in row numbering convention
            b/w iplotlib against vtk. 

            In vtk the ordering of rows is bottom to top
            whereas in iplotlib it is from top to bottom.

            Extra care is taken to consider row span for the specified plot.

        Args:
            r (int): a row id (0 < r < self.rows)
            c (int): a col id (0 < c < self.cols)
            plot (Plot): a plot instance. (used to consider row span)

        Returns:
            int: a valid vtk row id.
        """
        return self.rows - 1 - r - (plot.row_span - 1)

    def refresh_signal(self, signal: Signal, chart: vtkChart = None):
        """Refresh a specific signal

        Args:
            signal (Signal): An object derived from abstract iplotlib.core.signal.Signal
        """

        if not isinstance(signal, Signal):
            return

        data = signal.get_data()

        if data is None:
            return

        if len(data) < 2:
            return

        plot = self._plot_lookup.get(id(signal))
        if plot is None and chart is not None:
            # TODO: Use functional bag for envelope plots
            plot = self.add_vtk_line_plot(chart, signal.title, data[0], data[1], True)
            self._plot_lookup.update({id(signal): plot})
        else:
            self.plot_line(plot, data[0], data[1], signal.title, True)
        

    def refresh_plot(self, plot: Plot, column: int, row: int):
        """Refresh a specific plot

        Args:
            plot (Plot): An object derived from abstract iplotlib.core.plot.Plot
        Raises:
            InvalidPlotException
        """

        if not isinstance(plot, Plot):
            return

        # Invert row id for vtk
        row_id = self.get_internal_row_id(row, plot)

        # Deal with stacked charts
        stack_sz = len(plot.signals.keys())
        stacked = stack_sz > 1

        # add_chart_* fn
        get_fn = VTKCanvas.add_vtk_chart_matrix if stacked else VTKCanvas.add_vtk_chart

        # arguments to get_fn
        args = (self.matrix, column, row_id, plot.col_span, plot.row_span)

        # Add/Get a new chart/chart matrix
        element = get_fn(*args)

        if isinstance(element, vtkChartMatrix):
            element.SetSize(vtkVector2i(1, stack_sz))
            element.SetBorders(0, 0, 0, 0)

        for i, stack_id in enumerate(sorted(plot.signals.keys())):
            signals = plot.signals.get(stack_id) or []

            # Prepare or create chart in root/nested chart matrix if necessary
            chart = None
            if isinstance(element, vtkChartMatrix):
                chart = self.add_vtk_chart(element, 0, i)
            else:
                chart = element

            # Plot each signal
            for signal in signals:
                self.refresh_signal(signal, chart)

    @staticmethod
    def add_vtk_chart(matrix: vtkChartMatrix,
                      col: int = 0,
                      row: int = 0,
                      col_span: int = 1,
                      row_span: int = 1,
                      ) -> vtkChart:
        pos = vtkVector2i(col, row)
        span = vtkVector2i(col_span, row_span)
        chart = matrix.GetChart(pos)
        matrix.SetChartSpan(pos, span)
        return chart

    @staticmethod
    def add_vtk_chart_matrix(matrix: vtkChartMatrix,
                             col: int = 0,
                             row: int = 0,
                             col_span: int = 1,
                             row_span: int = 1,
                             ) -> vtkChartMatrix:
        pos = vtkVector2i(col, row)
        span = vtkVector2i(col_span, row_span)
        sub_matrix = matrix.GetChartMatrix(pos)
        matrix.SetChartSpan(pos, span)
        return sub_matrix

    def add_vtk_line_plot(self, chart: vtkChart, name: str, xdata: np.ndarray, ydata: np.ndarray, hi_prec_nanos: bool = False) -> vtkPlotLine:

        if not hasattr(xdata, "__getitem__") and not hasattr(ydata, "__getitem__"):
            return None
        else:
            plot = chart.AddPlot(vtkChart.LINE)  # type: vtkPlotLine
            self.plot_line(plot, xdata, ydata, name, hi_prec_nanos)
            plot.SetLegendVisibility(True)
            plot.SetLabel(name)
            return plot

    def plot_line(self, plot: vtkPlot,
                  x: typing.Sequence[float],
                  y: typing.Sequence[float],
                  var_name,
                  bitSequencing=False):
        if not isinstance(x, np.ndarray):
            x = np.array(x, dtype=np.float64)
        if not isinstance(y, np.ndarray):
            y = np.array(y, dtype=np.float64)
        table = vtkTable()
        xs = numpy_support.numpy_to_vtk(x)
        ys = numpy_support.numpy_to_vtk(y)
        xs.SetName("X-Axis")
        ys.SetName(var_name)
        table.AddColumn(xs)
        table.AddColumn(ys)
        if bitSequencing:
            # insert least->highest significant bits into table columns
            as16bits = x.view(np.uint16)
            bitSequences = [
                as16bits[::4],
                as16bits[1::4],
                as16bits[2::4],
                as16bits[3::4],
            ]
            for i, bitSeq in enumerate(bitSequences):
                vtkArr = numpy_support.numpy_to_vtk(bitSeq)
                vtkArr.SetName(f"Bit-Sequence: {i}")
                table.AddColumn(vtkArr)
        plot.SetInputData(table, 0, 1)

    def set_draw_style(self, plot: vtkPlot, drawstyle=None):
        table = plot.GetInput()
        c0 = table.GetColumn(0)
        c1 = table.GetColumn(1)
        xs = numpy_support.vtk_to_numpy(c0)
        ys = numpy_support.vtk_to_numpy(c1)
        numPoints = len(xs)
        var_name = c1.GetName()
        bitSequencing = table.GetNumberOfColumns() > 2

        if drawstyle is not None:
            newxs = []
            newys = []
            for i in range(numPoints - 1):
                newxs.append(xs[i])
                newys.append(ys[i])
                for newx, newy in vtkImplUtils.step_function(i, xs, ys, drawstyle):
                    newxs.append(newx)
                    newys.append(newy)
            newxs.append(xs[-1])
            newys.append(ys[-1])
            self.plot_line(plot, newxs, newys, var_name, bitSequencing)
        else:
            newxs = []
            newys = []
            for i in range(0, numPoints - 1, 2):
                newxs.append(xs[i])
                newys.append(ys[i])
            newxs.append(xs[-1])
            newys.append(ys[-1])
            self.plot_line(plot, newxs, newys, var_name, bitSequencing)
