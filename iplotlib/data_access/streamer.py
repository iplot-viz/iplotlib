import time
from functools import partial
from threading import Thread, Lock

import numpy as np

import iplotLogging.setupLogger as Sl

logger = Sl.get_logger(__name__)

# Max wait for the first live sample before anchoring the archive end at "now".
_FIRST_LIVE_WAIT_S = 2.0

# Sliding-window refresh cadence. Skipped for windows shorter than this period.
_TOPUP_PERIOD_S = 3600


# CWS-SCSU-0000:CU510{1,2,3,4}-TT-XI, CTRL-SYSM-CUB-4505-61:CU000{1,2,3}-HTH-TT,BUIL-B36-VA-RT-RT1:CL0001-TT02-STATE
# CTRL-SYSM-CUB-4505-61:CU0001-HTH-TT

class CanvasStreamer:

    def __init__(self, da):
        self.da = da
        self.stop_flag = False
        self.signals = {}
        self.collectors = []
        self.streamers = []
        self._inject_locks = {}
        self._window_ns = 0
        self._max_points = 0
        self._ds_to_signals = {}
        self._callback = None
        self._first_live_pending = set()

    def _signal_lock(self, signal):
        lock = self._inject_locks.get(signal.uid)
        if lock is None:
            lock = Lock()
            self._inject_locks[signal.uid] = lock
        return lock

    @staticmethod
    def _make_payload(signal, x, y, *, y_min=None, y_max=None, xunit='', yunit=''):
        """Build an inject_external payload. Envelope signals expand to
        dmin/dmax/davg; sources without min/max reuse ``y`` for both bounds."""
        is_envelope = signal is not None and getattr(signal, 'envelope', False)
        if is_envelope:
            ymin = y if y_min is None else y_min
            ymax = y if y_max is None else y_max
            return dict(
                alias_map={'time': {'idx': 0, 'independent': True},
                           'dmin': {'idx': 1},
                           'dmax': {'idx': 2},
                           'davg': {'idx': 3}},
                d0=x, d1=ymin, d2=ymax, d3=y,
                d0_unit=xunit, d1_unit=yunit, d2_unit=yunit, d3_unit=yunit,
            )
        return dict(
            alias_map={'time': {'idx': 0, 'independent': True},
                       'data': {'idx': 1}},
            d0=x, d1=y, d2=[], d3=[],
            d0_unit=xunit, d1_unit=yunit, d2_unit='', d3_unit='',
        )

    @staticmethod
    def _current_arrays(signal):
        """Read data_store as ``(x, y, ymin, ymax)``. ``y`` is davg for
        envelope signals; ymin/ymax are None for raw signals."""
        ds = signal.data_store
        x = np.asarray(ds[0]) if len(ds) > 0 else np.array([])
        if getattr(signal, 'envelope', False) and len(ds) >= 4:
            return x, np.asarray(ds[3]), np.asarray(ds[1]), np.asarray(ds[2])
        y = np.asarray(ds[1]) if len(ds) > 1 else np.array([])
        return x, y, None, None

    def _fetch_archive_window(self, ds, signal, start_ns, end_ns):
        # get_archive_window only falls back to envelope on UDA overflow;
        # envelope signals must call get_envelope directly.
        is_envelope = getattr(signal, 'envelope', False)
        fetch = self.da.get_envelope if is_envelope else self.da.get_archive_window
        try:
            data = fetch(
                ds,
                varname=signal.name,
                tsS=str(start_ns),
                tsE=str(end_ns),
                **self._archive_kwargs(signal),
            )
        except Exception as exc:
            logger.warning(f"Archive fetch failed for {signal.name}: {exc}")
            return None, None, None, None, None, None

        if data is None or getattr(data, 'errcode', -1) != 0:
            return None, None, None, None, None, None
        return self._unpack_archive(data)

    def _fetch_last_archive_value(self, ds, signal, end_ns):
        try:
            data = self.da.get_archive_window(
                ds,
                varname=signal.name,
                tsS="0",
                tsE=str(end_ns),
                nbp=1,
                decType="last",
            )
        except Exception as exc:
            logger.warning(f"Last-value fetch failed for {signal.name}: {exc}")
            return None, None, None, None, None, None
        if data is None or getattr(data, 'errcode', -1) != 0:
            return None, None, None, None, None, None
        return self._unpack_archive(data)

    def _archive_kwargs(self, signal=None):
        kwargs = {}
        if self._max_points > 0:
            kwargs['nbp'] = self._max_points
        # Envelope buckets already cover boundaries; extremities=True crashes UDA.
        if not (signal is not None and getattr(signal, 'envelope', False)):
            kwargs['extremities'] = True
        return kwargs

    def _apply_cap(self, signal):
        # Drop-oldest trim to honour the per-signal sample cap. Caller must hold _signal_lock.
        if self._max_points <= 0:
            return
        x, y, y_min, y_max = self._current_arrays(signal)
        if len(x) <= self._max_points:
            return
        n = self._max_points
        payload = self._make_payload(
            signal, x[-n:], y[-n:],
            y_min=y_min[-n:] if y_min is not None else None,
            y_max=y_max[-n:] if y_max is not None else None,
            xunit=getattr(signal.data_store[0], 'unit', ''),
            yunit=getattr(signal.data_store[1], 'unit', ''),
        )
        signal.inject_external(append=False, **payload)

    def start(self, canvas, callback, window_ns: int = None, max_points: int = 0):
        self.stop_flag = False
        self._first_live_pending.clear()
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
            s._streaming_has_live = False
            signals[s.name] = signals.get(s.name, []) + [s]
        self.signals = signals

        signals_by_ds = dict()
        for s in all_signals:
            if signals_by_ds.get(s.data_source):
                if s.name not in signals_by_ds[s.data_source]:
                    signals_by_ds[s.data_source].append(s.name)
            else:
                signals_by_ds[s.data_source] = [s.name]

        self._window_ns = int(window_ns) if window_ns else 0
        self._max_points = int(max_points) if max_points else 0
        self._ds_to_signals = {ds: [s for s in all_signals if s.data_source == ds]
                               for ds in signals_by_ds.keys()}
        self._callback = callback

        for ds in signals_by_ds.keys():
            logger.info(F"Starting streamer for data source: {ds}")
            self.start_stream(ds, signals_by_ds[ds], partial(self.handler, callback))

        if self._window_ns > 0:
            Thread(name="archive-backfill",
                   target=self._archive_backfill,
                   args=(self._ds_to_signals, self._window_ns, callback),
                   daemon=True).start()

            if self._window_ns > _TOPUP_PERIOD_S * int(1e9):
                Thread(name="archive-topup",
                       target=self._hourly_topup,
                       daemon=True).start()

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
                if dobj is not None:
                    callback(varname, dobj)
            time.sleep(0.1)  # 100 ms

        logger.info("Issuing stop subscription...")

        # self.da.stopSubscription(ds)
        stopping_thread = Thread(name="stopper", target=self.da.stop_subscription, args=(ds,))
        stopping_thread.start()

    def handler(self, callback, varname, dobj):
        signals_by_name = self.signals.get(varname)
        if signals_by_name is None:
            logger.warning(f'signal name {varname} was not found')
            return
        for signal in signals_by_name:
            if not hasattr(signal, 'inject_external'):
                continue
            x_data = dobj.xdata
            y_data = dobj.ydata
            if signal.uid in self._first_live_pending:
                cur_x = signal.x_data
                cur_y = signal.y_data
                if cur_x is not None and len(cur_x) > 0 and len(x_data) > 0:
                    cur_x_arr = np.asarray(cur_x)
                    cur_y_arr = np.asarray(cur_y)
                    flat_x = np.asarray(x_data[:1], dtype=cur_x_arr.dtype)
                    flat_y = np.asarray([cur_y_arr[-1]], dtype=cur_y_arr.dtype)
                    x_data = np.concatenate([flat_x, np.asarray(x_data)])
                    y_data = np.concatenate([flat_y, np.asarray(y_data)])
                self._first_live_pending.discard(signal.uid)
            result = self._make_payload(
                signal, x_data, y_data,
                xunit=dobj.xunit, yunit=dobj.yunit,
            )
            with self._signal_lock(signal):
                signal.inject_external(append=True, **result)
                self._apply_cap(signal)
            if len(x_data) > 0 and self._window_ns > 0:
                now_ns = int(time.time() * 1e9)
                if int(x_data[-1]) >= now_ns - self._window_ns:
                    signal._streaming_has_live = True
            logger.debug(f"Updated {varname} with {len(dobj.xdata)} new samples")
            callback(signal)

    def _archive_backfill(self, ds_to_signals: dict, window_ns: int, callback):
        """Seed each signal's visible window with archive data, anchoring the
        end at the first live sample (or now, if none arrives in time)."""
        for ds, signals in ds_to_signals.items():
            if self.stop_flag:
                return
            for signal in signals:
                if self.stop_flag:
                    return
                self._backfill_signal(ds, signal, window_ns, callback)

    def _backfill_signal(self, ds: str, signal, window_ns: int, callback):
        archive_end_ns, found_live = self._wait_for_first_live(signal)
        archive_start_ns = archive_end_ns - window_ns

        ax, ay, ay_min, ay_max, xunit, yunit = self._fetch_archive_window(
            ds, signal, archive_start_ns, archive_end_ns)
        if ax is None or len(ax) == 0:
            ax, ay, ay_min, ay_max, xunit, yunit = self._fetch_last_archive_value(
                ds, signal, archive_end_ns)
        if ax is None or len(ax) == 0:
            return

        with self._signal_lock(signal):
            cur_x, cur_y, cur_ymin, cur_ymax = self._current_arrays(signal)
            new_x = np.asarray(ax)
            new_y = np.asarray(ay)
            merged_x = np.concatenate([new_x, cur_x])
            merged_y = np.concatenate([new_y, cur_y])
            merged_ymin = None
            merged_ymax = None
            if getattr(signal, 'envelope', False):
                new_ymin = np.asarray(ay_min) if ay_min is not None else new_y
                new_ymax = np.asarray(ay_max) if ay_max is not None else new_y
                merged_ymin = np.concatenate(
                    [new_ymin, cur_ymin if cur_ymin is not None else cur_y])
                merged_ymax = np.concatenate(
                    [new_ymax, cur_ymax if cur_ymax is not None else cur_y])
            payload = self._make_payload(
                signal, merged_x, merged_y,
                y_min=merged_ymin, y_max=merged_ymax,
                xunit=xunit, yunit=yunit,
            )
            signal.inject_external(append=False, **payload)
            self._apply_cap(signal)
            signal._streaming_has_live = True

        if not found_live:
            self._first_live_pending.add(signal.uid)

        logger.info(f"Archive backfill for {signal.name}: {len(ax)} points prepended")
        callback(signal)

    def _wait_for_first_live(self, signal):
        """Returns (end_ns, found_live) so the caller can distinguish path 1 from
        path 2 (no live sample within the timeout)."""
        deadline = time.monotonic() + _FIRST_LIVE_WAIT_S
        while time.monotonic() < deadline and not self.stop_flag:
            x = signal.x_data
            if x is not None and len(x) > 0:
                return int(x[0]), True
            time.sleep(0.05)
        return int(time.time() * 1e9), False

    def _hourly_topup(self):
        """Refresh the most recent ``_TOPUP_PERIOD_S`` from archive each period
        and drop samples older than ``self._window_ns``."""
        period_ns = _TOPUP_PERIOD_S * int(1e9)
        while not self.stop_flag:
            target = time.monotonic() + _TOPUP_PERIOD_S
            while time.monotonic() < target and not self.stop_flag:
                time.sleep(1)
            if self.stop_flag:
                return
            for ds, signals in self._ds_to_signals.items():
                for signal in signals:
                    if self.stop_flag:
                        return
                    self._topup_signal(ds, signal, period_ns)

    def _topup_signal(self, ds: str, signal, period_ns: int):
        now_ns = int(time.time() * 1e9)
        last_period_start_ns = now_ns - period_ns
        cutoff_ns = now_ns - self._window_ns

        ax, ay, ay_min, ay_max, xunit, yunit = self._fetch_archive_window(
            ds, signal, last_period_start_ns, now_ns)
        if ax is None or len(ax) == 0:
            return

        with self._signal_lock(signal):
            cur_x, cur_y, cur_ymin, cur_ymax = self._current_arrays(signal)
            keep_mask = (cur_x >= cutoff_ns) & (cur_x < last_period_start_ns)
            kept_x = cur_x[keep_mask]
            kept_y = cur_y[keep_mask]

            new_x = np.asarray(ax)
            new_y = np.asarray(ay)
            merged_x = np.concatenate([kept_x, new_x])
            merged_y = np.concatenate([kept_y, new_y])
            merged_ymin = None
            merged_ymax = None
            if getattr(signal, 'envelope', False):
                kept_ymin = (cur_ymin[keep_mask]
                             if cur_ymin is not None else kept_y)
                kept_ymax = (cur_ymax[keep_mask]
                             if cur_ymax is not None else kept_y)
                new_ymin = np.asarray(ay_min) if ay_min is not None else new_y
                new_ymax = np.asarray(ay_max) if ay_max is not None else new_y
                merged_ymin = np.concatenate([kept_ymin, new_ymin])
                merged_ymax = np.concatenate([kept_ymax, new_ymax])

            payload = self._make_payload(
                signal, merged_x, merged_y,
                y_min=merged_ymin, y_max=merged_ymax,
                xunit=xunit, yunit=yunit,
            )
            signal.inject_external(append=False, **payload)
            self._apply_cap(signal)
            signal._streaming_has_live = True

        logger.info(f"Top-up for {signal.name}: {len(ax)} archive points, "
                    f"{len(kept_x)} prior live points retained")
        if self._callback:
            self._callback(signal)

    def change_window(self, new_window_ns: int):
        """Update the visible window mid-stream. If wider than the current one,
        fetch the newly-revealed range from the archive."""
        if new_window_ns <= 0:
            return
        old_window_ns = self._window_ns
        self._window_ns = int(new_window_ns)
        if new_window_ns > old_window_ns and self._ds_to_signals:
            Thread(name="archive-gap-fill",
                   target=self._gap_fill,
                   args=(old_window_ns, new_window_ns),
                   daemon=True).start()

    def _gap_fill(self, old_window_ns: int, new_window_ns: int):
        now_ns = int(time.time() * 1e9)
        new_start_ns = now_ns - new_window_ns
        old_start_ns = now_ns - old_window_ns
        for ds, signals in self._ds_to_signals.items():
            if self.stop_flag:
                return
            for signal in signals:
                if self.stop_flag:
                    return
                self._gap_fill_signal(ds, signal, new_start_ns, old_start_ns)

    def _gap_fill_signal(self, ds: str, signal, start_ns: int, end_ns: int):
        ax, ay, ay_min, ay_max, xunit, yunit = self._fetch_archive_window(
            ds, signal, start_ns, end_ns)
        if ax is None or len(ax) == 0:
            return

        with self._signal_lock(signal):
            cur_x, cur_y, cur_ymin, cur_ymax = self._current_arrays(signal)
            new_x = np.asarray(ax)
            new_y = np.asarray(ay)
            merged_x = np.concatenate([new_x, cur_x])
            merged_y = np.concatenate([new_y, cur_y])
            merged_ymin = None
            merged_ymax = None
            if getattr(signal, 'envelope', False):
                new_ymin = np.asarray(ay_min) if ay_min is not None else new_y
                new_ymax = np.asarray(ay_max) if ay_max is not None else new_y
                merged_ymin = np.concatenate(
                    [new_ymin, cur_ymin if cur_ymin is not None else cur_y])
                merged_ymax = np.concatenate(
                    [new_ymax, cur_ymax if cur_ymax is not None else cur_y])
            payload = self._make_payload(
                signal, merged_x, merged_y,
                y_min=merged_ymin, y_max=merged_ymax,
                xunit=xunit, yunit=yunit,
            )
            signal.inject_external(append=False, **payload)
            self._apply_cap(signal)
            signal._streaming_has_live = True

        logger.info(f"Gap-fill for {signal.name}: {len(ax)} archive points prepended")
        if self._callback:
            self._callback(signal)

    @staticmethod
    def _unpack_archive(data):
        """Returns ``(xdata, y_or_davg, ymin, ymax, xunit, yunit)``. ymin/ymax
        are None for raw DataObj responses."""
        if hasattr(data, 'ydata_avg') and data.ydata_avg is not None:
            ymin = getattr(data, 'ydata_min', None)
            ymax = getattr(data, 'ydata_max', None)
            return data.xdata, data.ydata_avg, ymin, ymax, data.xunit, data.yunit
        return data.xdata, data.ydata, None, None, data.xunit, data.yunit

    def stop(self):
        self.stop_flag = True
        self.collectors.clear()
        self.streamers.clear()
        self._first_live_pending.clear()
