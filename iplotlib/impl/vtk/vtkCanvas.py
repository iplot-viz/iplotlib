import numpy as np
import pandas as pd
import typing
from contextlib import contextmanager
from dataclasses import dataclass

from iplotlib.core.axis import LinearAxis
from iplotlib.core.canvas import Canvas
from iplotlib.core.plot import Plot, PlotXY
from iplotlib.core.signal import ArraySignal, Signal
from iplotlib.core.property_manager import PropertyManager
from iplotlib.impl.vtk import utils as vtkImplUtils

# needed for runtime vtk-opengl libs
import vtkmodules.vtkRenderingOpenGL2
# needed for runtime vtk-opengl libs
import vtkmodules.vtkRenderingContextOpenGL2
from vtkmodules.vtkCommonColor import vtkNamedColors
from vtkmodules.vtkCommonCore import vtkAbstractArray, vtkStringArray
from vtkmodules.vtkCommonDataModel import vtkColor4d, vtkTable, vtkVector2f, vtkVector2i, vtkRectd, vtkRecti
from vtkmodules.vtkChartsCore import vtkAxis, vtkChartMatrix, vtkChart, vtkChartXY, vtkContextArea, vtkPlot, vtkPlotLine, vtkPlotPoints
from vtkmodules.vtkViewsContext2D import vtkContextView
from vtkmodules.vtkRenderingCore import vtkTextProperty
from vtkmodules.vtkRenderingContext2D import vtkContext2D, vtkContextMapper2D, vtkContextMouseEvent, vtkContextItem, vtkContextScene, vtkMarkerUtilities, vtkPen
from vtkmodules.util import numpy_support
from vtkmodules.vtkPythonContext2D import vtkPythonItem

from iplotLogging import setupLogger as sl
logger = sl.get_logger(__name__, "DEBUG")

AXIS_MAP = [vtkAxis.BOTTOM, vtkAxis.LEFT]


class InvalidPlotException(Exception):
    def __init__(self, *args: object) -> None:
        super().__init__(*args)


