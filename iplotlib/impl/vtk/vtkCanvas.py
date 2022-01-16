import numpy as np
from dataclasses import dataclass
from typing import Any, Callable, Collection, Sequence, Tuple, Union

from iplotlib.core import (Axis,
                           LinearAxis,
                           RangeAxis,
                           BackendParserBase,
                           Canvas,
                           Plot,
                           PlotXY,
                           ArraySignal,
                           Signal)

from iplotlib.impl.vtk import utils as vtkImplUtils
from iplotlib.impl.vtk.tools import CanvasTitleItem, CrosshairCursorWidget, VTK64BitTimePlotSupport, queryMatrix

# needed for runtime vtk-opengl libs
import vtkmodules.vtkRenderingOpenGL2
# needed for runtime vtk-opengl libs
import vtkmodules.vtkRenderingContextOpenGL2
from vtkmodules.vtkCommonDataModel import vtkTable, vtkVector2i, vtkRectd, vtkRecti
from vtkmodules.vtkChartsCore import vtkAxis, vtkChartMatrix, vtkChart, vtkChartXY, vtkContextArea, vtkPlot, vtkPlotLine, vtkPlotPoints
from vtkmodules.vtkPythonContext2D import vtkPythonItem
from vtkmodules.vtkRenderingCore import vtkTextProperty, vtkRenderWindow
from vtkmodules.vtkRenderingContext2D import vtkContextMouseEvent, vtkMarkerUtilities, vtkPen
from vtkmodules.vtkViewsContext2D import vtkContextView
from vtkmodules.util import numpy_support

from iplotLogging import setupLogger as sl
logger = sl.get_logger(__name__)

AXIS_MAP = [vtkAxis.BOTTOM, vtkAxis.LEFT]
STEP_MAP = {"none": "none", "mid": "steps-mid", "post": "steps-post",
            "pre": "steps-pre", "steps-mid": "steps-mid", "steps-post": "steps-post", "steps-pre": "steps-pre"}


