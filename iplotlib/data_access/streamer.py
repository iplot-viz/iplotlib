import time
from functools import partial
from threading import Lock
from types import SimpleNamespace

import numpy as np

from PySide6.QtCore import QObject, QThread, Slot

import iplotLogging.setupLogger as Sl
from iplotlib.core.decimation import bucket_reduce_envelope, minmax_decimate

logger = Sl.get_logger(__name__)

# Max wait for the first live sample before anchoring the archive end at "now".
_FIRST_LIVE_WAIT_S = 2.0

# Sliding-window refresh cadence. Skipped for windows shorter than this period.
_TOPUP_PERIOD_S = 3600

# Injection cadence: polled chunks are buffered and merged so the O(buffer)
# cost of inject_external is paid once per period instead of once per poll.
_INJECT_PERIOD_S = 1.0

# Newest span kept at full resolution when the cap forces decimation.
_RAW_TAIL_S = 120

# Slice size for re-fetching an archive window the server truncated: small
# requests are served reliably where a repeated full-window request is not.
_ARCHIVE_SLICE_NS = 3600 * int(1e9)

# Rounds of retries over refused slices; refusals are transient, so a later
# attempt usually gets the data.
_ARCHIVE_RETRY_ROUNDS = 3

# QThread wait budget on stop(). Loops poll stop_flag frequently, so most
# workers exit well within this; stragglers (e.g. a receiver blocked on the
# SSE socket) are parked in _lingering_threads instead of blocking the UI.
_STOP_WAIT_MS = 200

# Keep Python references to QThreads that outlive their CanvasStreamer:
# unlike daemon threads, a QThread whose wrapper is garbage-collected while
# still running brings the process down.
_lingering_threads = []


def _prune_lingering():
    _lingering_threads[:] = [(t, w) for (t, w) in _lingering_threads
                             if not t.isFinished()]


