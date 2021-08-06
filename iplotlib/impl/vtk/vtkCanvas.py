from iplotlib.impl.vtk.tools.queryMatrix import get_charts
import numpy as np
import typing
from collections import defaultdict
from dataclasses import dataclass

from iplotlib.core.axis import Axis, LinearAxis
from iplotlib.core.canvas import Canvas
from iplotlib.core.plot import Plot, PlotXY
from iplotlib.core.signal import ArraySignal, Signal
from iplotlib.core.property_manager import PropertyManager
from iplotlib.impl.vtk import utils as vtkImplUtils
from iplotlib.impl.vtk.tools import CanvasTitleItem, CrosshairCursorWidget, VTK64BitTimePlotSupport, find_chart, find_element_index

# needed for runtime vtk-opengl libs
import vtkmodules.vtkRenderingOpenGL2
# needed for runtime vtk-opengl libs
import vtkmodules.vtkRenderingContextOpenGL2
from vtkmodules.vtkCommonDataModel import vtkTable, vtkVector2i, vtkRectd, vtkRecti
from vtkmodules.vtkChartsCore import vtkAxis, vtkChartMatrix, vtkChart, vtkChartXY, vtkContextArea, vtkPlot, vtkPlotLine, vtkPlotPoints
from vtkmodules.vtkPythonContext2D import vtkPythonItem
from vtkmodules.vtkRenderingCore import vtkTextProperty
from vtkmodules.vtkRenderingContext2D import vtkContextMouseEvent, vtkMarkerUtilities, vtkPen
from vtkmodules.vtkViewsContext2D import vtkContextView
from vtkmodules.util import numpy_support

from iplotLogging import setupLogger as sl
logger = sl.get_logger(__name__, "DEBUG")

AXIS_MAP = [vtkAxis.BOTTOM, vtkAxis.LEFT]
STEP_MAP = {"none": "none", "mid": "steps-mid", "post": "steps-post",
            "pre": "steps-pre", "steps-mid": "steps-mid", "steps-post": "steps-post", "steps-pre": "steps-pre"}


class InvalidPlotException(Exception):
    def __init__(self, *args: object) -> None:
        super().__init__(*args)