@dataclass
class VTKParser(BackendParserBase):
    """This class parses the core iplotlib classes into a VTK charts pipeline.
    """
    def __init__(self, canvas: Canvas = None, focus_plot=None, focus_plot_stack_key=None, impl_flush_method: Callable = None) -> None:
        """Initialize underlying vtk classes.
        """
        super().__init__(canvas=canvas, focus_plot=focus_plot, focus_plot_stack_key=focus_plot_stack_key, impl_flush_method=impl_flush_method)
        self._impl_focus_plot = None
        self._focus_plot_index = vtkVector2i(-1, -1)

        self.view = vtkContextView()
        self.scene = self.view.GetScene()
        self._layout = vtkChartMatrix()
        self.scene.AddItem(self._layout)
        self._matrix = self._layout

        self._vtk_custom_tickers = {}
        self.crosshair = CrosshairCursorWidget(self._layout,
                                               horizOn=True,
                                               hLineW=1,
                                               vLineW=1)
        self._layout.SetGutterX(50)
        self._layout.SetGutterY(50)
        self._layout.SetBorderTop(0)

        self._vtk_col_row_plot_lut = dict()  # (c, r) -> Plot

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
        self._layout.SetFillStrategy(vtkChartMatrix.StretchType.CUSTOM)
        self._title_region.SetDrawAreaResizeBehavior(
            vtkContextArea.DARB_FixedRect)

    @property
    def matrix(self):
        return self._matrix

    def export_image(self, filename: str, **kwargs):
        super().export_image(filename, **kwargs)
        renWin = vtkRenderWindow()
        dpi = kwargs.get("dpi") or 100
        width_i = kwargs.get("width") or 18.4
        height_i = kwargs.get("height") or 10.5
        width = int(dpi * width_i)
        height = int(dpi * height_i)
        renWin.SetSize(width, height)
        self.resize(width, height)
        renWin.SetDPI(dpi)

        self.view.SetRenderWindow(renWin)
        renWin.GetInteractor().Initialize()
        self.refresh(self.canvas)
        renWin.GetInteractor().Render()
        vtkImplUtils.screenshot(self.view.GetRenderWindow(), filename)

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

        line = chart.AddPlot(vtkChart.LINE)  # type: vtkPlotLine
        self.refresh_impl_plot_data(
            line, xdata, ydata, name, hi_prec_nanos)
        line.SetLegendVisibility(True)
        line.SetLabel(name)
        return line

    def clear(self):
        for charts in self._plot_impl_plot_lut.values():
            for chart in charts:
                for i in range(2):
                    vtk_axis = self.get_impl_axis(chart, i)
                    vtk_axis.RemoveObserver(vtkChart.UpdateRange)
                chart.RemoveObserver(vtkChart.UpdateRange)
        self._vtk_col_row_plot_lut.clear()
        self._layout.SetSize(vtkVector2i(0, 0))
        self._vtk_custom_tickers.clear()
        self.crosshair.clear()
        super().clear()

    def find_chart(self, probe: Tuple) -> Union[None, vtkChart]:
        """Find a chart right under the given probe position.
            This method is determined to find a chart

        Args:
            probe (Tuple): Position in VTK screen coordinates.
        """
        screenToScene = self.scene.GetTransform()
        scenePos = [0, 0]
        screenToScene.TransformPoints(probe, scenePos, 1)

        return queryMatrix.find_chart(self._layout, scenePos)

    def find_element_index(self, probe: Tuple) -> vtkVector2i:
        """Find a chart/chartmatrix right under the given probe position.
            This method is not determined to find a chart. It just returns the first element found.

        Args:
            probe (Tuple): Position in VTK screen coordinates.
        """
        screenToScene = self.scene.GetTransform()
        scenePos = [0, 0]
        screenToScene.TransformPoints(probe, scenePos, 1)

        return queryMatrix.find_element_index(self._layout, scenePos)

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
        if not self.canvas.rows:
            return -1
        r_id = self.canvas.rows - 1 - r - (plot.row_span - 1)
        r_id = 0 if r_id < 0 else r_id
        return r_id

    def hi_precision_needed(self, plot: Plot) -> bool:
        retVal = False
        for signals in plot.signals.values():
            for signal in signals:
                if isinstance(signal, ArraySignal):
                    retVal |= self._pm.get_value(
                        'hi_precision_data', self.canvas, plot, signal=signal)
        return retVal

    def process_ipl_canvas(self, canvas: Canvas):
        """This method analyzes the iplotlib canvas data structure and maps it
        onto an internal vtkChartMatrix instance

        """
        super().process_ipl_canvas(canvas)
        if canvas is None:
            self.canvas = canvas
            self.clear()
            return
    
        # 1. Clear layout.
        self.clear()
        self.canvas = canvas

        # 2. Allocate
        if self._focus_plot is not None:
            self._layout.SetSize(vtkVector2i(1, 1))
        else:
            self._layout.SetSize(vtkVector2i(canvas.cols, canvas.rows))

        # 3. Fill canvas with charts
        stop_drawing = False
        for i, column in enumerate(canvas.plots):

            j = 0

            for plot in column:

                if self._focus_plot is not None:
                    if self._focus_plot == plot:
                        logger.debug(f"Focusing on plot: {plot}")
                        self.process_ipl_plot(plot, 0, 0)
                        stop_drawing = True
                        break
                else:
                    self.process_ipl_plot(plot, i, j)

                # Increment row number carefully. (for next iteration)
                j += plot.row_span if isinstance(plot, Plot) else 1

            if stop_drawing:
                break

        # 4. Update the title at the top of canvas.
        self._refresh_canvas_title(canvas.title, canvas.font_color or '#000000')

    def process_ipl_plot(self, plot: Plot, column: int, row: int):
        """Refresh a specific plot

        Args:
            plot (Plot): An object derived from abstract iplotlib.core.plot.Plot
        """
        super().process_ipl_plot(plot, column, row)
        if not isinstance(plot, Plot):
            return

        # Invert row id for vtk
        row_id = self.get_internal_row_id(row, plot)
        self._vtk_col_row_plot_lut.update({(column, row_id): plot})

        if self._focus_plot == plot:
            row_id = 0

        # Deal with stacked charts
        if not self.canvas.full_mode_all_stack and self._focus_plot_stack_key is not None:
            stack_sz = 1
        else:
            stack_sz = len(plot.signals.keys())
        stacked = stack_sz > 1

        # add_chart_* fn
        create_chart_func = VTKParser.add_vtk_chart_matrix if stacked else VTKParser.add_vtk_chart

        # arguments to `create_chart_func`
        args = (self._layout, column, row_id, plot.col_span, plot.row_span)

        # Add/Get a new chart/chart matrix
        element = create_chart_func(*args)

        if isinstance(element, vtkChartMatrix):
            element.SetSize(vtkVector2i(1, stack_sz))
            element.SetBorders(0, 0, 0, 0)
            element.SetGutterX(0)
            element.SetGutterY(0)

        for stack_id, key in enumerate(sorted(plot.signals.keys())):
            is_stack_plot_focused = self._focus_plot_stack_key == key

            if not self.canvas.full_mode_all_stack and self._focus_plot_stack_key is not None or is_stack_plot_focused:
                row_id = 0
            else:
                row_id = stack_id
            signals = plot.signals.get(key) or []

            # Prepare or create chart in root/nested chart matrix if necessary
            chart = None
            if isinstance(element, vtkChartMatrix):
                chart = self.add_vtk_chart(element, 0, row_id)
            elif isinstance(element, vtkChart):
                chart = element
            else:
                logger.critical(
                    f"Unexpected code path in process_ipl_plot {column}, {row}, {row_id}")

            self._plot_impl_plot_lut[id(plot)].append(chart)
            # Keep references to iplotlib instances for ease of access in callbacks.
            self._impl_plot_cache_table.register(chart, self.canvas, plot, key, signals)
            self._refresh_custom_ticker(0, plot, chart)

            # translate Axis properties
            for ax_idx in range(len(plot.axes)):
                if isinstance(plot.axes[ax_idx], Collection):
                    axis = plot.axes[ax_idx][stack_id]
                    self.process_ipl_axis(axis, ax_idx, plot, chart)
                else:
                    axis = plot.axes[ax_idx]
                    self.process_ipl_axis(axis, ax_idx, plot, chart)

            # Plot each signal
            for signal in signals:
                self._signal_impl_plot_lut.update({id(signal): chart})
                self.process_ipl_signal(signal)

        if isinstance(element, vtkChartMatrix):
            element.LabelOuter(vtkVector2i(0, 0), vtkVector2i(0, stack_sz - 1))

        # translate plot properties to chart
        self._refresh_plot_title(plot)
        self._refresh_legend(plot)

        # translate PlotXY properties to chart
        self._refresh_grid(plot)

    def process_ipl_axis(self, axis: Axis, ax_idx: int, plot: Plot, impl_plot: vtkChart):
        super().process_ipl_axis(axis, ax_idx, plot, impl_plot)
        vtk_axis = impl_plot.GetAxis(vtkAxis.LEFT if ax_idx == 1 else vtkAxis.BOTTOM)
        self._axis_impl_plot_lut.update({id(axis): impl_plot})
        vtk_axis.AddObserver(vtkChart.UpdateRange, self._axis_update_callback)

        if isinstance(axis, Axis):
            if axis.label is not None:
                vtk_axis.SetTitle(axis.label)

            appearance = vtk_axis.GetTitleProperties()  # type: vtkTextProperty
            fc = self._pm.get_value('font_color', self.canvas, axis, plot)
            fs = self._pm.get_value('font_size', self.canvas, axis, plot)
            if fc is not None:
                appearance.SetColor(*vtkImplUtils.get_color3d(fc))
                logger.debug(f"Ax color: {vtkImplUtils.get_color3d(fc)}")
            if fs is not None:
                appearance.SetFontSize(fs)
        if isinstance(axis, RangeAxis) and not (isinstance(axis, LinearAxis) and axis.follow):
            if axis.begin is not None and axis.end is not None:
                self.set_oaw_axis_limits(impl_plot, ax_idx, [axis.begin, axis.end])
            vtk_axis.AutoScale()
        if isinstance(axis, LinearAxis):
            if axis.window is not None and not axis.follow:
                ax_max = self.get_oaw_axis_limits(impl_plot, ax_idx)[1]
                self.set_oaw_axis_limits(impl_plot, ax_idx, [ax_max - axis.window, ax_max])
                vtk_axis.AutoScale()

    def post_render(self):
        for charts in self._plot_impl_plot_lut.values():
            for chart in charts:
                self.get_impl_x_axis(chart).AddObserver(vtkChart.UpdateRange, self._axis_update_callback)
                self.get_impl_y_axis(chart).AddObserver(vtkChart.UpdateRange, self._axis_update_callback)

    def _axis_update_callback(self, obj, ev):
        impl_plot = obj.GetParent() # type: vtkChart
        has_shared_charts = isinstance(impl_plot.GetParent().GetParent(), vtkChartMatrix)
        affected_charts = [impl_plot]
        if self.canvas.shared_x_axis:
            for charts in self._plot_impl_plot_lut.values():
                for chart in charts:
                    if chart not in affected_charts:
                        affected_charts.append(chart)
        elif has_shared_charts:
            parent_matrix = impl_plot.GetParent()
            size = parent_matrix.GetSize()
            for c in range(size.GetX()):
                for r in range(size.GetY()):
                    chart_ = parent_matrix.GetChart(vtkVector2i(c, r))
                    if chart_ not in affected_charts:
                        affected_charts.append(chart_)

        for chart in affected_charts:
            xlims = self.get_oaw_axis_limits(chart, 0)
            ylims = self.get_oaw_axis_limits(chart, 1)
            ranges_hash = hash((*xlims, *ylims))
            current_hash = self._impl_plot_ranges_hash.get(id(chart))

            if current_hash is not None and (ranges_hash == current_hash):
                continue

            self._impl_plot_ranges_hash[id(chart)] = ranges_hash
            ranges = []

            ci = self._impl_plot_cache_table.get_cache_item(chart)
            if not hasattr(ci, 'plot'):
                continue
            if not isinstance(ci.plot(), Plot):
                continue

            for ax_idx, ax in enumerate(ci.plot().axes):
                if isinstance(ax, Collection):
                    ranges.append(self.update_multi_range_axis(ax, ax_idx, chart))
                elif isinstance(ax, RangeAxis):
                    self.update_range_axis(ax, ax_idx, chart)
                    ranges.append([ax.begin, ax.end])

            if not hasattr(ci, 'signals'):
                continue
            if not ci.signals:
                continue
            
            for signal_ref in ci.signals:
                signal = signal_ref()
                if hasattr(signal, "set_ranges"):
                    signal.set_ranges([ranges[0], ranges[1]])
            if not self.hi_precision_needed(ci.plot()):
                self._stale_impl_plots.add(chart)
        

    def set_impl_plot_limits(self, impl_plot: Any, ax_idx: int, limits: tuple) -> bool:
        if not isinstance(impl_plot, vtkChart):
            return False
        self.set_oaw_axis_limits(impl_plot, ax_idx, limits)
        return True

    def _refresh_canvas_title(self, title: str, font_color: str):
        """Updates canvas title text and the appearance
        """
        if title is not None:
            logger.debug(f"Setting canvas title: {title}")
            self._py_title_item.title = title

        if font_color:
            textProp = self._py_title_item.appearance
            textProp.SetColor(*vtkImplUtils.get_color3d(font_color))
            # textProp.SetBackgroundRGBA(*vtkImplUtils.get_color4d(self.font_bg_color))
            # textProp.SetFrameColor(*vtkImplUtils.get_color3d(self.font_frame_color))

    def remove_crosshair_widget(self):
        self.crosshair.clear()

    def refresh_crosshair_widget(self):
        if not isinstance(self.canvas, Canvas):
            return
        if not self.canvas.crosshair_enabled:
            return

        if isinstance(self._impl_focus_plot, vtkChart):
            self.crosshair.charts.append(self._impl_focus_plot)
        elif isinstance(self._impl_focus_plot, vtkChartMatrix):
            queryMatrix.get_charts(self._impl_focus_plot,
                                   self.crosshair.charts)
        else:
            queryMatrix.get_charts(self._layout, self.crosshair.charts)

        self.crosshair.resize()

        for cursor, _ in self.crosshair.cursors:  # type: CrosshairCursor,
            cursor.lc['h'] = self.canvas.crosshair_color
            cursor.lc['v'] = self.canvas.crosshair_color
            cursor.lw['h'] = self.canvas.crosshair_line_width
            cursor.lw['v'] = self.canvas.crosshair_line_width
            cursor.lv['h'] = self.canvas.crosshair_horizontal
            cursor.lv['v'] = self.canvas.crosshair_vertical

    def _refresh_custom_ticker(self, ax_id: int, plot: Plot, chart: vtkChartXY):
        ax_impl_id = AXIS_MAP[ax_id]
        vtk_axis = chart.GetAxis(ax_impl_id)
        ax = plot.axes[ax_id]

        if isinstance(ax, LinearAxis):
            # date time ticking
            if ax_impl_id == vtkAxis.BOTTOM:
                # translate LinearAxis properties
                if not self._vtk_custom_tickers.get(id(chart)):
                    self._vtk_custom_tickers.update(
                        {id(chart): VTK64BitTimePlotSupport()})
                    vtk_axis.AddObserver(
                        vtkChart.UpdateRange, self._vtk_custom_tickers[id(chart)].generateTics)

                # type: VTK64BitTimePlotSupport
                ticker = self._vtk_custom_tickers.get(id(chart))
                if ax.is_date:
                    ticker.enable()
                else:
                    ticker.disable()

        # handle high precision data for nanosecond timestamps
        # type: VTK64BitTimePlotSupport
        ticker = self._vtk_custom_tickers.get(id(chart))
        if ticker is not None:
            if self.hi_precision_needed(plot):
                ticker.precisionOn()
            else:
                ticker.precisionOff()

    def _refresh_grid(self, plot: Plot):
        """Update grid visibility

        Args:
            plot (Plot): An abstract plot object
        """
        for chart in self._plot_impl_plot_lut[id(plot)]:
            if isinstance(plot, PlotXY):
                grid = self._pm.get_value('grid', self.canvas, plot)
                if grid is not None:
                    chart.GetAxis(vtkAxis.BOTTOM).SetGridVisible(grid)
                    chart.GetAxis(vtkAxis.LEFT).SetGridVisible(grid)

    def _refresh_legend(self, plot: Plot):
        """Update legend visibility

        Args:
            plot (Plot): An abstract plot object
        """
        for chart in self._plot_impl_plot_lut[id(plot)]:
            legend = self._pm.get_value('legend', self.canvas, plot)
            if legend is not None:
                chart.SetShowLegend(legend)

    def refresh_mouse_mode(self, mmode: str):
        """Refresh mouse mmode across all charts
        """
        if not isinstance(self.canvas, Canvas):
            return

        self.canvas.crosshair_enabled = mmode == Canvas.MOUSE_MODE_CROSSHAIR

        for _, charts in self._plot_impl_plot_lut.items():
            for chart in charts:

                # Turn on zoom with mouse wheel.
                if isinstance(chart, vtkChartXY):
                    chart.ZoomWithMouseWheelOn()

                # Mouse mmode handled for each chart.
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

                if mmode == Canvas.MOUSE_MODE_PAN:
                    chart.SetActionToButton(
                        vtkChart.PAN, vtkContextMouseEvent.LEFT_BUTTON)
                elif mmode == Canvas.MOUSE_MODE_SELECT:
                    chart.SetActionToButton(
                        vtkChart.SELECT, vtkContextMouseEvent.LEFT_BUTTON)
                elif mmode == Canvas.MOUSE_MODE_ZOOM:
                    chart.SetActionToButton(
                        vtkChart.ZOOM, vtkContextMouseEvent.LEFT_BUTTON)
                    # Turn off zoom with mouse wheel.
                    if isinstance(chart, vtkChartXY):
                        chart.ZoomWithMouseWheelOff()
                elif mmode == Canvas.MOUSE_MODE_CROSSHAIR:
                    pass
                else:
                    logger.warning(
                        f"Invalide canvas mouse mode: {self.canvas.mouse_mode}")

    def refresh_impl_plot_data(self, plot: vtkPlot,
                               x: Sequence[float],
                               y: Sequence[float],
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

    def _refresh_plot_title(self, plot: Plot):
        """Update plot title text and its appearance
        """
        # Deal with stacked charts
        stack_sz = len(plot.signals.keys())
        stacked = stack_sz > 1

        for i, chart in enumerate(self._plot_impl_plot_lut[id(plot)]):
            draw_title = not stacked or (stacked and i == stack_sz - 1)
            if (plot.title is not None) and draw_title:
                chart.SetTitle(plot.title)
                appearance = chart.GetTitleProperties()  # type: vtkTextProperty
                fc = self._pm.get_value('font_color', self.canvas, plot)
                fs = self._pm.get_value('font_size', self.canvas, plot)
                if fc is not None:
                    appearance.SetColor(*vtkImplUtils.get_color3d(fc))
                if fs is not None:
                    appearance.SetFontSize(fs)

    def process_ipl_signal(self, signal: Signal):
        """Refresh a specific signal

        Args:
            signal (Signal): An object derived from abstract iplotlib.core.signal.Signal
        """
        super().process_ipl_signal(signal)
        if not isinstance(signal, Signal):
            return

        chart = self._signal_impl_plot_lut.get(id(signal))  # type: vtkChart

        data = signal.get_data()
        ndims = len(data)
        
        try:
            ci = self._impl_plot_cache_table.get_cache_item(chart)
            plot = ci.plot()
        except AttributeError:
            return
        hi_prec_nanos = self.hi_precision_needed(plot)
    
        if hasattr(signal, 'envelope') and signal.envelope:
            if ndims != 3:
                logger.error(
                    f"Requested to draw envelope for sig({id(signal)}), but it does not have sufficient data arrays (==3). {signal}")
                return
            # TODO: Use functional bag for envelope plots
        else:
            if ndims < 2:
                logger.error(
                    f"Requested to draw line for sig({id(signal)}), but it does not have sufficient data arrays (<2). {signal}")
                return
            line = self._signal_impl_shape_lut.get(id(signal))
            if not isinstance(line, vtkPlot):
                line = self.add_vtk_line_plot(chart, signal.label, data[0], data[1], hi_prec_nanos)
                self._signal_impl_shape_lut.update({id(signal): line})
            else:
                self.refresh_impl_plot_data(line, data[0], data[1], signal.label, hi_prec_nanos)

        # Translate abstract properties to backend
        self._process_ipl_signal_label(signal)
        self._process_ipl_signal_color(signal)

        if isinstance(signal, ArraySignal):
            self._refresh_line_size(signal)
            self._refresh_line_style(signal)
            self._refresh_marker_size(signal)
            self._refresh_marker_style(signal)
            self._refresh_step_type(signal)

    def _process_ipl_signal_color(self, signal: ArraySignal):
        line = self._signal_impl_shape_lut.get(
            id(signal))  # type: vtkPlot
        if not isinstance(line, vtkPlot):
            return
        if signal.color is not None:
            line.SetColor(*vtkImplUtils.get_color4ub(signal.color))

    def _process_ipl_signal_label(self, signal: Signal):
        line = self._signal_impl_shape_lut.get(
            id(signal))  # type: vtkPlot
        if not isinstance(line, vtkPlot):
            return
        if signal.label is not None:
            line.SetLabel(signal.label)

    def _refresh_step_type(self, signal: ArraySignal):
        line = self._signal_impl_shape_lut.get(
            id(signal))  # type: vtkPlot

        if not isinstance(line, vtkPlotPoints):
            return
        chart = self._signal_impl_plot_lut.get(
            id(signal))
        plot = self._impl_plot_cache_table.get_cache_item(chart).plot()

        step = self._pm.get_value(
            'step', self.canvas, plot, signal=signal)
        if step is None:
            return

        step_type = STEP_MAP[step.lower()]
        if step_type not in ["none", "steps", "steps-pre", "steps-post", "steps-mid"]:
            logger.warning(
                f"Steps type: {step} for {id(signal)} is not recognized!")
            return

        table = line.GetInput()
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
            line, newxs, newys, var_name, bitSequencing)

    def _refresh_line_size(self, signal: ArraySignal):
        line = self._signal_impl_shape_lut.get(
            id(signal))  # type: vtkPlot
        if not isinstance(line, vtkPlot):
            return
        chart = self._signal_impl_plot_lut.get(
            id(signal))
        plot = self._impl_plot_cache_table.get_cache_item(chart).plot()
        # line style, width if supported by hardware.
        pen = line.GetPen()
        ls = self._pm.get_value('line_size', self.canvas, plot, signal=signal)
        if ls is not None:
            pen.SetWidth(ls)

    def _refresh_line_style(self, signal: ArraySignal):
        line = self._signal_impl_shape_lut.get(
            id(signal))  # type: vtkPlot
        if not isinstance(line, vtkPlotPoints):
            return
        chart = self._signal_impl_plot_lut.get(
            id(signal))
        plot = self._impl_plot_cache_table.get_cache_item(chart).plot()
        # line style, width if supported by hardware.
        pen = line.GetPen()
        ls = self._pm.get_value('line_style', self.canvas, plot, signal=signal)
        if ls is None:
            return
        elif ls.lower() == "none":
            pen.SetLineType(vtkPen.NO_PEN)
        elif ls.lower() == "solid":
            pen.SetLineType(vtkPen.SOLID_LINE)
        elif ls.lower() == "dashed":
            pen.SetLineType(vtkPen.DASH_LINE)
        elif ls.lower() == "dotted":
            pen.SetLineType(vtkPen.DOT_LINE)

    def _refresh_marker_size(self, signal: ArraySignal):
        line = self._signal_impl_shape_lut.get(
            id(signal))  # type: vtkPlot
        if not isinstance(line, vtkPlotPoints):
            return
        chart = self._signal_impl_plot_lut.get(
            id(signal))
        plot = self._impl_plot_cache_table.get_cache_item(chart).plot()
        # marker style, size
        ms = self._pm.get_value('marker_size', self.canvas, plot, signal=signal)
        if signal.marker_size is not None:
            line.SetMarkerSize(ms)

    def _refresh_marker_style(self, signal: ArraySignal):
        line = self._signal_impl_shape_lut.get(
            id(signal))  # type: vtkPlot
        if not isinstance(line, vtkPlotPoints):
            return
        chart = self._signal_impl_plot_lut.get(
            id(signal))
        plot = self._impl_plot_cache_table.get_cache_item(chart).plot()
        marker = self._pm.get_value(
            'marker', self.canvas, plot, signal=signal)
        if marker == 'x':
            line.SetMarkerStyle(vtkMarkerUtilities.CROSS)
        elif marker == '+':
            line.SetMarkerStyle(vtkMarkerUtilities.PLUS)
        elif marker == "square":
            line.SetMarkerStyle(vtkMarkerUtilities.SQUARE)
        elif marker == 'o' or marker == "circle":
            line.SetMarkerStyle(vtkMarkerUtilities.CIRCLE)
        elif marker == "diamond":
            line.SetMarkerStyle(vtkMarkerUtilities.DIAMOND)

    def resize(self, w: int, h: int):
        title_height = int(self.title_scale * h)
        chart_height = h - title_height - 22  # typical window decoration height

        c_rect = vtkRecti(0, 0, w, chart_height)
        t_rect = vtkRecti(0, chart_height, w, title_height)
        self._layout.SetRect(c_rect)
        self._title_region.SetFixedRect(t_rect)

    def set_focus_plot(self, impl_plot: Any):
        if not isinstance(impl_plot, vtkChart):
            logger.debug("Set focus chart -> None")
            self._focus_plot = None
            self._focus_plot_stack_key = None
            return

        if self._focus_plot is None:
            logger.debug(f"Set focus chart {impl_plot}")
            ci = self._impl_plot_cache_table.get_cache_item(impl_plot)
            if not hasattr(ci, 'plot'):
                return
            if not ci.plot():
                return
            self._focus_plot = ci.plot()
            self._focus_plot_stack_key = ci.stack_key

    def get_impl_x_axis(self, impl_plot: Any):
        if isinstance(impl_plot, vtkChart):
            return impl_plot.GetAxis(vtkAxis.BOTTOM)
        else:
            return None

    def get_impl_y_axis(self, impl_plot: Any):
        if isinstance(impl_plot, vtkChart):
            return impl_plot.GetAxis(vtkAxis.LEFT)
        else:
            return None

    def get_impl_x_axis_limits(self, impl_plot: Any):
        if isinstance(impl_plot, vtkChart):
            ax = impl_plot.GetAxis(vtkAxis.BOTTOM)
            return (ax.GetMinimum(), ax.GetMaximum())
        else:
            return None

    def get_impl_y_axis_limits(self, impl_plot: Any):
        if isinstance(impl_plot, vtkChart):
            ax = impl_plot.GetAxis(vtkAxis.LEFT)
            return (ax.GetMinimum(), ax.GetMaximum())
        else:
            return None

    def get_oaw_axis_limits(self, impl_plot: Any, ax_idx: int):
        """Offset-aware version of implementation's get_x_limits, get_y_limits"""
        begin, end = (None, None)
        if 0 <= ax_idx <= 1:
            try:
                begin, end = [self.get_impl_x_axis_limits, self.get_impl_y_axis_limits][ax_idx](impl_plot)
            except TypeError:
                return begin, end
        if ax_idx == 1:
            return begin, end
        return self.transform_value(impl_plot, ax_idx, begin), self.transform_value(impl_plot, ax_idx, end)

    def set_impl_x_axis_limits(self, impl_plot: Any, limits: tuple):
        if isinstance(impl_plot, vtkChart):
            impl_plot.GetAxis(vtkAxis.BOTTOM).SetRange(limits[0], limits[1])

    def set_impl_y_axis_limits(self, impl_plot: Any, limits: tuple):
        if isinstance(impl_plot, vtkChart):
            impl_plot.GetAxis(vtkAxis.LEFT).SetRange(limits[0], limits[1])
        else:
            return None

    def set_oaw_axis_limits(self, impl_plot: Any, ax_idx: int, limits):
        """Offset-aware version of implementation's set_x_limits, set_y_limits"""
        if ax_idx == 0:
            begin = self.transform_value(
                impl_plot, ax_idx, limits[0], inverse=True)
            end = self.transform_value(
                impl_plot, ax_idx, limits[1], inverse=True)
        else:
            begin = limits[0]
            end = limits[1]

        if ax_idx == 0:
            if begin == end and begin is not None:
                begin = end-1
            return self.set_impl_x_axis_limits(impl_plot, (begin, end))
        elif ax_idx == 1:
            return self.set_impl_y_axis_limits(impl_plot, (begin, end))
        else:
            return None

    def transform_value(self, impl_plot: Any, ax_idx: int, value: Any, inverse=False):
        """Adds or subtracts axis offset from value trying to preserve type of offset (ex: does not convert to
        float when offset is int)"""
        if ax_idx == 1:
            return value
        ticker = self._vtk_custom_tickers.get(id(impl_plot))
        if not isinstance(ticker, VTK64BitTimePlotSupport):
            return value
        return ticker.transformValue(value, inverse=inverse)

    def transform_data(self, impl_plot: Any, data):
        """This function post processes 64-bitdata if it cannot be plotted with VTK directly.
        NOTE: This function is unused in the VTK implementation.
        """
        pass
