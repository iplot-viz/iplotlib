import time
from functools import partial
from threading import Thread

import numpy as np

import iplotLogging.setupLogger as ls

logger = ls.get_logger(__name__)

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
                for (stack_id, signals) in plot.signals.items():
                    all_signals += signals

        self.signals = {s.name: s for s in all_signals}

        signals_by_ds = dict()
        for s in all_signals:
            if signals_by_ds.get(s.data_source):
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
        logger.info(F"STREAM START vars={varnames} ds={ds} startSubscription={self.da.startSubscription}")
        streaming_thread = Thread(name="receiver", target=self.da.startSubscription, args=(ds,), kwargs={'params': varnames}, daemon=True)
        streaming_thread.start()
        self.streamers.append(streaming_thread)

        while not self.stop_flag:
            for varname in varnames:
                dobj = self.da.getNextData(ds, varname)

                if dobj is not None and dobj.xdata is not None and len(dobj.xdata) > 0 and callback is not None:
                    callback(varname, dobj)
            time.sleep(0.1)

        logger.info("Issuing stop subscription...")

        # self.da.stopSubscription(ds)
        stopping_thread = Thread(name="stopper", target=self.da.stopSubscription, args=(ds,))
        stopping_thread.start()

    def stop(self):
        self.stop_flag = True
        self.collectors.clear()
        self.streamers.clear()

    def handler(self, callback, varname, dobj):
        signal = self.signals.get(varname)
        if hasattr(signal, 'inject_external'):
            result = dict(alias_map={
                        'time': {'idx': 0, 'independent': True},
                        'data': {'idx': 1}
                        },
                      d0=dobj.xdata,
                      d1=dobj.ydata,
                      d2=[],
                      d0_unit=dobj.xunit,
                      d1_unit=dobj.yunit,
                      d2_unit='')
            signal.inject_external(append=True, **result)
            logger.info(f"Updated {varname} with {len(dobj.xdata)} new samples")
            callback(signal)
