from iplotlib.core.property_manager import PropertyManager
import numpy as np
import typing
from dataclasses import dataclass

from iplotlib.core.canvas import Canvas
from iplotlib.core.plot import Plot, PlotXY
from iplotlib.core.signal import ArraySignal, Signal
from iplotlib.impl.vtk import utils as vtkImplUtils

# needed for runtime vtk-opengl libs
import vtkmodules.vtkRenderingOpenGL2
# needed for runtime vtk-opengl libs
import vtkmodules.vtkRenderingContextOpenGL2
from vtkmodules.vtkCommonColor import vtkNamedColors
from vtkmodules.vtkCommonDataModel import vtkColor4d, vtkTable, vtkVector2i, vtkRectd, vtkRecti
from vtkmodules.vtkChartsCore import vtkAxis, vtkChartMatrix, vtkChart, vtkChartXY, vtkContextArea, vtkPlot, vtkPlotLine
from vtkmodules.vtkViewsContext2D import vtkContextView
from vtkmodules.vtkRenderingCore import vtkTextProperty
from vtkmodules.vtkRenderingContext2D import vtkContextItem, vtkContextScene, vtkMarkerUtilities, vtkPen
from vtkmodules.util import numpy_support
from vtkmodules.vtkPythonContext2D import vtkPythonItem

from iplotLogging import setupLogger as sl
logger = sl.get_logger(__name__, "DEBUG")

AXIS_MAP = [vtkAxis.BOTTOM, vtkAxis.LEFT]

class InvalidPlotException(Exception):
    def __init__(self, *args: object) -> None:
        super().__init__(*args)


class CanvasTitleItem(object):
    def __init__(self, title: str):
        self.title = title
        self.appearance = vtkTextProperty()
        self.appearance.SetFontSize(22)
        self.appearance.SetColor(0., 0., 0.)
        self.debug_rect = False

    def Initialize(self, vtkSelf):
        return True

    def Paint(self, vtkSelf, context2D):

        context2D.ApplyTextProp(self.appearance)
        bds = [0., 0., 0., 0.]  # xmin, ymin, width, height
        context2D.ComputeStringBounds(self.title, bds)
        rect = bds
        rect[0] += (0.5 * (1. - bds[2]))
        rect[1] += (0.5 * (1. - bds[3]))
        context2D.DrawStringRect(rect, self.title)

        # Draw a yellow rect to debug paint region.
        if self.debug_rect:
            pen = context2D.GetPen()

            penColor = [0, 0, 0]
            pen.GetColor(penColor)
            penWidth = pen.GetWidth()

            brush = context2D.GetBrush()
            brushColor = [0, 0, 0, 0]
            brush.GetColor(brushColor)

            pen.SetColor([200, 200, 30])
            brush.SetColor([200, 200, 30])
            brush.SetOpacity(128)

            context2D.DrawPolygon([0.0, 0.0, 1.0, 0.0, 1.0, 1.0, 0.0, 1.0], 4)

            pen.SetWidth(penWidth)
            pen.SetColor(penColor)
            brush.SetColor(brushColor[:3])
            brush.SetOpacity(brushColor[3])

        return True