class VTK64BitTimePlotSupport:
    def __init__(self, enabled=True, precise=True):
        self._enabled = enabled
        self._precise = precise
        self._table = None  # type: vtkTable
        self._plot = None  # type: vtkPlot

    def enable(self):
        """
        Generate tick-labels with iso-8601 format.
        See disable() to turn this off.
        """
        self._enabled = True

    def disable(self):
        """
        Turn off formatted tick labels.
        """
        self._enabled = False

    def precisionOn(self):
        """
        Dynamically adjust plot data to accurately represent
        varying time periods. All the way upto nano seconds.
        """
        self._precise = True

    def precisionOff(self):
        """
        Directly plot input time series. Precise upto ___
        """
        self._precise = False

    def isPlotValid(self):
        return isinstance(self._plot, vtkPlotPoints)

    @staticmethod
    def getColumnId(table, arr: vtkAbstractArray) -> int:
        columnId = -1
        numCols = table.GetNumberOfColumns()
        for i in range(numCols):
            if arr == table.GetColumn(i):
                columnId = i
                break
        return columnId

    @contextmanager
    def getPlotFromChart(self, plotId: int, chart: vtkChart):
        self._plot = chart.GetPlot(plotId)
        self._table = self._plot.GetInput()
        try:
            yield None
        finally:
            self._plot = None
            self._table = None

    def getActiveColumnId(self, chart: vtkChart, plotId: int) -> int:
        actColId = -1
        with self.getPlotFromChart(plotId, chart):
            if self.isPlotValid():
                data = self._plot.GetData()  # type: vtkContextMapper2D
                arr = data.GetInputArrayToProcess(
                    0, self._table)  # type: vtkAbstractArray
                actColId = VTK64BitTimePlotSupport.getColumnId(
                    self._table, arr)
        return actColId

    @staticmethod
    def getNextBitSeqId(bitSeqId: int,
                        numBitSequences: int,
                        least: bool = True) -> int:
        if (np.little_endian and least) or (not np.little_endian
                                            and not least):
            if bitSeqId <= 0:
                return 0
            else:
                return bitSeqId - 1
        else:
            if bitSeqId >= numBitSequences - 1:
                return numBitSequences - 1
            else:
                return bitSeqId + 1

    @staticmethod
    def normalizeToDtype(bitSequences: list, dtype=np.uint16):
        numberOfSequences = len(bitSequences)
        dtypeBitWidth = np.dtype(dtype).itemsize * 8
        dtypeMin = 0
        dtypeMax = (1 << dtypeBitWidth) - 1
        dtypeCapacity = dtypeMax - dtypeMin + 1

        start = 0
        if not np.little_endian:
            start = numberOfSequences - 1

        q = start
        while True:
            nextId = VTK64BitTimePlotSupport.getNextBitSeqId(q,
                                                             numberOfSequences,
                                                             least=False)
            seq = bitSequences[q]
            if nextId == q:
                if seq < dtypeMin:
                    bitSequences[q] = dtypeMin
                elif seq > dtypeMax:
                    bitSequences[q] = dtypeMax
                break

            if seq < dtypeMin:
                bitSequences[q] = dtypeMin
                p = np.abs(seq - dtypeMax) // dtypeCapacity
                bitSequences[nextId] = int(bitSequences[nextId] - p)
            elif seq > dtypeMax:
                bitSequences[q] = dtypeMax
                p = np.abs(seq - dtypeMax) // dtypeCapacity
                bitSequences[nextId] = int(bitSequences[nextId] + p)

            q = nextId

    @staticmethod
    def getTimeStampFrom16Bits(
            bitSequences: typing.Sequence[np.uint16]) -> int:
        if np.little_endian:
            bitSequencesIter = iter(bitSequences)
        else:
            bitSequencesIter = reversed(bitSequences)

        retVal = (next(bitSequencesIter) + next(bitSequencesIter) * (1 << 16) +
                  (next(bitSequencesIter) + next(bitSequencesIter) *
                   (1 << 16)) * (1 << 32))

        if retVal > ((1 << 63) - 1):
            retVal = (1 << 63) - 1

        return retVal

    def getXRange(self, chart: vtkChart, plotId: int) -> typing.Tuple[float]:
        xr = ()
        with self.getPlotFromChart(plotId, chart):
            if self.isPlotValid():
                xAxis = self._plot.GetXAxis()  # type: vtkAxis
                xr = xAxis.GetMinimum(), xAxis.GetMaximum()
        return xr

    def getOffsetTimeValue(self, chart: vtkChart, plotId: int,
                           columnId: int) -> int:
        """
        Determine an offset time stamp for a column Id.
        Ex:
        To generate full(64-bit) timestamps for values in a column,
        you'd need to add an offset to each value listed in that column.

        full_time_stamp_value[i] = offset + values[i]

        Args:
            plot (vtkPlot): plot instance
            columnId (int): a column id

        Returns:
            int: offset time for all values in columnId of plot's input data.
        """
        ofstTime = -1
        bitSequences = np.zeros((4, ), dtype=np.uint16)
        bitSeqId = columnId - 2
        with self.getPlotFromChart(plotId, chart):
            if self.isPlotValid():
                for i in range(1, 4):
                    arr = self._table.GetColumn(i + 1)
                    arrName = arr.GetName()
                    try:
                        bitSequences[i] = np.uint16(int(arrName))
                    except ValueError:  # if arrName = ""
                        pass
                logger.debug(f"Bit Sequence: {bitSequences}")
                if np.little_endian:
                    bitSequences[:bitSeqId] = [0] * (bitSeqId)
                else:
                    bitSequences[(bitSeqId + 1):] = [0] * (3 - bitSeqId)
                ofstTime = VTK64BitTimePlotSupport.getTimeStampFrom16Bits(
                    bitSequences)
        return ofstTime

    def checkStepUp(self, chart: vtkChart, plotId: int) -> bool:
        boundsOverflow = False
        xmin, xmax = self.getXRange(chart, plotId)
        maxRange = (1 << 16) - 1
        boundsOverflow = np.abs(xmax - xmin) > maxRange
        return boundsOverflow

    def checkStepDn(self, chart: vtkChart, plotId: int) -> bool:
        boundsEqual = True
        with self.getPlotFromChart(plotId, chart):
            if self.isPlotValid():
                data = self._plot.GetData()  # type: vtkContextMapper2D
                arr = data.GetInputArrayToProcess(
                    0, self._table)  # type: vtkAbstractArray
                tmin, tmax = arr.GetRange()
                boundsEqual = np.abs(tmax - tmin) < 1
        return boundsEqual

    def getNewColumnId(self, chart: vtkChart, plotId: int):
        actColId = self.getActiveColumnId(chart, plotId)
        newColId = actColId
        actBitSeqId = actColId - 2

        if self.checkStepDn(chart, plotId):
            newColId = VTK64BitTimePlotSupport.getNextBitSeqId(actBitSeqId,
                                                               4) + 2
            logger.debug(f"Stepping down {actColId}->{newColId}")
        elif self.checkStepUp(chart, plotId):
            newColId = (VTK64BitTimePlotSupport.getNextBitSeqId(
                actBitSeqId, 4, least=False) + 2)
            logger.debug(f"Stepping up {actColId}->{newColId}")
        else:
            logger.debug(
                f"No need to step up/down. Active Column Id: {actColId}")

        return newColId

    def updateActiveColumnId(self, chart: vtkChart, plotId: int,
                             newColId: int) -> bool:
        updated = False
        actColId = self.getActiveColumnId(chart, plotId)

        with self.getPlotFromChart(plotId, chart):
            if self.isPlotValid():
                if actColId == newColId:
                    updated = False
                else:
                    logger.debug(
                        f"Update active column: {actColId} -> {newColId}")

                    actBitSeqId = actColId - 2
                    newBitSeqId = newColId - 2
                    if (VTK64BitTimePlotSupport.getNextBitSeqId(
                            actBitSeqId, 4) == newBitSeqId):
                        # stepping down
                        actArr = self._table.GetColumn(actColId)
                        newArr = self._table.GetColumn(newColId)
                        tb = np.uint16(actArr.GetRange()[0])
                        newArr.SetName(str(tb))
                        logger.debug(f"Stepped down at {tb}")

                    self._plot.SetInputData(self._table, newColId, 1)
                    self._plot.Update()
                    updated = True
        return updated

    def selectColumn(self, chart: vtkChart, plotId: int) -> int:
        """Select a set of 16 bits used for x-axis data.
        It will do so only when x-axis range is insufficient i.e, beyond 65535.
        """
        logger.debug(f"Plot {plotId}: Dynamically select column")
        depth = 0
        maxDepth = 4
        newColId = 0
        while depth < maxDepth:
            depth += 1
            newColId = self.getNewColumnId(chart, plotId)
            if not self.updateActiveColumnId(chart, plotId, newColId):
                break

        return newColId

    def isBitSequencingEnabled(self, chart: vtkChart):
        numPlots = chart.GetNumberOfPlots()
        bEnabled = True
        for i in range(numPlots):
            stat = self.getActiveColumnId(chart, i) > 0
            logger.debug(
                f"Plot {i}: Bit sequencing was {'enabled' if stat else 'disabled'}."
            )
            bEnabled &= stat
        return bEnabled

    def enableBitSequencing(self, chart: vtkChart, plotId: int):
        with self.getPlotFromChart(plotId, chart):
            if self.isPlotValid():
                self._table.GetColumn(5).SetName(str(0))
        self.updateActiveColumnId(chart, plotId, 5)

    def disableBitSequencing(self, chart: vtkChart, plotId: int):
        with self.getPlotFromChart(plotId, chart):
            if self.isPlotValid():
                self.updateActiveColumnId(chart, plotId, 0)

    def resetXaxisRange(self, chart: vtkChart, plotId: int):
        actColId = self.getActiveColumnId(chart, plotId)
        with self.getPlotFromChart(plotId, chart):
            if self.isPlotValid():
                tArr = self._table.GetColumn(actColId)
                tMin, tMax = tArr.GetRange()
                xAxis = chart.GetAxis(vtkAxis.BOTTOM)
                xAxis.SetMinimum(tMin)
                xAxis.SetMaximum(tMax)

    def dynamicSelectColumns(self, chart: vtkChart):
        """Dynamically select columns (if bit sequencing was enabled)
        Args:
            chart (vtkChart): a chart contains a number of plots
        """
        selectedColIds = []
        if self._precise:
            numPlots = chart.GetNumberOfPlots()
            for i in range(numPlots):
                colId = self.selectColumn(chart, i)
                if colId:
                    selectedColIds.append(colId)
        return selectedColIds

    def generateTics(self, obj, ev):
        """Tick labels mark periods of time in plot data.
        These labels display only the varying periods.
        The constant prefix is stored in axis title.
        """
        if not self._enabled:
            return

        chart = obj.GetParent()  # type: vtkChart

        # Initially, compute simple numeric tick positions
        xAxis = chart.GetAxis(vtkAxis.BOTTOM)  # type: vtkAxis
        xAxis.SetCustomTickPositions(None, None)
        xAxis.SetNumberOfTicks(6)
        xAxis.SetTickLabelAlgorithm(vtkAxis.TICK_SIMPLE)

        columnIds = []
        bBitSeqEnabled = self.isBitSequencingEnabled(chart)

        numPlots = chart.GetNumberOfPlots()
        if self._precise:
            if bBitSeqEnabled:
                # Dynamically select a suitable column
                columnIds.extend(self.dynamicSelectColumns(chart))
            else:
                # Enable bit sequencing
                for i in range(numPlots):
                    self.enableBitSequencing(chart, i)
                    # and dynamically select columns
                    actColId = self.selectColumn(chart, i)
                    columnIds.append(actColId)
                    self.resetXaxisRange(
                        chart, i)  # needed to fit axis to current column data
        elif not self._precise:
            if bBitSeqEnabled:
                # Disable bit sequencing
                for i in range(numPlots):
                    self.disableBitSequencing(chart, i)
                    self.resetXaxisRange(
                        chart, i)  # needed to fit axis to current column data

        if self._precise:
            # Check for uniqueness. All plots must have same active column.
            activeColId = min(columnIds)
            activeBitSeqId = activeColId - 2
            if min(columnIds) != max(columnIds):
                columnIds[:] = [activeColId] * len(columnIds)

            # Enforce uniform active column. Get offset time
            ofstTime = (1 << 63) - 1
            for i in range(numPlots):
                self.updateActiveColumnId(chart, i, columnIds[i])
                ofstITime = self.getOffsetTimeValue(chart, i, columnIds[i])
                if ofstITime >= 0:
                    ofstTime = min(ofstITime, ofstTime)
            logger.debug(f"Offset time: {pd.to_datetime(ofstTime)}")

        xAxis.Update()
        tickPositionsVtkArr = xAxis.GetTickPositions()
        tickPositionsNpArr = numpy_support.vtk_to_numpy(tickPositionsVtkArr)
        tss = []

        logger.debug(f"TimeStamp | Tick Position | time")
        for pos in tickPositionsNpArr:
            if self._precise:
                bitSequences = np.array([ofstTime], np.uint64).view(np.uint16)
                bitSequencesList = bitSequences.tolist()
                bitSequencesList[activeBitSeqId] = int(
                    bitSequencesList[activeBitSeqId] + pos)
                logger.debug(f"Pre-normalize: {bitSequencesList}")
                VTK64BitTimePlotSupport.normalizeToDtype(bitSequencesList,
                                                         dtype=np.uint16)
                logger.debug(f"Post-normalize: {bitSequencesList}")
                t = VTK64BitTimePlotSupport.getTimeStampFrom16Bits(
                    bitSequencesList)
            else:
                t = np.int64(pos)
                if t < 0:
                    t = 0
            tss.append(pd.to_datetime(t))
            logger.debug(f"{tss[-1]} | {np.int64(pos)} | {t}")

        timestamps = pd.to_datetime(tss)
        uniq_year = timestamps.year.nunique() == 1
        uniq_month = timestamps.month.nunique() == 1
        uniq_day = timestamps.day.nunique() == 1
        uniq_hour = timestamps.hour.nunique() == 1
        uniq_minute = timestamps.minute.nunique() == 1
        uniq_second = timestamps.second.nunique() == 1
        uniq_micro = timestamps.microsecond.nunique() == 1

        prefixFmt = ""
        removeSuffix = "-%dT%H:%M:%S.%f.nano"
        tickLabelFmt = "%Y-%m-%dT%H:%M:%S.%f.nano"
        if uniq_year:
            prefixFmt += "%Y-"
            removeSuffix = "T%H:%M:%S.%f.nano"
            if uniq_month:
                prefixFmt += "%m-"
                removeSuffix = ":%M:%S.%f.nano"
                if uniq_day:
                    prefixFmt += "%dT"
                    removeSuffix = ":%S.%f.nano"
                    if uniq_hour:
                        prefixFmt += "%H:"
                        removeSuffix = ".%f.nano"
                        if uniq_minute:
                            prefixFmt += "%M:"
                            removeSuffix = ".nano"
                            if uniq_second:
                                prefixFmt += "%S."
                                removeSuffix = ""
                                if uniq_micro:
                                    prefixFmt += "%f."
                                    removeSuffix = ""

        tickLabelFmt = tickLabelFmt.replace(prefixFmt, "")
        tickLabelFmt = tickLabelFmt.replace(removeSuffix, "")
        logger.debug("Fmt strings:")
        logger.debug(f"|--Tick-label: {tickLabelFmt}")
        logger.debug(f"|--Axis title: Fmt string: {prefixFmt}")

        tick_labels = vtkStringArray()
        for ts in tss:
            tick_label = ts.strftime(tickLabelFmt)
            tick_label = tick_label.replace("nano",
                                            str(ts.nanosecond).zfill(3))
            tick_labels.InsertNextValue(tick_label)

        xAxis.SetCustomTickPositions(tickPositionsVtkArr, tick_labels)
        xAxis.SetTitle(tss[0].strftime(prefixFmt))
        xAxis.Update()