@dataclass
class VTKCanvas(Canvas):
    """A concrete implementation of iplotlib.core.canvas.Canvas
    """

    def __post_init__(self, focus_plot=None):
        """Initialize underlying vtk classes.
        """
        super().__post_init__()

        self.focus_plot = focus_plot
        self._impl_focus_plot = None
        self._focus_plot_index = vtkVector2i(-1, -1)

        self.view = vtkContextView()
        self.scene = self.view.GetScene()
        self.matrix = vtkChartMatrix()
        self.scene.AddItem(self.matrix)

        self.custom_tickers = {}
        self.crosshair = CrosshairCursorWidget(self.matrix,
                                               horizOn=True,
                                               hLineW=1,
                                               vLineW=1)
        self.property_manager = PropertyManager()

        self.matrix.SetGutterX(50)
        self.matrix.SetGutterY(50)
        self.matrix.SetBorderTop(0)

        self._abstr_plot_chart_lookup = defaultdict(list)  # Plot -> vtkChart
        self._impl_index_abstr_plot_lookup = dict()  # (c, r) -> Plot
        self._abstr_impl_plot_lookup = dict()  # Signal -> vtkPlot
        self._signal_plot_lookup = dict()  # reverse lookup i.e, Signal -> Plot

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
            self.refresh_impl_plot_data(
                plot, xdata, ydata, name, hi_prec_nanos)
            plot.SetLegendVisibility(True)
            plot.SetLabel(name)
            return plot

    def clear(self):
        self._abstr_plot_chart_lookup.clear()
        self._impl_index_abstr_plot_lookup.clear()
        self._abstr_impl_plot_lookup.clear()
        self._signal_plot_lookup.clear()
        self.matrix.SetSize(vtkVector2i(0, 0))
        self.custom_tickers.clear()
        self.crosshair.clear()

    def find_chart(self, probe: typing.Tuple) -> typing.Union[None, vtkChart]:
        """Find a chart right under the given probe position.
            This method is determined to find a chart

        Args:
            probe (typing.Tuple): Position in VTK screen coordinates.
        """
        screenToScene = self.scene.GetTransform()
        scenePos = [0, 0]
        screenToScene.TransformPoints(probe, scenePos, 1)

        return find_chart(self.matrix, scenePos)

    def find_element_index(self, probe: typing.Tuple) -> vtkVector2i:
        """Find a chart/chartmatrix right under the given probe position.
            This method is not determined to find a chart. It just returns the first element found.

        Args:
            probe (typing.Tuple): Position in VTK screen coordinates.
        """
        screenToScene = self.scene.GetTransform()
        scenePos = [0, 0]
        screenToScene.TransformPoints(probe, scenePos, 1)

        return find_element_index(self.matrix, scenePos)

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

    def hi_precision_needed(self, plot: Plot) -> bool:
        retVal = False
        for signals in plot.signals.values():
            for signal in signals:
                if isinstance(signal, ArraySignal):
                    retVal |= signal.hi_precision_data

    def refresh(self, redraw: bool = True):
        """This method analyzes the iplotlib canvas data structure and maps it
        onto a vtkChartMatrix

        The redraw flag forces a complete redraw of all plots. This clears existing canvas.
        """
        # 1. update property hierarchy
        self.property_manager.update(self)

        if redraw:
            # 2. Clear layout.
            self.clear()

            # 3. Allocate
            if self.focus_plot is not None:
                self.matrix.SetSize(vtkVector2i(1, 1))
            else:
                self.matrix.SetSize(vtkVector2i(self.cols, self.rows))

        # 4 Fill canvas with charts
        stop_drawing = False
        for i, column in enumerate(self.plots):

            j = 0

            for plot in column:

                if self.focus_plot is not None:
                    if self.focus_plot == plot:
                        self.refresh_plot(plot, 0, 0)
                        stop_drawing = True
                        break
                elif self.focus_plot is None:
                    self.refresh_plot(plot, i, j)

                # Increment row number carefully. (for next iteration)
                j += plot.row_span if isinstance(plot, Plot) else 1

            if stop_drawing:
                break

        # 5 Refresh mouse mode
        self.refresh_mouse_mode(self.mouse_mode)
        self.refresh_crosshair_widget()

        # 6. Canvas title
        self.refresh_canvas_title()

    def refresh_axes(self, plot: Plot):
        """Refresh a plot's axes

        Args:
            plot (Plot): An abstract Plot object
            chart (vtkChart): The chart whose axes will be refreshed
            ax (Axis): An abstract Axis object
            ax_id (int): The index of the ax object in Plot.axes
        """
        for chart in self._abstr_plot_chart_lookup[id(plot)]:
            for ax_id, ax in enumerate(plot.axes):
                ax_impl_id = AXIS_MAP[ax_id]
                ax_impl = chart.GetAxis(ax_impl_id)

                if isinstance(ax, Axis):
                    if ax.label is not None:
                        ax_impl.SetTitle(ax.label)

                    appearance = ax_impl.GetTitleProperties()  # type: vtkTextProperty
                    if ax.font_color is not None:
                        appearance.SetColor(
                            *vtkImplUtils.get_color3d(ax.font_color))
                        logger.debug(
                            f"Ax color: {vtkImplUtils.get_color3d(ax.font_color)}")
                    if ax.font_size is not None:
                        appearance.SetFontSize(ax.font_size)

    def refresh_canvas_title(self):
        """Updates canvas title text and the appearance
        """
        if self.title is not None:
            logger.debug(f"Setting canvas title: {self.title}")
            self._py_title_item.title = self.title

        if self.font_color:
            textProp = self._py_title_item.appearance
            textProp.SetColor(*vtkImplUtils.get_color3d(self.font_color))
            # textProp.SetBackgroundRGBA(*vtkImplUtils.get_color4d(self.font_bg_color))
            # textProp.SetFrameColor(*vtkImplUtils.get_color3d(self.font_frame_color))

    def remove_crosshair_widget(self):
        self.crosshair.clear()

    def refresh_crosshair_widget(self):
        self.crosshair.clear()
        
        if not self.crosshair_enabled:
            return
        if isinstance(self._impl_focus_plot, vtkChart):
            self.crosshair.charts.append(self._impl_focus_plot)
        elif isinstance(self._impl_focus_plot, vtkChartMatrix):
            get_charts(self._impl_focus_plot, self.crosshair.charts)
        else:
            get_charts(self.matrix, self.crosshair.charts)

        self.crosshair.resize()

        for cursor, _ in self.crosshair.cursors:  # type: CrosshairCursor,
            cursor.lc['h'] = self.crosshair_color
            cursor.lc['v'] = self.crosshair_color
            cursor.lw['h'] = self.crosshair_line_width
            cursor.lw['v'] = self.crosshair_line_width
            cursor.lv['h'] = self.crosshair_horizontal
            cursor.lv['v'] = self.crosshair_vertical

    def refresh_custom_ticker(self, ax_id: int, plot: Plot, chart: vtkChartXY):
        ax_impl_id = AXIS_MAP[ax_id]
        ax_impl = chart.GetAxis(ax_impl_id)
        ax = plot.axes[ax_id]

        if isinstance(ax, LinearAxis):
            # date time ticking
            if ax_impl_id == vtkAxis.BOTTOM:
                # translate LinearAxis properties
                if not self.custom_tickers.get(id(chart)):
                    self.custom_tickers.update(
                        {id(chart): VTK64BitTimePlotSupport()})
                    ax_impl.AddObserver(
                        vtkChart.UpdateRange, self.custom_tickers[id(chart)].generateTics)

                # type: VTK64BitTimePlotSupport
                ticker = self.custom_tickers.get(id(chart))
                if ax.is_date:
                    ticker.enable()
                else:
                    ticker.disable()

        # handle high precision data for nanosecond timestamps
        # type: VTK64BitTimePlotSupport
        ticker = self.custom_tickers.get(id(chart))
        if ticker is not None:
            if self.hi_precision_needed(plot):
                ticker.precisionOn()
            else:
                ticker.precisionOff()

    def refresh_grid(self, plot: Plot):
        """Update grid visibility

        Args:
            plot (Plot): An abstract plot object
        """
        for chart in self._abstr_plot_chart_lookup[id(plot)]:
            if isinstance(plot, PlotXY):
                if plot.grid is not None:
                    chart.GetAxis(vtkAxis.BOTTOM).SetGridVisible(plot.grid)
                    chart.GetAxis(vtkAxis.LEFT).SetGridVisible(plot.grid)

    def refresh_legend(self, plot):
        """Update legend visibility

        Args:
            plot (Plot): An abstract plot object
        """
        for chart in self._abstr_plot_chart_lookup[id(plot)]:
            if plot.legend is not None:
                chart.SetShowLegend(plot.legend)

    def refresh_line_size(self, signal: ArraySignal):
        impl_plot = self._abstr_impl_plot_lookup.get(
            id(signal))  # type: vtkPlot
        # line style, width if supported by hardware.
        pen = impl_plot.GetPen()
        if signal.line_size is not None:
            pen.SetWidth(signal.line_size)

    def refresh_line_style(self, signal: ArraySignal):
        impl_plot = self._abstr_impl_plot_lookup.get(
            id(signal))  # type: vtkPlot
        # line style, width if supported by hardware.
        pen = impl_plot.GetPen()
        if signal.line_style is None:
            return
        elif signal.line_style.lower() == "None":
            pen.SetLineType(vtkPen.NO_PEN)
        elif signal.line_style.lower() == "solid":
            pen.SetLineType(vtkPen.SOLID_LINE)
        elif signal.line_style.lower() == "dashed":
            pen.SetLineType(vtkPen.DASH_LINE)
        elif signal.line_style.lower() == "dotted":
            pen.SetLineType(vtkPen.DOT_LINE)

    def refresh_marker_size(self, signal: ArraySignal):
        impl_plot = self._abstr_impl_plot_lookup.get(
            id(signal))  # type: vtkPlot
        # marker style, size
        if signal.marker_size is not None:
            impl_plot.SetMarkerSize(signal.marker_size)

    def refresh_marker_style(self, signal: ArraySignal):
        impl_plot = self._abstr_impl_plot_lookup.get(
            id(signal))  # type: vtkPlot
        if signal.marker == 'x':
            impl_plot.SetMarkerStyle(vtkMarkerUtilities.CROSS)
        elif signal.marker == '+':
            impl_plot.SetMarkerStyle(vtkMarkerUtilities.PLUS)
        elif signal.marker == "square":
            impl_plot.SetMarkerStyle(vtkMarkerUtilities.SQUARE)
        elif signal.marker == 'o' or signal.marker == "circle":
            impl_plot.SetMarkerStyle(vtkMarkerUtilities.CIRCLE)
        elif signal.marker == "diamond":
            impl_plot.SetMarkerStyle(vtkMarkerUtilities.DIAMOND)

    def refresh_mouse_mode(self, mode: str):
        """Refresh mouse mode across all charts
        """
        self.mouse_mode = mode
        self.crosshair_enabled = self.mouse_mode == Canvas.MOUSE_MODE_CROSSHAIR

        for _, charts in self._abstr_plot_chart_lookup.items():
            for chart in charts:

                # Mouse mode handled for each chart.
                chart.SetActionToButton(
                    vtkChart.PAN, vtkContextMouseEvent.NO_BUTTON)
                chart.SetActionToButton(
                    vtkChart.ZOOM, vtkContextMouseEvent.NO_BUTTON)
                chart.SetActionToButton(
                    vtkChart.ZOOM_AXIS, vtkContextMouseEvent.NO_BUTTON)
                chart.SetActionToButton(
                    vtkChart.SELECT, vtkContextMouseEvent.NO_BUTTON)
                chart.SetActionToButton(
                    vtkChart.SELECT_RECTANGLE, vtkContextMouseEvent.NO_BUTTON)
                chart.SetActionToButton(
                    vtkChart.CLICK_AND_DRAG, vtkContextMouseEvent.NO_BUTTON)

                if self.mouse_mode == Canvas.MOUSE_MODE_PAN:
                    chart.SetActionToButton(
                        vtkChart.PAN, vtkContextMouseEvent.LEFT_BUTTON)
                elif self.mouse_mode == Canvas.MOUSE_MODE_SELECT:
                    chart.SetActionToButton(
                        vtkChart.SELECT, vtkContextMouseEvent.LEFT_BUTTON)
                elif self.mouse_mode == Canvas.MOUSE_MODE_ZOOM:
                    chart.SetActionToButton(
                        vtkChart.ZOOM, vtkContextMouseEvent.LEFT_BUTTON)
                elif self.mouse_mode == Canvas.MOUSE_MODE_CROSSHAIR:
                    pass
                else:
                    logger.warning(
                        f"Invalide canvas mouse mode: {self.mouse_mode}")

                # Turn off zoom with mouse wheel.
                if isinstance(chart, vtkChartXY):
                    chart.ZoomWithMouseWheelOff()

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
        self._impl_index_abstr_plot_lookup.update({(column, row_id): plot})

        if self.focus_plot == plot:
            row_id = 0

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
            element.SetGutterX(0)
            element.SetGutterY(0)

        for i, stack_id in enumerate(sorted(plot.signals.keys())):
            signals = plot.signals.get(stack_id) or []

            # Prepare or create chart in root/nested chart matrix if necessary
            chart = None
            if isinstance(element, vtkChartMatrix):
                chart = self.add_vtk_chart(element, 0, i)
            elif isinstance(element, vtkChart):
                chart = element
            else:
                logger.critical(f"Unexpected path in refresh_plot {column}, {row}, {row_id}")

            self.refresh_custom_ticker(0, plot, chart)
            self._abstr_plot_chart_lookup[id(plot)].append(chart)

            # Plot each signal
            for signal in signals:
                self._signal_plot_lookup.update({id(signal): plot})
                self.refresh_signal(signal, chart)

        if isinstance(element, vtkChartMatrix):
            element.LabelOuter(vtkVector2i(0, 0), vtkVector2i(0, stack_sz - 1))

        # translate plot properties to chart
        self.refresh_plot_titles(plot)
        self.refresh_legend(plot)

        # translate Axis properties
        self.refresh_axes(plot)

        # translate PlotXY properties to chart
        self.refresh_grid(plot)

    def refresh_impl_plot_data(self, plot: vtkPlot,
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

    def refresh_plot_titles(self, plot):
        """Update plot title text and its appearance
        """
        # Deal with stacked charts
        stack_sz = len(plot.signals.keys())
        stacked = stack_sz > 1

        for i, chart in enumerate(self._abstr_plot_chart_lookup[id(plot)]):
            draw_title = not stacked or (stacked and i == stack_sz - 1)
            if (plot.title is not None) and draw_title:
                chart.SetTitle(plot.title)
                appearance = chart.GetTitleProperties()  # type: vtkTextProperty
                if plot.font_color is not None:
                    appearance.SetColor(
                        *vtkImplUtils.get_color3d(plot.font_color))
                if plot.font_size is not None:
                    appearance.SetFontSize(plot.font_size)

    def refresh_signal(self, signal: Signal, chart: vtkChart):
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
        plot = self._signal_plot_lookup.get(id(signal))  # type: Plot
        self.property_manager.acquire_signal_from_plot(plot, signal)
        hi_precision = self.hi_precision_needed(plot)

        # Create backend objects
        impl_plot = self._abstr_impl_plot_lookup.get(
            id(signal))  # type: vtkPlot
        if impl_plot is None and chart is not None:
            # TODO: Use functional bag for envelope plots
            if isinstance(signal, ArraySignal):
                impl_plot = self.add_vtk_line_plot(
                    chart, signal.title, data[0], data[1], hi_precision)
                self._abstr_impl_plot_lookup.update({id(signal): impl_plot})
        else:
            if isinstance(signal, ArraySignal):
                self.refresh_impl_plot_data(
                    impl_plot, data[0], data[1], signal.title, hi_precision)

        # Translate abstract properties to backend
        self.refresh_signal_title(signal)
        self.refresh_signal_color(signal)

        if isinstance(signal, ArraySignal):
            self.refresh_line_size(signal)
            self.refresh_line_style(signal)
            self.refresh_marker_size(signal)
            self.refresh_marker_style(signal)
            self.refresh_step_type(signal)

    def refresh_signal_color(self, signal: ArraySignal):
        impl_plot = self._abstr_impl_plot_lookup.get(
            id(signal))  # type: vtkPlot
        if signal.color is not None:
            impl_plot.SetColor(*vtkImplUtils.get_color4ub(signal.color))

    def refresh_signal_title(self, signal: Signal):
        impl_plot = self._abstr_impl_plot_lookup.get(
            id(signal))  # type: vtkPlot
        impl_plot.SetLabel(signal.title)

    def refresh_step_type(self, signal: ArraySignal):
        impl_plot = self._abstr_impl_plot_lookup.get(
            id(signal))  # type: vtkPlot

        if signal.step is None:
            return

        step_type = STEP_MAP[signal.step.lower()]
        if step_type not in ["none", "steps", "steps-pre", "steps-post", "steps-mid"]:
            logger.warning(
                f"Steps type: {signal.step} for {id(signal)} is not recognized!")
            return

        table = impl_plot.GetInput()
        c0 = table.GetColumn(0)
        c1 = table.GetColumn(1)
        xs = numpy_support.vtk_to_numpy(c0)
        ys = numpy_support.vtk_to_numpy(c1)
        numPoints = len(xs)
        var_name = c1.GetName()
        bitSequencing = table.GetNumberOfColumns() > 2

        newxs = []
        newys = []
        if step_type != "none":
            for i in range(numPoints - 1):
                newxs.append(xs[i])
                newys.append(ys[i])
                for newx, newy in vtkImplUtils.step_function(i, xs, ys, step_type):
                    newxs.append(newx)
                    newys.append(newy)
            newxs.append(xs[-1])
            newys.append(ys[-1])
        else:
            for i in range(0, numPoints - 1, 2):
                newxs.append(xs[i])
                newys.append(ys[i])
            newxs.append(xs[-1])
            newys.append(ys[-1])

        self.refresh_impl_plot_data(
            impl_plot, newxs, newys, var_name, bitSequencing)

    def resize(self, w: int, h: int):
        title_height = int(self.title_scale * h)
        chart_height = h - title_height - 22  # typical window decoration height

        self._title_region.SetFixedRect(
            vtkRecti(0, chart_height, w, title_height))
        self.matrix.SetRect(vtkRecti(0, 0, w, chart_height))

    def set_focus_plot(self, index: vtkVector2i):
        if index.GetX() < 0 or index.GetY() < 0:
            logger.debug("Nothing to focus")
            return

        if self.focus_plot is None:
            logger.debug(f"Set focus chart @ internal index : {index}")
            self.focus_plot = self._impl_index_abstr_plot_lookup.get((index[0], index[1]))
        else:
            logger.debug("Set focus chart -> None")
            self.focus_plot = None