class _StreamJob(QObject):
    """Runs a blocking callable inside its own QThread.

    Mirrors the worker/moveToThread pattern: the thread's started signal
    invokes run(), and run() quits the thread's event loop when the target
    returns so the QThread can finish and be joined.
    """

    def __init__(self, target):
        super().__init__()
        self._target = target

    @Slot()
    def run(self):
        try:
            self._target()
        except Exception:
            logger.exception("Streaming worker crashed")
        finally:
            QThread.currentThread().quit()


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
        self._qt_threads = []

    def _spawn(self, name: str, target):
        """Start ``target`` on a dedicated QThread and keep it referenced."""
        _prune_lingering()
        thread = QThread()
        thread.setObjectName(name)
        job = _StreamJob(target)
        job.moveToThread(thread)
        thread.started.connect(job.run)
        self._qt_threads.append((thread, job))
        thread.start()
        return thread

    @staticmethod
    def _carrier(signal):
        """Expression signals stream through their child variable: the child
        owns the raw buffers and the parent re-evaluates on injection."""
        children = getattr(signal, 'children', None)
        if children and len(children) == 1 and hasattr(children[0], 'inject_external'):
            return children[0]
        return signal

    @staticmethod
    def _reprocess(signal):
        try:
            signal._do_data_processing()
        except Exception:
            logger.exception(f"Processing failed for {signal.name}")

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

    @staticmethod
    def _sanitize_archive_chunk(ax, ay, ay_min, ay_max, cursor, req_end,
                                reject_boundary_pair=False):
        """Keep the part of a reply that advances the fetch: drops the
        synthetic end-of-request projection appended to truncated replies and
        anything before ``cursor``. With ``reject_boundary_pair`` a reply
        carrying only the extremities boundary points counts as a refusal.
        Returns None when nothing new remains."""
        if ax is None or len(ax) == 0:
            return None
        ax = np.asarray(ax)
        ay = np.asarray(ay)
        if ay_min is not None:
            ay_min = np.asarray(ay_min)
            ay_max = np.asarray(ay_max)
        margin = max((req_end - cursor) // 100, int(1e9))
        # A lone final point far from its predecessor is the extremities
        # projection at the requested end, not coverage. Two-point replies are
        # legitimate (a flat signal's boundary samples).
        if (len(ax) >= 3 and int(ax[-1]) >= req_end - margin
                and int(ax[-2]) < req_end - margin
                and int(ax[-1]) - int(ax[-2]) > margin):
            ax, ay = ax[:-1], ay[:-1]
            if ay_min is not None:
                ay_min, ay_max = ay_min[:-1], ay_max[:-1]
        keep = ax >= cursor
        if not keep.any():
            return None
        ax, ay = ax[keep], ay[keep]
        if ay_min is not None:
            ay_min, ay_max = ay_min[keep], ay_max[keep]
        if reject_boundary_pair and len(ax) <= 2:
            interior = (ax > cursor + margin) & (ax < req_end - margin)
            if not interior.any():
                return None
        return ax, ay, ay_min, ay_max

    def _fetch_archive_window_complete(self, ds, signal, start_ns, end_ns):
        """Fetch ``[start_ns, end_ns]`` tolerating truncated replies: the UDA
        server can stop a long window early (with a synthetic extremity at the
        requested end masking the cut) and refuses to resume the remainder as
        one request. After a short first reply the fetch continues in
        ``_ARCHIVE_SLICE_NS`` slices, skipping any slice it refuses. Returns
        the same tuple as ``_fetch_archive_window``."""
        xs, ys, y_mins, y_maxs = [], [], [], []
        xunit = yunit = None
        has_bounds = False
        # Replies that stop just short of the end (e.g. envelope buckets) are
        # complete enough; only a clearly early stop is worth resuming. Floored
        # above start_ns so even a sub-margin window is fetched once.
        resume_below = max(start_ns + 1,
                           end_ns - max((end_ns - start_ns) // 100, int(1e9)))
        max_chunks = int((end_ns - start_ns) // _ARCHIVE_SLICE_NS) + 8
        cursor = start_ns
        sliced = False
        holes = []
        for _ in range(max_chunks):
            if cursor >= resume_below:
                break
            req_end = min(cursor + _ARCHIVE_SLICE_NS, end_ns) if sliced else end_ns
            ax, ay, ay_min, ay_max, xu, yu = self._fetch_archive_window(
                ds, signal, cursor, req_end)
            chunk = self._sanitize_archive_chunk(
                ax, ay, ay_min, ay_max, cursor, req_end,
                reject_boundary_pair=sliced)
            if chunk is None:
                if not sliced:
                    if ax is None or len(ax) == 0:
                        break
                    sliced = True
                    continue
                holes.append((cursor, req_end))
                cursor = req_end + 1
                continue
            cx, cy, c_min, c_max = chunk
            xunit, yunit = xu, yu
            xs.append(cx)
            ys.append(cy)
            y_mins.append(c_min if c_min is not None else cy)
            y_maxs.append(c_max if c_max is not None else cy)
            has_bounds = has_bounds or c_min is not None
            if not sliced and int(cx[-1]) < resume_below:
                sliced = True
                logger.info(f"Archive reply for {signal.name} truncated; continuing in slices")
            cursor = int(cx[-1]) + 1

        # Refusals are transient (a slice denied to one signal is served to the
        # next moments later): retry skipped slices in rounds. A boundary-only
        # pair (a genuinely flat slice) is only accepted once it has persisted
        # through every round.
        for attempt in range(_ARCHIVE_RETRY_ROUNDS):
            if not holes:
                break
            final = attempt == _ARCHIVE_RETRY_ROUNDS - 1
            remaining = []
            for h_start, h_end in holes:
                ax, ay, ay_min, ay_max, xu, yu = self._fetch_archive_window(
                    ds, signal, h_start, h_end)
                chunk = self._sanitize_archive_chunk(
                    ax, ay, ay_min, ay_max, h_start, h_end,
                    reject_boundary_pair=not final)
                if chunk is None:
                    remaining.append((h_start, h_end))
                    continue
                cx, cy, c_min, c_max = chunk
                if xunit is None:
                    xunit, yunit = xu, yu
                xs.append(cx)
                ys.append(cy)
                y_mins.append(c_min if c_min is not None else cy)
                y_maxs.append(c_max if c_max is not None else cy)
                has_bounds = has_bounds or c_min is not None
            holes = remaining
        for _ in holes:
            logger.warning(f"Archive slice for {signal.name} not served after retries; leaving a gap")

        if not xs:
            return None, None, None, None, None, None
        order = sorted(range(len(xs)), key=lambda i: int(xs[i][0]))
        x = np.concatenate([xs[i] for i in order])
        y = np.concatenate([ys[i] for i in order])
        y_min = np.concatenate([y_mins[i] for i in order]) if has_bounds else None
        y_max = np.concatenate([y_maxs[i] for i in order]) if has_bounds else None
        return x, y, y_min, y_max, xunit, yunit

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

    def _cut_overlap_tail(self, signal, first_ts: int):
        """Trim buffered samples at or after ``first_ts`` so the batch can be
        appended monotonically, and return them as ``(x, y, ymin, ymax)`` for
        the caller to fold back into the batch. Returns None when the batch
        does not overlap the buffer. Caller must hold _signal_lock."""
        x, y, y_min, y_max = self._current_arrays(signal)
        if len(x) == 0 or int(x[-1]) < first_ts:
            return None
        keep = np.asarray(x) < first_ts
        payload = self._make_payload(
            signal, np.asarray(x)[keep], np.asarray(y)[keep],
            y_min=np.asarray(y_min)[keep] if y_min is not None else None,
            y_max=np.asarray(y_max)[keep] if y_max is not None else None,
            xunit=getattr(signal.data_store[0], 'unit', ''),
            yunit=getattr(signal.data_store[1], 'unit', ''),
        )
        signal.inject_external(append=False, **payload)
        return (np.asarray(x)[~keep], np.asarray(y)[~keep],
                np.asarray(y_min)[~keep] if y_min is not None else None,
                np.asarray(y_max)[~keep] if y_max is not None else None)

    @staticmethod
    def _fold_tail(tail, x, y):
        """Merge a cut buffer tail with a live batch chronologically. On a
        re-emitted timestamp the batch sample wins. Returns (x, y, ymin, ymax);
        ymin/ymax are None unless the tail carried envelope bounds."""
        tx, ty, t_min, t_max = tail
        mx = np.concatenate([tx, np.asarray(x)])
        my = np.concatenate([ty, np.asarray(y)])
        m_min = np.concatenate([t_min, np.asarray(y)]) if t_min is not None else None
        m_max = np.concatenate([t_max, np.asarray(y)]) if t_max is not None else None
        order = np.argsort(mx, kind='stable')
        keep = np.empty(len(order), dtype=bool)
        keep[-1] = True
        keep[:-1] = mx[order][1:] > mx[order][:-1]
        sel = order[keep]
        return (mx[sel], my[sel],
                m_min[sel] if m_min is not None else None,
                m_max[sel] if m_max is not None else None)

    def _apply_cap(self, signal):
        """Honour the per-signal cap as maximum stored points: the newest
        ``_RAW_TAIL_S`` stay raw and older samples are decimated into the
        remaining budget, preserving extremes. Caller must hold _signal_lock.
        Returns True when the buffer was actually reduced."""
        if self._max_points <= 0:
            return False
        x, y, y_min, y_max = self._current_arrays(signal)
        n = len(x)
        if n <= self._max_points:
            return False
        x = np.asarray(x)
        y = np.asarray(y)
        if y_min is not None:
            y_min = np.asarray(y_min)
            y_max = np.asarray(y_max)

        tail = int(np.searchsorted(x, int(x[-1]) - _RAW_TAIL_S * int(1e9),
                                   side='left'))
        budget = self._max_points - (n - tail)
        if tail > 0 and budget > 4:
            if y_min is not None:
                hx, hmin, hmax, havg = bucket_reduce_envelope(
                    x[:tail], y_min[:tail], y_max[:tail], y[:tail], budget)
                y_min = np.concatenate([hmin, y_min[tail:]])
                y_max = np.concatenate([hmax, y_max[tail:]])
            else:
                hx, havg = minmax_decimate(x[:tail], y[:tail], budget // 2)
            x = np.concatenate([hx, x[tail:]])
            y = np.concatenate([havg, y[tail:]])

        # Guarantee the cap even when the raw tail alone exceeds it.
        if len(x) > self._max_points:
            k = self._max_points
            x, y = x[-k:], y[-k:]
            if y_min is not None:
                y_min, y_max = y_min[-k:], y_max[-k:]

        payload = self._make_payload(
            signal, x, y,
            y_min=y_min, y_max=y_max,
            xunit=getattr(signal.data_store[0], 'unit', ''),
            yunit=getattr(signal.data_store[1], 'unit', ''),
        )
        signal.inject_external(append=False, **payload)
        return True

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
            # A '*' inherited from the last Draw would outlive its data here.
            s.isDownsampled = False
            cname = self._carrier(s).name
            signals[cname] = signals.get(cname, []) + [s]
        self.signals = signals

        signals_by_ds = dict()
        for s in all_signals:
            cname = self._carrier(s).name
            if signals_by_ds.get(s.data_source):
                if cname not in signals_by_ds[s.data_source]:
                    signals_by_ds[s.data_source].append(cname)
            else:
                signals_by_ds[s.data_source] = [cname]

        self._window_ns = int(window_ns) if window_ns else 0
        self._max_points = int(max_points) if max_points else 0
        self._ds_to_signals = {ds: [s for s in all_signals if s.data_source == ds]
                               for ds in signals_by_ds.keys()}
        self._callback = callback

        for ds in signals_by_ds.keys():
            logger.info(F"Starting streamer for data source: {ds}")
            self.start_stream(ds, signals_by_ds[ds], partial(self.handler, callback))

        if self._window_ns > 0:
            self._spawn("archive-backfill",
                        partial(self._archive_backfill,
                                self._ds_to_signals, self._window_ns, callback))

            if self._window_ns > _TOPUP_PERIOD_S * int(1e9):
                self._spawn("archive-topup", self._hourly_topup)

    def start_stream(self, ds, varnames, callback):
        logger.info(F"STREAM START vars={varnames} ds={ds} startSubscription={self.da.start_subscription}")
        # Receiver: blocking SSE subscription loop feeding per-variable queues.
        receive_thread = self._spawn(
            "receiver", partial(self.da.start_subscription, ds, params=varnames))
        self.streamers.append(receive_thread)

        collect_thread = self._spawn(
            "collector", partial(self.stream_thread, ds, varnames, callback))
        self.collectors.append(collect_thread)

    def stream_thread(self, ds, varnames, callback):
        pending = {varname: [] for varname in varnames}
        next_flush = time.monotonic() + _INJECT_PERIOD_S
        while not self.stop_flag:
            for varname in varnames:
                dobj = self.da.get_next_data(ds, varname)
                if dobj is not None:
                    pending[varname].append(dobj)
            if time.monotonic() >= next_flush:
                self._flush_batches(pending, callback)
                next_flush = time.monotonic() + _INJECT_PERIOD_S
            time.sleep(0.1)  # 100 ms

        self._flush_batches(pending, callback)
        logger.info("Issuing stop subscription...")
        # Already off the UI thread; safe to call synchronously on the way out.
        self.da.stop_subscription(ds)

    @staticmethod
    def _flush_batches(pending: dict, callback):
        for varname, chunks in pending.items():
            if not chunks:
                continue
            pending[varname] = []
            callback(varname, CanvasStreamer._merge_chunks(chunks))

    @staticmethod
    def _merge_chunks(chunks):
        """Merge buffered chunks into a single chronological payload; empty
        chunks are kept only as a fallback so the handler still slides the
        window."""
        filled = [c for c in chunks if len(c.xdata) > 0]
        if not filled:
            return chunks[-1]
        last = filled[-1]
        if len(filled) == 1:
            x = np.asarray(last.xdata)
            y = np.asarray(last.ydata)
        else:
            x = np.concatenate([np.asarray(c.xdata) for c in filled])
            y = np.concatenate([np.asarray(c.ydata) for c in filled])
        # The feed interleaves and re-emits ranges; a stable sort restores
        # monotonicity without losing real samples.
        order = np.argsort(x, kind='stable')
        if not np.array_equal(order, np.arange(len(order))):
            logger.debug(f"Reordered {len(x)} samples of a live batch")
            x = x[order]
            y = y[order]
        # For a re-emitted timestamp the stable sort leaves the newest emission
        # last; keep that one.
        keep = np.empty(len(x), dtype=bool)
        keep[-1] = True
        keep[:-1] = x[1:] > x[:-1]
        if not keep.all():
            logger.debug(f"Dropped {int((~keep).sum())} duplicate timestamps from a live batch")
            x = x[keep]
            y = y[keep]
        return SimpleNamespace(xdata=x, ydata=y, xunit=last.xunit, yunit=last.yunit)

    def handler(self, callback, varname, dobj):
        signals_by_name = self.signals.get(varname)
        if signals_by_name is None:
            logger.warning(f'signal name {varname} was not found')
            return
        for signal in signals_by_name:
            carrier = self._carrier(signal)
            if not hasattr(carrier, 'inject_external'):
                continue
            x_data = dobj.xdata
            y_data = dobj.ydata
            if len(x_data) == 0:
                # No new samples: skip injection but keep the window sliding.
                callback(signal)
                continue
            first_live = signal.uid in self._first_live_pending
            if first_live:
                cur_x = carrier.x_data
                cur_y = carrier.y_data
                if cur_x is not None and len(cur_x) > 0 and len(x_data) > 0:
                    cur_x_arr = np.asarray(cur_x)
                    cur_y_arr = np.asarray(cur_y)
                    flat_x = np.asarray(x_data[:1], dtype=cur_x_arr.dtype)
                    flat_y = np.asarray([cur_y_arr[-1]], dtype=cur_y_arr.dtype)
                    x_data = np.concatenate([flat_x, np.asarray(x_data)])
                    y_data = np.concatenate([flat_y, np.asarray(y_data)])
                self._first_live_pending.discard(signal.uid)
            with self._signal_lock(carrier):
                tail = self._cut_overlap_tail(carrier, int(x_data[0]))
                y_min = y_max = None
                if tail is not None and not first_live:
                    # Overlapped buffer samples are real feed data; on the first
                    # live batch the tail is the backfill's synthetic boundary
                    # point, a projection to discard.
                    x_data, y_data, y_min, y_max = self._fold_tail(
                        tail, x_data, y_data)
                result = self._make_payload(
                    carrier, x_data, y_data, y_min=y_min, y_max=y_max,
                    xunit=dobj.xunit, yunit=dobj.yunit,
                )
                carrier.inject_external(append=True, **result)
                if self._apply_cap(carrier):
                    # Flag the plotted signal, not the carrier: the streaming
                    # reprocess path never aggregates children's flags.
                    signal.isDownsampled = True
            if carrier is not signal:
                self._reprocess(signal)
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
        carrier = self._carrier(signal)
        archive_end_ns, found_live = self._wait_for_first_live(carrier)
        archive_start_ns = archive_end_ns - window_ns

        ax, ay, ay_min, ay_max, xunit, yunit = self._fetch_archive_window_complete(
            ds, carrier, archive_start_ns, archive_end_ns)
        if ax is None or len(ax) == 0:
            ax, ay, ay_min, ay_max, xunit, yunit = self._fetch_last_archive_value(
                ds, carrier, archive_end_ns)
        if ax is None or len(ax) == 0:
            return
        if ay_min is not None and not getattr(signal, 'envelope', False):
            # An envelope reply to a raw request means UDA overflowed and
            # decimated — the same condition the Draw path flags.
            signal.isDownsampled = True

        with self._signal_lock(carrier):
            cur_x, cur_y, cur_ymin, cur_ymax = self._current_arrays(carrier)
            new_x = np.asarray(ax)
            new_y = np.asarray(ay)
            if len(cur_x) > 0:
                # The synthetic end-of-window point would break monotonicity.
                keep = new_x < int(cur_x[0])
                new_x = new_x[keep]
                new_y = new_y[keep]
                if ay_min is not None:
                    ay_min = np.asarray(ay_min)[keep]
                if ay_max is not None:
                    ay_max = np.asarray(ay_max)[keep]
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
                carrier, merged_x, merged_y,
                y_min=merged_ymin, y_max=merged_ymax,
                xunit=xunit, yunit=yunit,
            )
            carrier.inject_external(append=False, **payload)
            if self._apply_cap(carrier):
                signal.isDownsampled = True
            signal._streaming_has_live = True

        if carrier is not signal:
            self._reprocess(signal)
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
        carrier = self._carrier(signal)
        now_ns = int(time.time() * 1e9)
        last_period_start_ns = now_ns - period_ns
        cutoff_ns = now_ns - self._window_ns

        ax, ay, ay_min, ay_max, xunit, yunit = self._fetch_archive_window_complete(
            ds, carrier, last_period_start_ns, now_ns)
        if ax is None or len(ax) == 0:
            return
        if ay_min is not None and not getattr(signal, 'envelope', False):
            signal.isDownsampled = True

        with self._signal_lock(carrier):
            cur_x, cur_y, cur_ymin, cur_ymax = self._current_arrays(carrier)
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
                carrier, merged_x, merged_y,
                y_min=merged_ymin, y_max=merged_ymax,
                xunit=xunit, yunit=yunit,
            )
            carrier.inject_external(append=False, **payload)
            self._apply_cap(carrier)
            signal._streaming_has_live = True

        if carrier is not signal:
            self._reprocess(signal)
        logger.info(f"Top-up for {signal.name}: {len(ax)} archive points, "
                    f"{len(kept_x)} prior live points retained")
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
        # Give workers a short grace period; they all poll stop_flag. Anything
        # still running (e.g. a receiver blocked on the SSE socket) is parked
        # in the module registry so its QThread stays referenced until it ends.
        for thread, job in self._qt_threads:
            thread.quit()
            if not thread.wait(_STOP_WAIT_MS):
                _lingering_threads.append((thread, job))
        self._qt_threads.clear()
        self.collectors.clear()
        self.streamers.clear()
        self._first_live_pending.clear()
