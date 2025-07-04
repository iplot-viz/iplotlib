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


import numpy as np
import pandas as pd
from typing import Sequence, Any, Tuple
from contextlib import contextmanager
import datetime

from vtkmodules.vtkCommonCore import vtkAbstractArray, vtkStringArray
from vtkmodules.vtkCommonDataModel import vtkTable
from vtkmodules.vtkChartsCore import vtkAxis, vtkChart, vtkPlot, vtkPlotPoints
from vtkmodules.vtkRenderingContext2D import vtkContextMapper2D
from vtkmodules.util import numpy_support

from iplotLogging import setupLogger as Sl

logger = Sl.get_logger(__name__, "INFO")


class VTK64BitTimePlotSupport:
    def __init__(self, enabled=True, precise=True):
        self._enabled = enabled
        self._precise = precise
        self._table = None  # type: vtkTable
        self._plot = None  # type: vtkPlot
        self._activeBitSeqId = None
        self._ofstTime = None

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

    def precision_on(self):
        """
        Dynamically adjust plot data to accurately represent
        varying time periods. All the way upto nano seconds.
        """
        self._precise = True

    def precision_off(self):
        """
        Directly plot input time series. Precise upto ___
        """
        self._precise = False

    def is_plot_valid(self):
        return isinstance(self._plot, vtkPlotPoints) and isinstance(self._table, vtkTable)

    @staticmethod
    def get_column_id(table, arr: vtkAbstractArray) -> int:
        columnId = -1
        numCols = table.GetNumberOfColumns()
        for i in range(numCols):
            if arr == table.GetColumn(i):
                columnId = i
                break
        return columnId

    @contextmanager
    def get_plot_from_chart(self, plotId: int, chart: vtkChart):
        self._plot = chart.GetPlot(plotId)
        self._table = self._plot.GetInput()
        try:
            yield None
        finally:
            self._plot = None
            self._table = None

    def get_active_column_id(self, chart: vtkChart, plotId: int) -> int:
        actColId = -1
        with self.get_plot_from_chart(plotId, chart):
            if self.is_plot_valid():
                data = self._plot.GetData()  # type: vtkContextMapper2D
                arr = data.GetInputArrayToProcess(0, self._table)  # type: vtkAbstractArray
                actColId = VTK64BitTimePlotSupport.get_column_id(self._table, arr)
        return actColId

    @staticmethod
    def get_next_bit_seq_id(bitSeqId: int, numBitSequences: int, least: bool = True) -> int:
        if (np.little_endian and least) or (not np.little_endian and not least):
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
    def normalize_to_dtype(bitSequences: list, dtype=np.uint16):
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
            nextId = VTK64BitTimePlotSupport.get_next_bit_seq_id(q,
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
    def get_time_stamp_from_16bits(bitSequences: Sequence[np.uint16]) -> int:
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

    def get_x_range(self, chart: vtkChart, plotId: int) -> Tuple[float, float]:
        xr = ()
        with self.get_plot_from_chart(plotId, chart):
            if self.is_plot_valid():
                xAxis = self._plot.GetXAxis()  # type: vtkAxis
                xr = xAxis.GetMinimum(), xAxis.GetMaximum()
        return xr

    def get_offset_time_value(self, chart: vtkChart, plotId: int, columnId: int) -> int:
        """
        Determine an offset time stamp for a column Id.
        Ex:
        To generate full(64-bit) timestamps for values in a column,
        you'd need to add an offset to each value listed in that column.

        full_time_stamp_value[i] = offset + values[i]

        Args:
            chart (vtkChart)
            plotId (int): id plot
            columnId (int): a column id

        Returns:
            int: offset time for all values in columnId of plot's input data.
        """
        ofstTime = -1
        bitSequences = np.zeros((4,), dtype=np.uint16)
        bitSeqId = columnId - 2
        with self.get_plot_from_chart(plotId, chart):
            if self.is_plot_valid():
                for i in range(1, 4):
                    arr = self._table.GetColumn(i + 1)
                    arrName = arr.GetName()
                    try:
                        bitSequences[i] = np.uint16(int(arrName))
                    except ValueError:  # if arrName = ""
                        pass
                logger.debug(f"Bit Sequence: {bitSequences}")
                if np.little_endian:
                    bitSequences[:bitSeqId] = [0] * bitSeqId
                else:
                    bitSequences[(bitSeqId + 1):] = [0] * (3 - bitSeqId)
                ofstTime = VTK64BitTimePlotSupport.get_time_stamp_from_16bits(bitSequences)
        return ofstTime

    def check_step_up(self, chart: vtkChart, plotId: int) -> bool:
        xmin, xmax = self.get_x_range(chart, plotId)
        maxRange = (1 << 16) - 1
        boundsOverflow = np.abs(xmax - xmin) > maxRange
        return boundsOverflow

    def check_step_dn(self, chart: vtkChart, plotId: int) -> bool:
        boundsEqual = True
        with self.get_plot_from_chart(plotId, chart):
            if self.is_plot_valid():
                data = self._plot.GetData()  # type: vtkContextMapper2D
                arr = data.GetInputArrayToProcess(
                    0, self._table)  # type: vtkAbstractArray
                tmin, tmax = arr.GetRange()
                boundsEqual = np.abs(tmax - tmin) < 1
        return boundsEqual

    def get_new_column_id(self, chart: vtkChart, plotId: int):
        actColId = self.get_active_column_id(chart, plotId)
        newColId = actColId
        actBitSeqId = actColId - 2

        if self.check_step_dn(chart, plotId):
            newColId = VTK64BitTimePlotSupport.get_next_bit_seq_id(actBitSeqId,
                                                                   4) + 2
            logger.debug(f"Stepping down {actColId}->{newColId}")
        elif self.check_step_up(chart, plotId):
            newColId = (VTK64BitTimePlotSupport.get_next_bit_seq_id(
                actBitSeqId, 4, least=False) + 2)
            logger.debug(f"Stepping up {actColId}->{newColId}")
        else:
            logger.debug(
                f"No need to step up/down. Active Column Id: {actColId}")

        return newColId

    def update_active_column_id(self, chart: vtkChart, plotId: int,
                                newColId: int) -> bool:
        updated = False
        actColId = self.get_active_column_id(chart, plotId)

        with self.get_plot_from_chart(plotId, chart):
            if self.is_plot_valid():
                if actColId == newColId:
                    updated = False
                else:
                    logger.debug(
                        f"Update active column: {actColId} -> {newColId}")

                    actBitSeqId = actColId - 2
                    newBitSeqId = newColId - 2
                    if (VTK64BitTimePlotSupport.get_next_bit_seq_id(
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

    def select_column(self, chart: vtkChart, plotId: int) -> int:
        """Select a set of 16 bits used for x-axis data.
        It will do so only when x-axis range is insufficient i.e, beyond 65535.
        """
        logger.debug(f"Plot {plotId}: Dynamically select column")
        depth = 0
        maxDepth = 4
        newColId = 0
        while depth < maxDepth:
            depth += 1
            newColId = self.get_new_column_id(chart, plotId)
            if not self.update_active_column_id(chart, plotId, newColId):
                break

        return newColId

    def is_bit_sequencing_enabled(self, chart: vtkChart):
        numPlots = chart.GetNumberOfPlots()
        bEnabled = True
        for i in range(numPlots):
            stat = self.get_active_column_id(chart, i) > 0
            logger.debug(
                f"Plot {i}: Bit sequencing was {'enabled' if stat else 'disabled'}."
            )
            bEnabled &= stat
        return bEnabled

    def enable_bit_sequencing(self, chart: vtkChart, plotId: int):
        with self.get_plot_from_chart(plotId, chart):
            if self.is_plot_valid():
                self._table.GetColumn(5).SetName(str(0))
        self.update_active_column_id(chart, plotId, 5)

    def disable_bit_sequencing(self, chart: vtkChart, plotId: int):
        with self.get_plot_from_chart(plotId, chart):
            if self.is_plot_valid():
                self.update_active_column_id(chart, plotId, 0)

    def resetChartXAxisRange(self, chart: vtkChart):
        numPlots = chart.GetNumberOfPlots()
        for i in range(numPlots):
            self.reset_xaxis_range(chart, i)

    def reset_xaxis_range(self, chart: vtkChart, plotId: int):
        actColId = self.get_active_column_id(chart, plotId)
        with self.get_plot_from_chart(plotId, chart):
            if self.is_plot_valid():
                tArr = self._table.GetColumn(actColId)
                tMin, tMax = tArr.GetRange()
                xAxis = chart.GetAxis(vtkAxis.BOTTOM)
                xAxis.SetMinimum(tMin)
                xAxis.SetMaximum(tMax)
                xAxis_top = chart.GetAxis(vtkAxis.TOP)
                xAxis_top.SetMinimum(tMin)
                xAxis_top.SetMaximum(tMax)

    def dynamic_select_columns(self, chart: vtkChart):
        """Dynamically select columns (if bit sequencing was enabled)
        Args:
            chart (vtkChart): a chart contains a number of plots
        """
        selectedColIds = []
        if self._precise:
            numPlots = chart.GetNumberOfPlots()
            for i in range(numPlots):
                colId = self.select_column(chart, i)
                if colId:
                    selectedColIds.append(colId)
        return selectedColIds

    def compute_offset_value(self, chart: vtkChart):
        columnIds = []
        bBitSeqEnabled = self.is_bit_sequencing_enabled(chart)

        numPlots = chart.GetNumberOfPlots()
        if self._precise:
            if bBitSeqEnabled:
                # Dynamically select a suitable column
                columnIds.extend(self.dynamic_select_columns(chart))
            else:
                # Enable bit sequencing
                for i in range(numPlots):
                    self.enable_bit_sequencing(chart, i)
                    # and dynamically select columns
                    actColId = self.select_column(chart, i)
                    columnIds.append(actColId)
                    # self.resetXaxisRange(
                    #     chart, i)  # needed to fit axis to current column data

            # Check for uniqueness. All plots must have same active column.
            try:
                activeColId = min(columnIds)
            except ValueError:
                return
            self._activeBitSeqId = activeColId - 2
            if min(columnIds) != max(columnIds):
                columnIds[:] = [activeColId] * len(columnIds)

            # Enforce uniform active column. Get offset time
            self._ofstTime = (1 << 63) - 1
            for i in range(numPlots):
                self.update_active_column_id(chart, i, columnIds[i])
                ofstITime = self.get_offset_time_value(chart, i, columnIds[i])
                if ofstITime >= 0:
                    self._ofstTime = min(ofstITime, self._ofstTime)
            logger.debug(f"Offset time: {pd.to_datetime(self._ofstTime)}")
        elif not self._precise:
            if bBitSeqEnabled:
                # Disable bit sequencing
                for i in range(numPlots):
                    self.disable_bit_sequencing(chart, i)
                    # self.resetXaxisRange(
                    #     chart, i)  # needed to fit axis to current column data
            self._ofstTime = 0
            self._activeBitSeqId = -1

    def transformValue(self, value: Any, inverse=False):
        """Build the full 64 bit integer value corresponding to input value in 
        the context of given chart
        The inverse operation would subtract the offset and return the 16-bit integer"""
        if not inverse:
            if self._precise and self._enabled and self._ofstTime is not None:
                bitSequences = np.array([self._ofstTime], np.uint64).view(np.uint16)
                bitSequencesList = bitSequences.tolist()
                bitSequencesList[self._activeBitSeqId] = int(bitSequencesList[self._activeBitSeqId] + value)
                logger.debug(f"Pre-normalize: {bitSequencesList}")
                VTK64BitTimePlotSupport.normalize_to_dtype(bitSequencesList,
                                                           dtype=np.uint16)
                logger.debug(f"Post-normalize: {bitSequencesList}")
                return VTK64BitTimePlotSupport.get_time_stamp_from_16bits(bitSequencesList)
            elif self._precise or self._enabled:
                try:
                    return np.int64(value)
                except OverflowError:
                    return int(value)
            elif value > (1 << 32):
                try:
                    return np.int64(value)
                except OverflowError:
                    return int(value)
            else:
                return value
        elif self._precise and self._enabled:
            bitSequences = np.array([value], np.uint64).view(np.uint16).tolist()
            try:
                return bitSequences[self._activeBitSeqId]
            except (TypeError, IndexError) as _:
                return bitSequences[0]
        elif self._enabled:
            try:
                return np.int64(value)
            except OverflowError:
                return int(value)
        elif value > (1 << 32):
            try:
                return np.int64(value)
            except OverflowError:
                return int(value)
        else:
            return value

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

        self.compute_offset_value(chart)

        xAxis.Update()
        tick_positions_vtk_arr = xAxis.GetTickPositions()
        tick_positions_np_arr = numpy_support.vtk_to_numpy(tick_positions_vtk_arr)
        tss = []

        logger.debug(f"TimeStamp | Tick Position | time")
        for pos in tick_positions_np_arr:
            t = self.transformValue(pos)
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
            tick_label = tick_label.replace("nano", str(ts.nanosecond).zfill(3))
            tick_labels.InsertNextValue(tick_label)

        xAxis.SetCustomTickPositions(tick_positions_vtk_arr, tick_labels)
        try:
            xAxis.SetTitle(tss[0].strftime(prefixFmt))
        except IndexError:
            logger.critical(f"There is no data for chart. Setting xAxis title to 'X Axis'")
            xAxis.SetTitle('X Axis')
        xAxis.Update()

    @staticmethod
    def round_hour(ret):
        parts = ret.split('T')
        hour_str = parts[1]

        if len(hour_str) == 5:
            hour = datetime.datetime.strptime(hour_str, '%H:%M')
        else:
            hour = datetime.datetime.strptime(hour_str, '%H:%M:%S')

        if hour.minute >= 30:
            hour += datetime.timedelta(hours=1)

        if len(hour_str) == 5:
            hour = hour.replace(minute=0)
            round_hour_str = hour.strftime('%H:%M')
        else:
            hour = hour.replace(minute=0, second=0)
            round_hour_str = hour.strftime('%H:%M:%S')

        new_ret = f"{parts[0]}T{round_hour_str}"

        return new_ret
