import typing

from iplotlib.impl.vtk import utils as vtkImplUtils

from vtkmodules.vtkCommonDataModel import vtkVector2f
from vtkmodules.vtkChartsCore import vtkAxis, vtkChartMatrix, vtkChart
from vtkmodules.vtkPythonContext2D import vtkPythonItem
from vtkmodules.vtkRenderingContext2D import vtkContext2D

from iplotLogging import setupLogger as sl
logger = sl.get_logger(__name__, "INFO")

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
