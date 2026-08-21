import os
import time
from functools import partial
from threading import Lock
from types import SimpleNamespace

import numpy as np

from PySide6.QtCore import QObject, QThread, Slot

import iplotLogging.setupLogger as Sl
from iplotlib.core.decimation import minmax_decimate

logger = Sl.get_logger(__name__)

# Periodic full-window refresh cadence: even without cap overflow, the
# archive progressively supplants the live buffer so the two stay consistent.
_TOPUP_PERIOD_S = 3600

# Minimum spacing between cap-triggered refreshes of the same signal, so a
# fast signal overflowing its buffer cannot hammer UDA. Overridable through
# MINT_STREAMING_REFRESH_SECONDS.
_DEFAULT_REFRESH_MIN_INTERVAL_S = 300

# Minimum spacing between refreshes of ANY signal. Without it, a periodic
# tick or a simultaneous overflow across a large workspace fires one archive
# request per signal back to back; each reinjection reprocesses and redraws
# on the draw thread, which is what makes focus changes and autoscale crawl.
_REFRESH_GLOBAL_SPACING_S = 2.0

# Hard bound on drain rounds per 100 ms pass of the stream thread. Guarantees
# the loop reaches its flush and its sleep no matter what the feed returns.
_DRAIN_MAX_ROUNDS = 256


def _refresh_min_interval_s() -> float:
    try:
        return max(5.0, float(os.environ.get('MINT_STREAMING_REFRESH_SECONDS',
                                             _DEFAULT_REFRESH_MIN_INTERVAL_S)))
    except (TypeError, ValueError):
        return _DEFAULT_REFRESH_MIN_INTERVAL_S

# Injection cadence: polled chunks are buffered and merged so the O(buffer)
# cost of inject_external is paid once per period instead of once per poll.
# Raising MINT_STREAMING_INJECT_SECONDS trades display latency for CPU: every
# injection re-copies the buffer, reprocesses expressions and redraws, so on
# large workspaces with a high point cap a 2-5 s cadence cuts CPU roughly
# proportionally.
_DEFAULT_INJECT_PERIOD_S = 1.0
_MAX_INJECT_PERIOD_S = 10.0


def _inject_period_s(window_ns: int = 0, max_points: int = 0) -> float:
    """Injection cadence. Every injection re-copies the buffer, reprocesses
    expressions and redraws, so injecting faster than the display can
    resolve is pure waste: with ``max_points`` samples across ``window_ns``
    one bucket lasts window/max_points, and a 7-day window at 10k points
    resolves nothing finer than about a minute. The cadence therefore
    follows the bucket duration, clamped to [1 s, 10 s] so short windows
    stay as responsive as before and wide ones cut CPU by up to 10x.
    MINT_STREAMING_INJECT_SECONDS overrides the result outright."""
    override = os.environ.get('MINT_STREAMING_INJECT_SECONDS')
    if override is not None:
        try:
            return max(0.2, float(override))
        except (TypeError, ValueError):
            pass
    if window_ns > 0 and max_points > 0:
        bucket_s = (window_ns / 1e9) / max_points
        return min(_MAX_INJECT_PERIOD_S, max(_DEFAULT_INJECT_PERIOD_S, bucket_s))
    return _DEFAULT_INJECT_PERIOD_S

# Newest live span kept whole. The archiver lags the live feed by roughly this
# much, so the backfill stops here and the feed covers the rest; it is also the
# span left at full resolution when the cap forces decimation. Overridable
# through MINT_STREAMING_LIVE_SECONDS for tuning without a code change.
_DEFAULT_LIVE_RETENTION_S = 120


def _live_retention_s() -> int:
    try:
        return max(0, int(os.environ.get('MINT_STREAMING_LIVE_SECONDS',
                                          _DEFAULT_LIVE_RETENTION_S)))
    except (TypeError, ValueError):
        return _DEFAULT_LIVE_RETENTION_S