class CrosshairCursor(object):
    def __init__(self,
                 horizOn=False,
                 vertOn=True,
                 hLineW=1,
                 hLineCol='red',
                 vLineW=1,
                 vLineCol='blue'):
        self.lv = {'h': horizOn, 'v': vertOn}
        self.lw = {'h': hLineW, 'v': vLineW}
        self.lc = {'h': hLineCol, 'v': vLineCol}
        self.xRange = [0, 1]
        self.yRange = [0, 1]
        self.position = [0.5, 0.5]

    def Initialize(self, vtkSelf):
        return True

    def Paint(self, vtkSelf, context2D: vtkContext2D):
        logger.debug(f"Painting crosshair cursor @{self.position}")
        pen = context2D.GetPen()
        brush = context2D.GetBrush()

        if (self.yRange[0] < self.position[1] <
                self.yRange[1]) and self.lv['h']:
            pen.SetColor(*vtkImplUtils.get_color3ub(self.lc['h']))
            brush.SetColor(*vtkImplUtils.get_color3ub(self.lc['h']))
            pen.SetWidth(self.lw['h'])
            context2D.DrawLine(self.xRange[0], self.position[1],
                               self.xRange[1], self.position[1])

        if (self.xRange[0] < self.position[0] <
                self.xRange[1]) and self.lv['v']:
            pen.SetColor(*vtkImplUtils.get_color3ub(self.lc['v']))
            brush.SetColor(*vtkImplUtils.get_color3ub(self.lc['v']))
            pen.SetWidth(self.lw['v'])
            context2D.DrawLine(self.position[0], self.yRange[0],
                               self.position[0], self.yRange[1])

        return True