@dataclass
class VTKCanvas(Canvas):
    """A concrete implementation of iplotlib.core.canvas.Canvas
    """

    def __post_init__(self):
        """Initialize underlying vtk classes.
        """
        super().__post_init__()

        self.property_manager = PropertyManager()
        self.view = vtkContextView()
        self.scene = self.view.GetScene()

        self.matrix = vtkChartMatrix()
        self.matrix.SetGutterX(50)
        self.matrix.SetGutterY(50)
        self.matrix.SetBorderTop(0)

        self.scene.AddItem(self.matrix)

        self._plot_impl_lookup = dict() # Signal -> vtkPlot
        self._plot_lookup = dict() # reverse lookup i.e, Signal -> Plot

        self._title_region = vtkContextArea()
        axisLeft = self._title_region.GetAxis(vtkAxis.LEFT)
        axisRight = self._title_region.GetAxis(vtkAxis.RIGHT)
        axisBottom = self._title_region.GetAxis(vtkAxis.BOTTOM)
        axisTop = self._title_region.GetAxis(vtkAxis.TOP)
        axisTop.SetVisible(False)
        axisRight.SetVisible(False)
        axisLeft.SetVisible(False)
        axisBottom.SetVisible(False)
        axisTop.SetMargins(0, 0)
        axisRight.SetMargins(0, 0)
        axisLeft.SetMargins(0, 0)
        axisBottom.SetMargins(0, 0)
        self._title_region.SetDrawAreaBounds(vtkRectd(0., 0., 1., 1.))
        self._title_region.SetFillViewport(False)
        self._title_region.SetShowGrid(False)
        self.scene.AddItem(self._title_region)

        self.title_scale = 0.1
        self._title_item = vtkPythonItem()
        self._py_title_item = CanvasTitleItem("")
        self._title_item.SetPythonObject(self._py_title_item)
        self._title_item.SetVisible(True)
        self._title_region.GetDrawAreaItem().AddItem(self._title_item)

        # Both elements will stretch to fill their rects.
        self.matrix.SetFillStrategy(vtkChartMatrix.StretchType.CUSTOM)
        self._title_region.SetDrawAreaResizeBehavior(
            vtkContextArea.DARB_FixedRect)

    def resize(self, w: int, h: int):
        title_height = int(self.title_scale * h)
        chart_height = h - title_height - 22  # typical window decoration height

        self._title_region.SetFixedRect(
            vtkRecti(0, chart_height, w, title_height))
        self.matrix.SetRect(vtkRecti(0, 0, w, chart_height))

    def clear(self):
        self.matrix.SetSize(vtkVector2i(0, 0))

    def refresh(self):
        """This method analyzes the iplotlib canvas data structure and maps it
        onto a vtkChartMatrix
        """
        # 1. update property hierarchy
        self.property_manager.update(self)

        # 2. Clear layout.
        self.clear()

        # 3. Allocate
        self.matrix.SetSize(vtkVector2i(self.cols, self.rows))

        # 4. Fill canvas with charts
        for i, column in enumerate(self.plots):

            j = 0

            for plot in column:

                self.refresh_plot(plot, i, j)

                # Increment row number carefully. (for next iteration)
                j += plot.row_span if isinstance(plot, Plot) else 1

        # 5. Translate pure canvas properties
        if self.title is not None:
            logger.info(f"Setting canvas title: {self.title}")
            self._py_title_item.title = self.title

        if self.font_color:
            c4d = vtkColor4d()
            vtkNamedColors().GetColor(self.font_color, c4d)

            textProp = self._py_title_item.appearance
            textProp.SetColor(c4d.GetRed(), c4d.GetGreen(), c4d.GetBlue())

            # vtkNamedColors().GetColor(self.font_bg_color, c4d)
            # textProp.SetBackgroundRGBA(c4d.GetRed(), c4d.GetGreen(), c4d.GetBlue(), c4d.GetAlpha())

            # vtkNamedColors().GetColor(self.font_frame_color, c4d)
            # textProp.SetFrameColor(c4d.GetRed(), c4d.GetGreen(), c4d.GetBlue())

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

        # acquire/update properties
        plot = self._plot_lookup.get(id(signal)) # type: Plot
        self.property_manager.acquire_signal_from_plot(plot, signal)

        # Create backend objects
        plot_impl = self._plot_impl_lookup.get(id(signal))  # type: vtkPlot
        if plot_impl is None and chart is not None:
            # TODO: Use functional bag for envelope plots
            if isinstance(signal, ArraySignal):
                plot_impl = self.add_vtk_line_plot(
                    chart, signal.title, data[0], data[1], signal.hi_precision_data)
                self._plot_impl_lookup.update({id(signal): plot_impl})
        else:
            if isinstance(signal, ArraySignal):
                self.plot_line(
                    plot_impl, data[0], data[1], signal.title, signal.hi_precision_data)

        # Translate abstract properties to backend
        plot_impl.SetLabel(signal.title)
        if isinstance(signal, ArraySignal):

            if signal.color is not None:
                plot_impl.SetColor(*vtkImplUtils.get_color4ub(signal.color))

            # line style, width if supported by hardware.
            pen = plot_impl.GetPen()
            if signal.line_size is not None:
                pen.SetWidth(signal.line_size)
            if signal.line_style == "solid":
                pen.SetLineType(vtkPen.SOLID_LINE)
            elif signal.line_style == "dashed":
                pen.SetLineType(vtkPen.DASH_LINE)
            elif signal.line_style == "dotted":
                pen.SetLineType(vtkPen.DOT_LINE)

            # marker style, size
            if signal.marker_size is not None:
                plot_impl.SetMarkerSize(signal.marker_size)
            if signal.marker == 'x':
                plot_impl.SetMarkerStyle(vtkMarkerUtilities.CROSS)
            elif signal.marker == '+':
                plot_impl.SetMarkerStyle(vtkMarkerUtilities.PLUS)
            elif signal.marker == "square":
                plot_impl.SetMarkerStyle(vtkMarkerUtilities.SQUARE)
            elif signal.marker == 'o' or signal.marker == "circle":
                plot_impl.SetMarkerStyle(vtkMarkerUtilities.CIRCLE)
            elif signal.marker == "diamond":
                plot_impl.SetMarkerStyle(vtkMarkerUtilities.DIAMOND)

            # steps
            self.set_draw_style(plot_impl, signal.step)

    def refresh_plot(self, plot: Plot, column: int, row: int):
        """Refresh a specific plot

        Args:
            plot (Plot): An object derived from abstract iplotlib.core.plot.Plot
        Raises:
            InvalidPlotException
        """

        if not isinstance(plot, Plot):
            return

        self.property_manager.acquire_plot_from_canvas(self, plot)

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

            # translate plot properties to chart
            if plot.title is not None:
                chart.SetTitle(plot.title)
                appearance = chart.GetTitleProperties() # type: vtkTextProperty
                if plot.font_color is not None:
                    appearance.SetColor(*vtkImplUtils.get_color3d(plot.font_color))
                if plot.font_size is not None:
                    appearance.SetFontSize(plot.font_size)

            if plot.legend is not None:
                chart.SetShowLegend(plot.legend)
            
            if isinstance(plot, PlotXY):
                if plot.grid is not None:
                    chart.GetAxis(vtkAxis.BOTTOM).SetGridVisible(plot.grid)
                    chart.GetAxis(vtkAxis.LEFT).SetGridVisible(plot.grid)
                for ax_id, ax in enumerate(plot.axes):
                    ax_impl = chart.GetAxis(AXIS_MAP[ax_id])
                    if plot.grid is not None:
                        ax_impl.SetGridVisible(plot.grid)
                    if ax.label is not None:
                        ax_impl.SetTitle(ax.label)
                        appearance = chart.GetTitleProperties() # type: vtkTextProperty
                        if ax.font_color is not None:
                            appearance.SetColor(*vtkImplUtils.get_color3d(ax.font_color))
                        if ax.font_size is not None:
                            appearance.SetFontSize(ax.font_size)

            # Plot each signal
            for signal in signals:
                self._plot_lookup.update({id(signal): plot})
                self.refresh_signal(signal, chart)


        if isinstance(element, vtkChartMatrix):
            element.LabelOuter(vtkVector2i(0, 0), vtkVector2i(0, stack_sz - 1))


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

        if drawstyle is None:
            return

        table = plot.GetInput()
        c0 = table.GetColumn(0)
        c1 = table.GetColumn(1)
        xs = numpy_support.vtk_to_numpy(c0)
        ys = numpy_support.vtk_to_numpy(c1)
        numPoints = len(xs)
        var_name = c1.GetName()
        bitSequencing = table.GetNumberOfColumns() > 2

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