# Bucket count requested when an (opt-in) envelope signal is fetched.
_ENVELOPE_TARGET_POINTS = 1920

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
        self._refresh_pending = set()
        self._last_refresh = {}
        self._verbose = set()
        # Signals whose visible content is a held last-known value (archive
        # empty in the window, or the feed re-announcing a stale value).
        # Their buffers are normalized to a zero-order hold so an empty span
        # is drawn flat instead of as an invented ramp.
        self._hold_semantics = set()
        self._last_refresh_any = 0.0
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

    def _fetch_archive_range(self, ds, signal, start_ns, end_ns):
        # Read as a server-side envelope only when the user opted this signal
        # into one (Envelope column). A plain raw read is used otherwise, which
        # the access layer still decimates to an envelope on server overflow.
        is_envelope = getattr(signal, 'envelope', False)
        if is_envelope:
            fetch = self.da.get_envelope
            kwargs = {'nbp': self._max_points or _ENVELOPE_TARGET_POINTS}
        else:
            fetch = self.da.get_archive_window
            kwargs = self._archive_kwargs(signal)
        try:
            data = fetch(
                ds,
                varname=signal.name,
                tsS=str(start_ns),
                tsE=str(end_ns),
                **kwargs,
            )
        except Exception as exc:
            logger.warning(f"Archive fetch failed for {signal.name}: {exc}")
            return None, None, None, None, None, None

        if data is None or getattr(data, 'errcode', -1) != 0:
            return None, None, None, None, None, None
        return self._unpack_archive(data)

    def _fetch_last_archive_value(self, ds, signal, end_ns):
        # The last-point read can be very expensive on a DB back-end, so it
        # follows the variable table convention: only signals that opt in
        # through the Extremities column pay for it.
        if not getattr(signal, 'extremities', False):
            return None, None, None, None, None, None
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
            # Keep the point budget if the server overflows into an envelope.
            kwargs['env_nbp'] = self._max_points
        # Extremities is the user's per-signal opt-in (table column), the same
        # contract as the envelope column. Envelope requests omit it:
        # extremities=True crashes UDA.
        if not (signal is not None and getattr(signal, 'envelope', False)):
            kwargs['extremities'] = bool(getattr(signal, 'extremities', False))
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

    def _window_is_live_only(self) -> bool:
        """True when the window is no wider than the archiver's lag, so the
        archive holds nothing inside it and live data covers the whole span.

        Below that width every archive range inverts: the backfill asks for
        [now - window, now - retention], whose start is AFTER its end once
        window < retention (a 60 s window against a 120 s lag), and the same
        arithmetic in the refresh and the last-value fallback. Those queries
        are meaningless, and the archive genuinely has nothing to give for
        such a window, so the archive work is skipped entirely."""
        return 0 < self._window_ns <= _live_retention_s() * int(1e9)

    def _has_window_hole(self, signal):
        """True when the buffer no longer reaches the left edge of the window,
        i.e. the safety trim dropped history that only the archive can supply.

        This replaces a plain over-the-cap test as the refresh trigger. A busy
        signal sits permanently over the cap while still covering the whole
        window, and refreshing it then bought nothing: it re-fetched data the
        buffer already had, once per signal per interval, which is the archive
        request storm that made focus changes and autoscale crawl. What
        actually warrants a round trip is a gap at the left edge.
        Caller must hold _signal_lock."""
        if self._max_points <= 0 or self._window_ns <= 0:
            return False
        if self._window_is_live_only():
            # Nothing archived inside the window; live fills it by itself.
            return False
        x, _, _, _ = self._current_arrays(signal)
        if len(x) == 0:
            return False
        window_start = int(time.time() * 1e9) - self._window_ns
        # A tenth of the window of missing history is worth one request.
        return int(np.asarray(x)[0]) > window_start + self._window_ns // 10

    def _apply_cap(self, signal):
        """Safety valve only: the regular cap enforcement is the refresh
        (drop + ONE archive re-ask for the whole window at the budget, per
        the mint#78 point-5 algorithm). Trimming the oldest locally on every
        overflow instead would eat the coarse archive buckets far faster
        than real time — each dropped live second costs one multi-second
        bucket off the left edge, visibly shrinking the window — so the
        local trim only kicks in beyond twice the cap (refresh delayed or
        archive unavailable) to bound memory. Caller must hold _signal_lock.
        Returns True when samples were dropped."""
        if self._max_points <= 0:
            return False
        x, y, y_min, y_max = self._current_arrays(signal)
        n = len(x)
        if n <= 2 * self._max_points:
            return False
        k = self._max_points
        x = np.asarray(x)[-k:]
        y = np.asarray(y)[-k:]
        if y_min is not None:
            y_min = np.asarray(y_min)[-k:]
            y_max = np.asarray(y_max)[-k:]

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
            # Full-window refresh worker: reacts to cap overflows for any
            # window length and ticks periodically for long windows.
            self._spawn("archive-refresh", self._refresh_loop)

    def start_stream(self, ds, varnames, callback):
        logger.debug(F"Subscribing to {ds} for {len(varnames)} variables: {varnames}")
        # Receiver: blocking SSE subscription loop feeding per-variable queues.
        receive_thread = self._spawn(
            "receiver", partial(self.da.start_subscription, ds, params=varnames))
        self.streamers.append(receive_thread)

        collect_thread = self._spawn(
            "collector", partial(self.stream_thread, ds, varnames, callback))
        self.collectors.append(collect_thread)

    def stream_thread(self, ds, varnames, callback):
        pending = {varname: [] for varname in varnames}
        inject_period = _inject_period_s(self._window_ns, self._max_points)
        logger.info(f"Injection cadence for {ds}: {inject_period:.1f}s")
        next_flush = time.monotonic() + inject_period
        while not self.stop_flag:
            # Bounded drain. The pass polls each variable up to
            # _DRAIN_MAX_ROUNDS times, so its termination depends on nothing
            # the feed does: a feed that always has something to hand over
            # (empty heartbeat chunks, or production outpacing the poll) must
            # not keep this loop from reaching the flush and the sleep.
            # 256 rounds per 100 ms is ~2560 chunks/s/variable of drain
            # capacity -- far above any feed, so no backlog can build (the
            # original one-chunk-per-pass drain capped at 10/s, which is the
            # backlog drift), while the hard bound plus the unconditional
            # sleep is what keeps this loop from ever becoming a busy poll.
            for _ in range(_DRAIN_MAX_ROUNDS):
                got_any = False
                for varname in varnames:
                    dobj = self.da.get_next_data(ds, varname)
                    if dobj is not None:
                        pending[varname].append(dobj)
                        got_any = True
                if not got_any or self.stop_flag:
                    break
            if time.monotonic() >= next_flush:
                self._flush_batches(pending, callback)
                next_flush = time.monotonic() + inject_period
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

    def _reduce_live_batch(self, signal, x, y):
        """Reduce a live batch to the window's display resolution.

        A fast signal delivers far more samples per injection than a window of
        ``max_points`` can show: at 7 days and 10k points one bucket lasts a
        minute, so a kHz feed contributes 60000 samples where 2 would do. Left
        alone the buffer fills with invisible detail, the safety trim then eats
        the left edge, and every eviction costs an archive round trip to put it
        back -- the request storm. Reducing the batch to min/max pairs per
        bucket bounds buffer growth by elapsed time instead of sample rate, so
        the buffer keeps covering the window and refreshes become rare.

        Extremes are preserved at their true coordinates (min/max per bucket),
        and NaN line breaks survive, so this is the same reduction the archive
        would have applied. Envelope buffers are left alone: their band is
        already a reduction. Returns ``(x, y, reduced)``."""
        if self._max_points <= 0 or self._window_ns <= 0:
            return x, y, False
        if getattr(signal, 'envelope', False):
            return x, y, False
        x = np.asarray(x)
        y = np.asarray(y)
        if len(x) < 4:
            return x, y, False
        bucket_ns = max(1, self._window_ns // self._max_points)
        span_ns = int(x[-1]) - int(x[0])
        if span_ns <= 0:
            return x, y, False
        target_pairs = int(span_ns // bucket_ns)
        if target_pairs <= 0:
            target_pairs = 1
        if len(x) <= 2 * target_pairs:
            return x, y, False
        rx, ry = minmax_decimate(x, y, target_pairs)
        if len(rx) >= len(x):
            return x, y, False
        return rx, ry, True

    @staticmethod
    def _step_across_gaps(x, y, max_gap_ns: int):
        """Insert a zero-order-hold point before every sample that follows a
        gap wider than ``max_gap_ns``, returning ``(x, y, changed)``.

        A process variable archived on change has no samples while it does
        not change, so the only correct reading of a long empty span is that
        the value held. Joining the two ends with a straight line instead
        asserts a linear ramp that never happened -- and when the two ends
        differ only in the last representable digit (an archive value stored
        as float32 versus the same value arriving live as float64, say), that
        invented ramp is what autoscale magnifies into a full-height slope
        across the window for a signal that is in fact constant.

        Applied only to signals under hold semantics (sparse ones, whose
        buffers are small), so the O(n) scan is negligible and densely
        sampled traces keep plain interpolation between their samples."""
        x = np.asarray(x)
        y = np.asarray(y)
        if len(x) < 2 or max_gap_ns <= 0:
            return x, y, False
        gaps = np.diff(x.astype(np.int64)) > max_gap_ns
        if not gaps.any():
            return x, y, False
        # A gap at index i sits between sample i and i+1: hold y[i] until
        # just before x[i+1].
        idx = np.flatnonzero(gaps)
        hold_x = x[idx + 1] - 1
        hold_y = y[idx]
        out_x = np.concatenate([x, hold_x])
        out_y = np.concatenate([y, hold_y])
        order = np.argsort(out_x, kind='stable')
        out_x, out_y = out_x[order], out_y[order]
        # A held point landing exactly on a real sample is redundant.
        keep = np.empty(len(out_x), dtype=bool)
        keep[-1] = True
        keep[:-1] = out_x[1:] > out_x[:-1]
        return out_x[keep], out_y[keep], True

    def _apply_hold_semantics(self, signal, window_ns: int):
        """Normalize a held/sparse signal's buffer to a zero-order hold.
        Caller must hold _signal_lock. Returns True if rewritten."""
        if window_ns <= 0:
            return False
        x, y, y_min, y_max = self._current_arrays(signal)
        if y_min is not None:
            # An envelope buffer carries its own band; leave it alone.
            return False
        # A gap is anything far wider than the visible sample spacing.
        max_gap_ns = max(1, window_ns // 100)
        new_x, new_y, changed = self._step_across_gaps(x, y, max_gap_ns)
        if not changed:
            return False
        payload = self._make_payload(
            signal, new_x, new_y,
            xunit=getattr(signal.data_store[0], 'unit', ''),
            yunit=getattr(signal.data_store[1], 'unit', ''),
        )
        signal.inject_external(append=False, **payload)
        return True

    def _trim_to_window(self, signal, window_start_ns: int):
        """Drop samples that have slid out of the visible window, holding
        the newest of them as an anchor at the left edge so the trace still
        spans it. Nothing else trims the left edge for sparse signals (the
        archive refresh only runs for verbose ones), so without this a long
        stream keeps samples from before the window and the X axis stretches
        past it. Rewriting costs O(buffer), so it is amortized: it only runs
        once the oldest sample has drifted a twentieth of the window behind
        the edge. Caller must hold _signal_lock. Returns True if rewritten."""
        if window_start_ns <= 0:
            return False
        x, y, y_min, y_max = self._current_arrays(signal)
        if len(x) == 0:
            return False
        x = np.asarray(x)
        margin = max(1, self._window_ns // 20)
        if int(x[0]) >= window_start_ns - margin:
            return False

        y = np.asarray(y)
        inside = x >= window_start_ns
        if not inside.any():
            # Everything is behind the window: keep the last value only,
            # held at the edge.
            keep_x = np.asarray([window_start_ns], dtype=x.dtype)
            keep_y = np.asarray([y[-1]], dtype=y.dtype)
            keep_min = keep_max = None
        else:
            keep_x = x[inside]
            keep_y = y[inside]
            keep_min = np.asarray(y_min)[inside] if y_min is not None else None
            keep_max = np.asarray(y_max)[inside] if y_max is not None else None
            if (~inside).any() and int(keep_x[0]) > window_start_ns:
                # Hold the last pre-window value at the edge, as a step (see
                # _hold_stale_samples): anchor plus a repeat just before the
                # first in-window sample, so the held span is flat rather
                # than a slope drawn from the edge to that sample.
                held = np.asarray([y[~inside][-1]], dtype=y.dtype)
                anchor_x = np.asarray(
                    [window_start_ns, int(keep_x[0]) - 1], dtype=x.dtype)
                anchor_y = np.concatenate([held, held])
                keep_x = np.concatenate([anchor_x, keep_x])
                keep_y = np.concatenate([anchor_y, keep_y])
                if keep_min is not None:
                    keep_min = np.concatenate([anchor_y, keep_min])
                    keep_max = np.concatenate([anchor_y, keep_max])

        payload = self._make_payload(
            signal, keep_x, keep_y, y_min=keep_min, y_max=keep_max,
            xunit=getattr(signal.data_store[0], 'unit', ''),
            yunit=getattr(signal.data_store[1], 'unit', ''),
        )
        signal.inject_external(append=False, **payload)
        return True

    @staticmethod
    def _hold_stale_samples(x, y, window_start_ns: int, hold_to_ns: int):
        """Convert samples older than the visible window into a held
        last-known value.

        A live feed announces a signal that has not changed in a long time by
        re-emitting its last value with that value's ORIGINAL timestamp (e.g.
        a point stamped 8 July arriving today). Appending it at face value
        stretches the X range weeks outside the requested window and squashes
        every other trace on the plot. Semantically such a sample is not "a
        measurement at 8 July"; it is "the value has been this since 8 July",
        so it must be drawn as a constant line across the window instead.

        Returns ``(x, y, clamped)``. With no stale samples the inputs come
        back untouched. Otherwise the newest stale value is anchored at
        ``window_start_ns``: if the batch is entirely stale it is held to
        ``hold_to_ns`` as a two-point flat line, and if fresher samples
        follow, the anchor holds the old value up to the first of them.
        """
        x = np.asarray(x)
        y = np.asarray(y)
        if len(x) == 0 or window_start_ns <= 0:
            return x, y, False
        stale = x < window_start_ns
        if not stale.any():
            return x, y, False

        # The newest stale sample is the last known value.
        hold_value = y[stale][-1]
        anchor_x = np.asarray([window_start_ns], dtype=x.dtype)
        anchor_y = np.asarray([hold_value], dtype=y.dtype)

        fresh_x = x[~stale]
        fresh_y = y[~stale]
        if len(fresh_x) == 0:
            # Nothing inside the window: a flat line spanning it.
            end_x = np.asarray([hold_to_ns], dtype=x.dtype)
            if hold_to_ns <= window_start_ns:
                return anchor_x, anchor_y, True
            return (np.concatenate([anchor_x, end_x]),
                    np.concatenate([anchor_y, anchor_y]), True)
        if int(fresh_x[0]) <= window_start_ns:
            # A real sample already sits on the boundary; no anchor needed.
            return fresh_x, fresh_y, True
        # Zero-order hold: repeat the held value immediately before the first
        # fresh sample so the trace stays flat and then steps. Emitting only
        # the anchor and the fresh sample would leave the renderer to draw a
        # straight line between them, i.e. a slope across the whole window
        # for a signal that was in fact constant until it changed.
        step_x = np.asarray([int(fresh_x[0]) - 1], dtype=x.dtype)
        return (np.concatenate([anchor_x, step_x, fresh_x]),
                np.concatenate([anchor_y, anchor_y, fresh_y]), True)

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
            clamped = False
            if self._window_ns > 0:
                now_ns = int(time.time() * 1e9)
                x_data, y_data, clamped = self._hold_stale_samples(
                    x_data, y_data, now_ns - self._window_ns, now_ns)
                if clamped:
                    self._hold_semantics.add(signal.uid)
                    logger.info(
                        f"{varname}: live sample(s) older than the window; "
                        f"holding the last known value across it")
                if not clamped:
                    x_data, y_data, reduced = self._reduce_live_batch(
                        carrier, x_data, y_data)
                    if reduced:
                        logger.debug(
                            f"{varname}: live batch reduced to "
                            f"{len(x_data)} points for the window resolution")
                        signal.isDownsampled = True
            if first_live:
                cur_x = carrier.x_data
                if not clamped and cur_x is not None and len(cur_x) > 0 \
                        and len(x_data) > 0:
                    # Break the line between the archive block and the live
                    # feed rather than joining them with a diagonal: the archive
                    # ends ~2 min behind the first live sample, so a NaN placed
                    # just before that sample leaves the gap visible instead of
                    # interpolating across empty time. A clamped batch is a
                    # held value, not a fresh block, so it needs no break.
                    gap_x = np.asarray([int(x_data[0]) - 1],
                                       dtype=np.asarray(cur_x).dtype)
                    x_data = np.concatenate([gap_x, np.asarray(x_data)])
                    y_data = np.concatenate([[np.nan], np.asarray(y_data)])
                self._first_live_pending.discard(signal.uid)
            with self._signal_lock(carrier):
                tail = self._cut_overlap_tail(carrier, int(x_data[0]))
                y_min = y_max = None
                if tail is not None:
                    x_data, y_data, y_min, y_max = self._fold_tail(
                        tail, x_data, y_data)
                result = self._make_payload(
                    carrier, x_data, y_data, y_min=y_min, y_max=y_max,
                    xunit=dobj.xunit, yunit=dobj.yunit,
                )
                carrier.inject_external(append=True, **result)
                if self._window_ns > 0:
                    self._trim_to_window(
                        carrier, int(time.time() * 1e9) - self._window_ns)
                    if signal.uid in self._hold_semantics:
                        # The held value spans the empty part of the window;
                        # a new sample must step off it, not ramp from it.
                        self._apply_hold_semantics(carrier, self._window_ns)
                if self._apply_cap(carrier):
                    # Flag the plotted signal, not the carrier: the streaming
                    # reprocess path never aggregates children's flags.
                    signal.isDownsampled = True
                if self._has_window_hole(carrier):
                    # History missing at the left edge: only the archive can
                    # supply it, so ask the refresh worker for one call.
                    self._mark_refresh(signal)
                if carrier is not signal:
                    # Reprocess while still holding the carrier's lock. The
                    # expression reads the carrier's data_store, which must
                    # not be mutated concurrently by another writer (topup,
                    # backfill) while that read is in progress, or the parent
                    # expression sees a torn (mismatched-length or partially
                    # cleared) buffer and produces garbled output.
                    self._reprocess(signal)
            if len(x_data) > 0 and self._window_ns > 0:
                now_ns = int(time.time() * 1e9)
                if int(x_data[-1]) >= now_ns - self._window_ns:
                    signal._streaming_has_live = True
            logger.debug(f"Updated {varname} with {len(dobj.xdata)} new samples")
            callback(signal)

    def _archive_backfill(self, ds_to_signals: dict, window_ns: int, callback):
        """Seed each signal's visible window from the archive in a single
        request per signal. The archive lags the live feed, so it is read only
        up to ``now - live_retention`` and the feed fills the newest span; the
        first live batch then breaks the line so the two blocks are not joined
        by a diagonal. A signal is read as an envelope only when the user opted
        it into one."""
        now_ns = int(time.time() * 1e9)
        live_only = self._window_is_live_only()
        # A window narrower than the archiver's lag contains nothing archived,
        # and asking for [now - window, now - retention] would invert the
        # range. Read the last value only, so the trace shows the held value
        # immediately instead of an empty plot, and let live fill the window.
        end_ns = now_ns if live_only else now_ns - _live_retention_s() * int(1e9)
        start_ns = now_ns - window_ns
        for ds, signals in ds_to_signals.items():
            for signal in signals:
                if self.stop_flag:
                    return
                carrier = self._carrier(signal)
                self._first_live_pending.add(signal.uid)
                if live_only:
                    self._backfill_last_value(ds, signal, carrier, end_ns, callback)
                    continue
                ax, ay, ay_min, ay_max, xunit, yunit = self._fetch_archive_range(
                    ds, carrier, start_ns, end_ns)
                self._note_verbosity(signal, ax, ay_min)
                if ax is None or len(ax) == 0:
                    # No archive data in the window (maybe a lone live point
                    # arrives later): the signal is not verbose, so the
                    # refresh worker will never re-query the archive for it.
                    self._backfill_last_value(ds, signal, carrier, end_ns, callback)
                    continue
                n = self._inject_archive_chunk(
                    signal, carrier,
                    (ax, ay, ay_min, ay_max, xunit or '', yunit or ''), callback)
                if n:
                    logger.info(f"Archive backfill for {signal.name}: {n} points prepended")

    def _inject_archive_chunk(self, signal, carrier, chunk, callback):
        """Prepend an archive chunk to the carrier buffer, merging against any
        live samples already present. Returns the number of archive points."""
        cx, cy, c_min, c_max, xunit, yunit = chunk
        if c_min is not None and not getattr(signal, 'envelope', False):
            # An envelope reply to a raw request means UDA overflowed and
            # decimated — the same condition the Draw path flags.
            signal.isDownsampled = True
        is_env = getattr(signal, 'envelope', False)
        cx = np.asarray(cx)
        cy = np.asarray(cy)
        with self._signal_lock(carrier):
            cur_x, cur_y, cur_min, cur_max = self._current_arrays(carrier)
            m_min = m_max = None
            if len(cur_x) > 0:
                mx = np.concatenate([cx, cur_x])
                my = np.concatenate([cy, cur_y])
                if is_env:
                    m_min = np.concatenate([
                        np.asarray(c_min) if c_min is not None else cy,
                        cur_min if cur_min is not None else cur_y])
                    m_max = np.concatenate([
                        np.asarray(c_max) if c_max is not None else cy,
                        cur_max if cur_max is not None else cur_y])
                # Chunk first + stable sort + keep-last: on a timestamp
                # collision the buffered sample wins over an archive boundary
                # point.
                order = np.argsort(mx, kind='stable')
                keep = np.empty(len(order), dtype=bool)
                keep[-1] = True
                keep[:-1] = mx[order][1:] > mx[order][:-1]
                sel = order[keep]
                mx, my = mx[sel], my[sel]
                if is_env:
                    m_min, m_max = m_min[sel], m_max[sel]
            else:
                mx, my = cx, cy
                if is_env:
                    m_min = np.asarray(c_min) if c_min is not None else cy
                    m_max = np.asarray(c_max) if c_max is not None else cy
            payload = self._make_payload(
                carrier, mx, my, y_min=m_min, y_max=m_max,
                xunit=xunit, yunit=yunit,
            )
            carrier.inject_external(append=False, **payload)
            if self._apply_cap(carrier):
                signal.isDownsampled = True
            if self._has_window_hole(carrier):
                self._mark_refresh(signal)
            signal._streaming_has_live = True
            if carrier is not signal:
                # See handler(): keep the reprocess read inside the carrier's
                # lock so a concurrent live/topup write cannot interleave
                # mid-read and corrupt the derived signal.
                self._reprocess(signal)
        callback(signal)
        return len(cx)

    def _backfill_last_value(self, ds, signal, carrier, end_ns, callback):
        """No samples in the window: fall back to the last value recorded
        before it and hold it across the window as a constant line. The
        reply's timestamp is by construction older than the window (the
        query is unbounded at the start), so injecting it verbatim would
        stretch the X range back to whenever the signal last changed."""
        ax, ay, ay_min, ay_max, xunit, yunit = self._fetch_last_archive_value(
            ds, carrier, end_ns)
        if ax is None or len(ax) == 0:
            return
        if self._window_ns > 0:
            # Hold from the window's left edge up to whatever the caller read.
            # Deriving it from now (rather than from end_ns plus the
            # retention) keeps the span valid for both a wide window, whose
            # end sits a retention behind now, and a live-only one, whose end
            # is now.
            start_ns = int(time.time() * 1e9) - self._window_ns
            ax, ay, clamped = self._hold_stale_samples(
                ax, ay, start_ns, end_ns)
            if clamped:
                self._hold_semantics.add(signal.uid)
                logger.info(f"Holding last known value for {signal.name} "
                            f"across the window (no samples inside it)")
                # min/max bounds belong to the original sample; a held value
                # has no band of its own.
                if ay_min is not None:
                    ay_min = ay_max = None
        self._inject_archive_chunk(
            signal, carrier,
            (ax, ay, ay_min, ay_max, xunit or '', yunit or ''), callback)

    def _mark_refresh(self, signal):
        """Flag a signal for a full-window archive refresh. Cheap and
        thread-safe (single set.add); the refresh worker picks it up.
        A cap overflow proves the signal is verbose, so it also joins the
        periodic-refresh population."""
        self._refresh_pending.add(signal.uid)
        self._verbose.add(signal.uid)

    def _note_verbosity(self, signal, ax, ay_min):
        """Classify a signal from an archive reply. A signal is "verbose"
        when the window holds more samples than the point budget: the reply
        saturated the budget, or a raw request overflowed into a decimated
        (envelope) reply. Only verbose signals are worth periodic archive
        refreshes; a sparse signal (few points, or none at all with a lone
        live sample) gets its data from the one initial backfill and the
        live feed, and re-asking the archive for it would waste UDA and CPU
        for nothing. Verbosity is re-evaluated on every reply so a signal
        that quiets down leaves the refresh population."""
        budget = self._max_points
        if budget <= 0:
            return
        n = 0 if ax is None else len(ax)
        decimated = ay_min is not None and not getattr(signal, 'envelope', False)
        if n >= budget or decimated:
            self._verbose.add(signal.uid)
            # Densely sampled: plain interpolation between real samples.
            self._hold_semantics.discard(signal.uid)
        elif n < budget - budget // 10:
            self._verbose.discard(signal.uid)

    def _refresh_loop(self):
        """Refresh worker implementing the mint#78 point-5 contract: whenever
        a signal's buffer overflowed the cap, or on the periodic tick, re-ask
        the archive for the whole visible window in ONE call at the same
        point budget and keep the live span the archive does not yet cover.
        Only signals classified verbose (more samples in the window than the
        budget) are refreshed periodically: sparse signals never re-query
        the archive after the initial backfill. Per-signal refreshes are
        rate-limited so a fast signal cannot hammer UDA."""
        period_target = time.monotonic() + _TOPUP_PERIOD_S
        min_interval = _refresh_min_interval_s()
        while not self.stop_flag:
            time.sleep(1)
            if self.stop_flag:
                return
            periodic = time.monotonic() >= period_target
            if periodic:
                period_target = time.monotonic() + _TOPUP_PERIOD_S
            if not periodic and not self._refresh_pending:
                continue
            for ds, signals in self._ds_to_signals.items():
                for signal in signals:
                    if self.stop_flag:
                        return
                    uid = signal.uid
                    due_pending = uid in self._refresh_pending
                    due_periodic = periodic and uid in self._verbose
                    if not (due_pending or due_periodic):
                        continue
                    now = time.monotonic()
                    if now - self._last_refresh_any < _REFRESH_GLOBAL_SPACING_S:
                        # Stagger across signals: one archive round trip at a
                        # time, so a workspace-wide tick cannot flood the
                        # draw thread with reinjections.
                        break
                    if now - self._last_refresh.get(uid, 0.0) < min_interval:
                        # Stays pending; retried on a later pass. Applies to
                        # periodic refreshes too -- a signal refreshed for a
                        # hole a moment ago does not need the tick as well.
                        continue
                    self._refresh_pending.discard(uid)
                    self._last_refresh[uid] = now
                    self._last_refresh_any = now
                    self._refresh_signal(ds, signal)

    def _refresh_signal(self, ds: str, signal):
        """One archive call for the whole window ``[now - window,
        now - live_retention]`` at the point budget. The live buffer keeps
        every sample NEWER than the archive's actual last sample: the
        archiver nominally lags live by ~live_retention, but it can lag far
        more (processed/downsampled streams are written in blocks), and
        keeping only the theoretical newest-2-minutes span would silently
        discard everything between the archive's real end and that boundary
        — the newest chunks would vanish on every refresh. Anchoring the
        keep-boundary at the archive's own last timestamp loses nothing
        regardless of the actual lag. No NaN break is inserted here: the
        two blocks meet at that timestamp (unlike the first fill, where the
        archive genuinely ends behind the first live sample)."""
        if self._window_is_live_only():
            # Nothing archived inside the window; the query would invert.
            return
        carrier = self._carrier(signal)
        now_ns = int(time.time() * 1e9)
        boundary_ns = now_ns - _live_retention_s() * int(1e9)
        start_ns = now_ns - self._window_ns

        ax, ay, ay_min, ay_max, xunit, yunit = self._fetch_archive_range(
            ds, carrier, start_ns, boundary_ns)
        self._note_verbosity(signal, ax, ay_min)
        if ax is None or len(ax) == 0:
            return
        if ay_min is not None and not getattr(signal, 'envelope', False):
            signal.isDownsampled = True
        is_env = getattr(signal, 'envelope', False)

        new_x = np.asarray(ax)
        new_y = np.asarray(ay)
        # Live samples strictly after the archive's real end are kept; the
        # archive replaces everything it actually covers.
        keep_after_ns = int(new_x[-1])
        with self._signal_lock(carrier):
            cur_x, cur_y, cur_ymin, cur_ymax = self._current_arrays(carrier)
            keep_mask = (np.asarray(cur_x) > keep_after_ns) if len(cur_x) \
                else np.zeros(0, dtype=bool)
            kept_x = np.asarray(cur_x)[keep_mask]
            kept_y = np.asarray(cur_y)[keep_mask]

            # Disjoint by construction (archive <= keep_after < live tail),
            # so a plain concatenation is already chronological.
            mx = np.concatenate([new_x, kept_x])
            my = np.concatenate([new_y, kept_y])
            merged_ymin = merged_ymax = None
            if is_env:
                kept_ymin = (np.asarray(cur_ymin)[keep_mask]
                             if cur_ymin is not None else kept_y)
                kept_ymax = (np.asarray(cur_ymax)[keep_mask]
                             if cur_ymax is not None else kept_y)
                new_ymin = np.asarray(ay_min) if ay_min is not None else new_y
                new_ymax = np.asarray(ay_max) if ay_max is not None else new_y
                merged_ymin = np.concatenate([new_ymin, kept_ymin])
                merged_ymax = np.concatenate([new_ymax, kept_ymax])

            payload = self._make_payload(
                carrier, mx, my,
                y_min=merged_ymin, y_max=merged_ymax,
                xunit=xunit, yunit=yunit,
            )
            carrier.inject_external(append=False, **payload)
            # No cap trim here: the refresh result IS the cap (10k archive
            # points + the newest live span, per the point-5 contract).
            signal._streaming_has_live = True
            if carrier is not signal:
                # See handler(): keep the reprocess read inside the carrier's
                # lock so a concurrent live write cannot interleave mid-read
                # and corrupt the derived signal.
                self._reprocess(signal)

        logger.info(f"Window refresh for {signal.name}: {len(ax)} archive "
                    f"points, {len(kept_x)} live points retained")
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
        self._refresh_pending.clear()
        self._last_refresh.clear()
        self._verbose.clear()
        self._hold_semantics.clear()
        self._last_refresh_any = 0.0
