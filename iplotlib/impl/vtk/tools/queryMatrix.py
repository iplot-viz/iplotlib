# Copyright (c) 2020-2025 ITER Organization,
#               CS 90046
#               13067 St Paul Lez Durance Cedex
#               France
# Author IO
#
# This file is part of iplotlib module.
# iplotlib python module is free software: you can redistribute it and/or modify it under
# the terms of the MIT license.
#
# This file is part of ITER CODAC software.
# For the terms and conditions of redistribution or use of this software
# refer to the file LICENSE located in the top level directory
# of the distribution package
#


from typing import Union, List, Tuple
from vtkmodules.vtkCommonDataModel import vtkVector2f, vtkVector2i
from vtkmodules.vtkChartsCore import vtkChartMatrix, vtkChart, vtkPlot

from iplotLogging import setupLogger as Sl

logger = Sl.get_logger(__name__, "INFO")


def get_charts(matrix: vtkChartMatrix, charts: List[vtkChart]):
    """Get all constituent charts in a chart matrix

    Args:
        matrix (vtkChartMatrix): a chart matrix (possibly with a nested layout)
        charts (List[vtkChart]): a list of charts
    """
    size = matrix.GetSize()
    for c in range(size.GetX()):
        for r in range(size.GetY()):
            chart = matrix.GetChart(vtkVector2i(c, r))
            subMatrix = matrix.GetChartMatrix(vtkVector2i(c, r))
            if chart is None and subMatrix is not None:
                get_charts(subMatrix, charts)
            elif chart is not None and subMatrix is None:
                charts.append(chart)


def find_element_index(matrix: vtkChartMatrix, scenePosition: Tuple) -> vtkVector2i:
    """Find the vtkChart/vtkChartMatrix that is near the given probing position in a chart matrix.
        This method is not determined to find a chart. It just returns the first element found.

    Args:
        matrix (vtkChartMatrix): a chart matrix (possibly with a nested layout)
        scenePosition (Tuple): a probe position

    Returns:
        vtkVector2i: A chart or none if no chart exists
    """
    elementIndex = matrix.GetChartIndex(vtkVector2f(scenePosition))
    logger.debug(f"Mouse in element {elementIndex}")

    return elementIndex


def find_chart(matrix: vtkChartMatrix, scenePosition: Tuple) -> Union[None, vtkChart]:
    """Find the vtkChart that is near the given probing position in a chart matrix.
        This method is determined to find a chart.

    Args:
        matrix (vtkChartMatrix): a chart matrix (possibly with a nested layout)
        scenePosition (Tuple): a probe position

    Returns:
        Union[None, vtkChart]: A chart or none if no chart exists
    """
    elementIndex = matrix.GetChartIndex(vtkVector2f(scenePosition))
    logger.debug(f"Mouse in element {elementIndex}")

    if elementIndex.GetX() < 0 or elementIndex.GetY() < 0:
        return

    chart = matrix.GetChart(elementIndex)
    subMatrix = matrix.GetChartMatrix(elementIndex)
    if chart is None and subMatrix is not None:
        return find_chart(subMatrix, scenePosition)
    elif chart is not None and subMatrix is None:
        return chart


def find_root_plot(matrix: vtkChartMatrix, scenePosition: Tuple) -> Union[None, vtkPlot]:
    """Find the root plot that is near the given probing position in a chart matrix.

    Args:
        matrix (vtkChartMatrix): a chart matrix (possibly with a nested layout)
        scenePosition (Tuple): a probe position

    Returns:
        Union[None, vtkPlot]: A plot or none if no plot exists
    """
    elementIndex = matrix.GetChartIndex(vtkVector2f(scenePosition))
    logger.debug(f"Mouse in element {elementIndex}")

    if elementIndex.GetX() < 0 or elementIndex.GetY() < 0:
        return

    chart = matrix.GetChart(elementIndex)
    subMatrix = matrix.GetChartMatrix(elementIndex)
    if chart is None and subMatrix is not None:
        return find_root_plot(subMatrix, scenePosition)
    elif chart is not None and subMatrix is None:
        return chart.GetPlot(0)