class CrosshairCursorWidget:
    def __init__(self, matrix: vtkChartMatrix, charts: typing.List[vtkChart],
                 **kwargs):
        self.matrix = matrix
        self.charts = []
        self.rootPlotPos = [0, 0]
        self.cursors = []
        self.cursor_kwargs = kwargs

        self.scene = self.matrix.GetScene()
        if self.scene is None:
            return

        self.resize()

    def resize(self):

        for _ in range(len(self.charts)):
            cursor = CrosshairCursor(self.cursor_kwargs)
            item = vtkPythonItem()
            item.SetPythonObject(cursor)
            item.SetVisible(False)
            self.cursors.append([cursor, item])
            self.scene.AddItem(item)

    def clear(self):
        for _, item in self.cursors:
            self.scene.RemoveItem(item)
        self.cursors.clear()
        self.charts.clear()

    def hide(self):
        for _, item in self.cursors:
            item.SetVisible(False)

    def onMove(self, mousePos: tuple):
        scene = self.matrix.GetScene()
        if scene is None:
            return

        screenToScene = scene.GetTransform()
        scenePos = [0, 0]
        screenToScene.TransformPoints(mousePos, scenePos, 1)

        self.hide()

        def _get_plot_root(matrix: vtkChartMatrix):

            elementIndex = matrix.GetChartIndex(vtkVector2f(scenePos))
            logger.debug(f"Mouse in element {elementIndex}")

            if elementIndex.GetX() < 0 or elementIndex.GetY() < 0:
                return

            chart = matrix.GetChart(elementIndex)
            subMatrix = matrix.GetChartMatrix(elementIndex)
            if chart is None and subMatrix is not None:
                return _get_plot_root(subMatrix)
            elif chart is not None and subMatrix is None:
                return chart.GetPlot(0)

        plotRoot = _get_plot_root(self.matrix)
        if plotRoot is None:
            return

        self.rootPlotPos = plotRoot.MapFromScene(vtkVector2f(scenePos))
        self._update()

    def _update(self):
        for i, chart in enumerate(self.charts):
            plot = chart.GetPlot(0)
            if plot is None:
                continue

            xShift = plot.GetShiftScale().GetX()
            xScale = plot.GetShiftScale().GetWidth()
            xAxis = chart.GetAxis(vtkAxis.BOTTOM)
            xRange = [xAxis.GetMinimum(), xAxis.GetMaximum()]
            xRangePlotCoords = [0, 0]
            for j in range(2):
                xRangePlotCoords[j] = (xRange[j] + xShift) * xScale

            yShift = plot.GetShiftScale().GetY()
            yScale = plot.GetShiftScale().GetHeight()
            yAxis = chart.GetAxis(vtkAxis.LEFT)
            yRange = [yAxis.GetMinimum(), yAxis.GetMaximum()]
            yRangePlotCoords = [0, 0]
            for j in range(2):
                yRangePlotCoords[j] = (yRange[j] + yShift) * yScale

            cursor, item = self.cursors[i]
            for j in range(2):
                cursor.xRange[j], cursor.yRange[j] = plot.MapToScene(
                    vtkVector2f(xRangePlotCoords[j], yRangePlotCoords[j]))

            cursor.position = plot.MapToScene(vtkVector2f(self.rootPlotPos))
            item.SetVisible(True)


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

        self.view = vtkContextView()
        self.scene = self.view.GetScene()
        self.matrix = vtkChartMatrix()
        self.scene.AddItem(self.matrix)
        self.custom_tickers = {}
        self.crosshair = CrosshairCursorWidget(self.matrix,
                                               [],
                                               horizOn=True,
                                               hLineW=1,
                                               vLineW=1)
        self.property_manager = PropertyManager()

        self.matrix.SetGutterX(50)
        self.matrix.SetGutterY(50)
        self.matrix.SetBorderTop(0)

        self._plot_impl_lookup = dict()  # Signal -> vtkPlot
        self._plot_lookup = dict()  # reverse lookup i.e, Signal -> Plot

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
        self._plot_impl_lookup.clear()
        self._plot_lookup.clear()
        self.matrix.SetSize(vtkVector2i(0, 0))
        self.custom_tickers.clear()
        self.crosshair.clear()

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

        # 4.1 Fill canvas with charts
        for i, column in enumerate(self.plots):

            j = 0

            for plot in column:

                self.refresh_plot(plot, i, j)

                # Increment row number carefully. (for next iteration)
                j += plot.row_span if isinstance(plot, Plot) else 1

        # 4.2 canvas applicable mouse mode
        self.crosshair_enabled = (self.mouse_mode == Canvas.MOUSE_MODE_CROSSHAIR)

        # 4.3 Crosshair widget
        self.crosshair.resize()
        for cursor, _ in self.crosshair.cursors:  # type: CrosshairCursor,
            cursor.lc['h'] = self.crosshair_color
            cursor.lc['v'] = self.crosshair_color
            cursor.lw['h'] = self.crosshair_line_width
            cursor.lw['v'] = self.crosshair_line_width
            cursor.lv['h'] = self.crosshair_horizontal
            cursor.lv['v'] = self.crosshair_vertical


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
        plot = self._plot_lookup.get(id(signal))  # type: Plot
        self.property_manager.acquire_signal_from_plot(plot, signal)
        # handle high precision data for nanosecond timestamps
        if isinstance(signal, ArraySignal):
            # type: VTK64BitTimePlotSupport
            ticker = self.custom_tickers.get(id(plot))
            if ticker is not None:
                if signal.hi_precision_data:
                    ticker.precisionOn()
                else:
                    ticker.precisionOff()
            else:
                logger.warning(
                    "refresh_signal called but date-time ticker unitialized.")

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
            element.SetGutterX(0)
            element.SetGutterY(0)

        for i, stack_id in enumerate(sorted(plot.signals.keys())):
            signals = plot.signals.get(stack_id) or []

            # Prepare or create chart in root/nested chart matrix if necessary
            chart = None
            if isinstance(element, vtkChartMatrix):
                chart = self.add_vtk_chart(element, 0, i)
            else:
                chart = element

            if chart not in self.crosshair.charts and self.crosshair_enabled:
                self.crosshair.charts.append(chart)

            chart.SetActionToButton(vtkChart.PAN, vtkContextMouseEvent.NO_BUTTON)
            chart.SetActionToButton(vtkChart.ZOOM, vtkContextMouseEvent.NO_BUTTON)
            chart.SetActionToButton(vtkChart.ZOOM_AXIS, vtkContextMouseEvent.NO_BUTTON)
            chart.SetActionToButton(vtkChart.SELECT, vtkContextMouseEvent.NO_BUTTON)
            chart.SetActionToButton(vtkChart.SELECT_RECTANGLE, vtkContextMouseEvent.NO_BUTTON)
            chart.SetActionToButton(vtkChart.CLICK_AND_DRAG, vtkContextMouseEvent.NO_BUTTON)

            if self.mouse_mode == Canvas.MOUSE_MODE_PAN:
                chart.SetActionToButton(vtkChart.PAN, vtkContextMouseEvent.LEFT_BUTTON)
            elif self.mouse_mode == Canvas.MOUSE_MODE_SELECT:
                chart.SetActionToButton(vtkChart.SELECT, vtkContextMouseEvent.LEFT_BUTTON)
            elif self.mouse_mode == Canvas.MOUSE_MODE_ZOOM:
                chart.SetActionToButton(vtkChart.SELECT, vtkContextMouseEvent.LEFT_BUTTON)

            # translate plot properties to chart
            draw_title = not stacked or (stacked and i == stack_sz - 1)
            if (plot.title is not None) and draw_title:
                chart.SetTitle(plot.title)
                appearance = chart.GetTitleProperties()  # type: vtkTextProperty
                if plot.font_color is not None:
                    appearance.SetColor(
                        *vtkImplUtils.get_color3d(plot.font_color))
                if plot.font_size is not None:
                    appearance.SetFontSize(plot.font_size)

            if plot.legend is not None:
                chart.SetShowLegend(plot.legend)

            if isinstance(plot, PlotXY):
                if plot.grid is not None:
                    chart.GetAxis(vtkAxis.BOTTOM).SetGridVisible(plot.grid)
                    chart.GetAxis(vtkAxis.LEFT).SetGridVisible(plot.grid)
                for ax_id, ax in enumerate(plot.axes):
                    ax_impl_id = AXIS_MAP[ax_id]
                    ax_impl = chart.GetAxis(ax_impl_id)

                    # date time ticking
                    if ax_impl_id == vtkAxis.BOTTOM:
                        if not self.custom_tickers.get(id(plot)):
                            self.custom_tickers.update(
                                {id(plot): VTK64BitTimePlotSupport()})
                            ax_impl.AddObserver(
                                vtkChart.UpdateRange, self.custom_tickers[id(plot)].generateTics)
                        # type: VTK64BitTimePlotSupport
                        ticker = self.custom_tickers.get(id(plot))
                        if isinstance(ax, LinearAxis):
                            if ax.is_date:
                                ticker.enable()
                            else:
                                ticker.disable()
                    if plot.grid is not None:
                        ax_impl.SetGridVisible(plot.grid)
                    if ax.label is not None:
                        ax_impl.SetTitle(ax.label)
                        appearance = chart.GetTitleProperties()  # type: vtkTextProperty
                        if ax.font_color is not None:
                            appearance.SetColor(
                                *vtkImplUtils.get_color3d(ax.font_color))
                        if ax.font_size is not None:
                            appearance.SetFontSize(ax.font_size)

            # Plot each signal
            for signal in signals:
                self._plot_lookup.update({id(signal): plot})
                self.refresh_signal(signal, chart)

        if isinstance(element, vtkChartMatrix):
            element.LabelOuter(vtkVector2i(0, 0), vtkVector2i(0, stack_sz - 1))

        if self.shared_x_axis:
            element.LinkAll(vtkVector2i(0, 0), vtkAxis.BOTTOM)

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
