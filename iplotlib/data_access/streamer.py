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


import time
from functools import partial
from threading import Thread

import iplotLogging.setupLogger as Sl

logger = Sl.get_logger(__name__)


# CWS-SCSU-0000:CU510{1,2,3,4}-TT-XI, CTRL-SYSM-CUB-4505-61:CU000{1,2,3}-HTH-TT,BUIL-B36-VA-RT-RT1:CL0001-TT02-STATE
# CTRL-SYSM-CUB-4505-61:CU0001-HTH-TT

class CanvasStreamer:

    def __init__(self, da):
        self.da = da
        self.stop_flag = False
        self.signals = {}
        self.collectors = []
        self.streamers = []

    def start(self, canvas, callback):
        self.stop_flag = False
        all_signals = []
        for col in canvas.plots:
            for plot in col:
                if plot:
                    for (stack_id, signals) in plot.signals.items():
                        for signal in signals:
                            if signal.stream_valid:
                                all_signals.append(signal)

        signals = {}
        for s in all_signals:
            signals[s.name] = signals.get(s.name, []) + [s]
        self.signals = signals

        signals_by_ds = dict()
        for s in all_signals:
            if signals_by_ds.get(s.data_source):
                if s.name not in signals_by_ds[s.data_source]:
                    signals_by_ds[s.data_source].append(s.name)
            else:
                signals_by_ds[s.data_source] = [s.name]

        for ds in signals_by_ds.keys():
            logger.info(F"Starting streamer for data source: {ds}")
            self.start_stream(ds, signals_by_ds[ds], partial(self.handler, callback))

    def start_stream(self, ds, varnames, callback):
        collect_thread = Thread(name="collector", target=self.stream_thread, args=(ds, varnames, callback), daemon=True)

        collect_thread.start()
        self.collectors.append(collect_thread)

    def stream_thread(self, ds, varnames, callback):
        logger.info(F"STREAM START vars={varnames} ds={ds} startSubscription={self.da.start_subscription}")
        streaming_thread = Thread(name="receiver", target=self.da.start_subscription, args=(ds,),
                                  kwargs={'params': varnames}, daemon=True)
        streaming_thread.start()
        self.streamers.append(streaming_thread)

        while not self.stop_flag:
            for varname in varnames:
                dobj = self.da.get_next_data(ds, varname)

                if dobj is not None and dobj.xdata is not None and len(dobj.xdata) > 0 and callback is not None:
                    callback(varname, dobj)
            time.sleep(0.1)

        logger.info("Issuing stop subscription...")

        # self.da.stopSubscription(ds)
        stopping_thread = Thread(name="stopper", target=self.da.stop_subscription, args=(ds,))
        stopping_thread.start()

    def stop(self):
        self.stop_flag = True
        self.collectors.clear()
        self.streamers.clear()

    def handler(self, callback, varname, dobj):
        signals_by_name = self.signals.get(varname)
        if signals_by_name is None:
            logger.warning(f'signal name {varname} was not found')
            return
        for signal in signals_by_name:
            if hasattr(signal, 'inject_external'):
                result = dict(alias_map={
                    'time': {'idx': 0, 'independent': True},
                    'data': {'idx': 1}
                },
                    d0=dobj.xdata,
                    d1=dobj.ydata,
                    d2=[],
                    d3=[],
                    d0_unit=dobj.xunit,
                    d1_unit=dobj.yunit,
                    d2_unit='',
                    d3_unit='')
                signal.inject_external(append=True, **result)
                logger.debug(f"Updated {varname} with {len(dobj.xdata)} new samples")
                callback(signal)
