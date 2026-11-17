"""
Data access requests run in worker threads.

Each worker thread reads through a data access object of its own, as data access clients are not
safe to share between threads. A request leaves the GUI thread free for as long as its client
releases the GIL while it waits, and independent requests run at the same time.
"""

import inspect
import queue
import threading
from collections import OrderedDict, defaultdict
from concurrent.futures import CancelledError, Executor, Future, InvalidStateError, wait
from functools import partial
from typing import Callable, Dict, Iterable, Optional

from PySide6.QtCore import QCoreApplication, QEventLoop, QObject, QThread, Qt, Signal, Slot

from iplotDataAccess.dataSource import DS_CODAC_TYPE
from iplotLogging import setupLogger
from iplotlib.interface.iplotSignalAdapter import AccessHelper, DataAccessError

logger = setupLogger.get_logger(__name__)

#: Data source types whose requests may run in several worker threads at once. Requests to other
#: sources share a single worker: the IMAS client must not be called from two threads at once.
PARALLEL_SOURCE_TYPES = frozenset({DS_CODAC_TYPE})

# Worker slot of the data sources whose requests share a single worker.
_SERIAL_SLOT = -1

# Requests whose worker is remembered: far more than the data access caches hold.
_REMEMBERED_REQUESTS = 4096

# A request read before goes back to its worker unless that worker has this many more requests to read than the
# least loaded one.
_AFFINITY_MAX_EXCESS = 2

_STOPPED = "The data access stopped while reading the data"

# State of a worker thread: what sets its data access up, the data source types it reads (all if None), the data
# sources it leaves unconnected, the number of workers that share the caches of their data sources, the cache
# generation it last cleared its data access cache for, and the data sources it tried to connect to again. Its data
# access object is AccessHelper's for this thread (see AccessHelper.thread_data_access).
_worker = threading.local()


def app_data_access():
    """Data access configured as the application's, from the data sources file DataAccess finds: with the data
    sources of the types this worker reads only, and none of those the application could not connect to, as far as
    iplotDataAccess can leave them out."""
    from iplotDataAccess.dataAccess import DataAccess
    accepted = inspect.signature(DataAccess).parameters
    asked = dict(source_types=_worker.source_types, leave_unconnected=_worker.leave_unconnected)
    # Not AppDataAccess, whose single data access object is the application's.
    data_access = DataAccess(**{name: value for name, value in asked.items() if name in accepted})
    configured = data_access.load_config()
    # A worker of no type serves only requests to data sources the application does not have, and so does a worker
    # whose data sources the application could not connect to.
    if not configured and _worker.source_types != frozenset() and not getattr(data_access, 'unconnected', None):
        logger.error("No data sources found for the data access worker")
    return data_access


def _start_worker(data_access_factory, source_types, cache_share, leave_unconnected):
    """Set up the data access of a worker thread; raise if it cannot read."""
    _worker.data_access_factory = data_access_factory
    _worker.source_types = source_types
    _worker.cache_share = cache_share
    _worker.leave_unconnected = leave_unconnected
    _worker.cache_epoch = 0
    _worker.reconnected = set()
    _set_up_data_access()
    if AccessHelper.thread_data_access() is None:
        raise DataAccessError("Data access could not be set up in the worker thread, see the log")


def _set_up_data_access():
    # Logged, as the worker reports it when it is asked to read. A worker that fails to set it up again keeps reading
    # with the data access object it has.
    try:
        data_access = _worker.data_access_factory()
        _share_cache(data_access, _worker.cache_share)
    except Exception:
        logger.exception("Cannot set up data access in the worker thread")
    else:
        AccessHelper.set_thread_data_access(data_access)


def _share_cache(data_access, workers: int):
    """Keep in this worker its share of the query cache of each data source: the other workers that read the same
    data sources keep the rest, so that together they keep as many queries as one data access object would."""
    if workers <= 1:
        return
    for data_source in (getattr(data_access, 'ds_list', None) or {}).values():
        cache = getattr(data_source, 'access_cache', None)
        maxsize = getattr(cache, 'maxsize', None)
        # A data source kept when the worker sets up data access again (see _data_access) has its share.
        if maxsize and not getattr(data_source, '_shared_cache', False):
            data_source.access_cache = type(cache)(maxsize=max(1, int(maxsize) // workers))
            data_source._shared_cache = True


def _data_access(name: Optional[str], cache_epoch: int):
    """The data access object of this worker, for a request to the data source `name`: set up once more the first
    time a request names a data source it could not connect to, and with its cache cleared if the application
    cleared the caches since the last request (see AccessPool.clear_cache)."""
    data_access = AccessHelper.thread_data_access()
    if data_access is None:
        raise DataAccessError("Data access could not be set up in the worker thread, see the log")
    connected = getattr(data_access, 'get_connected_data_source_names', None)
    if (name is not None and connected is not None and name not in connected() and name not in _worker.reconnected
            and name not in _worker.leave_unconnected):
        # The application connected to it, but this worker could not when it started.
        _worker.reconnected.add(name)
        logger.warning(f"The data access thread connects again to the data sources: {name} was not connected")
        _set_up_data_access()
        data_access = AccessHelper.thread_data_access()
        if data_access is None:
            raise DataAccessError("Data access could not be set up in the worker thread, see the log")
    if cache_epoch != _worker.cache_epoch:
        _worker.cache_epoch = cache_epoch
        try:
            data_access.clear_cache()
        except Exception:
            logger.exception("Cannot clear the data access cache of the worker thread")
    return data_access


def _failure(error: BaseException, varname) -> DataAccessError:
    """The error raised reading `varname`, as the application reports it. Call it while handling the error."""
    logger.debug(f"Error reading {varname}", exc_info=True)
    # AccessHelper._submit_fetch() reports only the message.
    return DataAccessError(str(error) if isinstance(error, Exception) else repr(error))


def _read(params: dict, cache_epoch: int) -> dict:
    _data_access(params.get('data_s_name'), cache_epoch)
    try:
        return AccessHelper._request_data(**params)
    except DataAccessError:
        raise
    except BaseException as e:
        raise _failure(e, params.get('varname')) from None


def _call(method, name: str, kwargs: dict, cache_epoch: int, progress: Optional[Callable] = None):
    """`method` of the data access object, or a function given that object, called for the data source `name` (see
    AccessPool.call); a function is also given ``progress=``, if given, to report its progress with."""
    data_access = _data_access(name, cache_epoch)
    sources = getattr(data_access, 'ds_list', None)
    if sources is not None and name not in sources:
        # The data access object would answer for its default data source instead.
        raise DataAccessError(f"The data access thread has no data source {name}")
    try:
        with AccessHelper.reading(name):
            if not callable(method):
                return getattr(data_access, method)(name, **kwargs)
            if progress is not None:
                kwargs = dict(kwargs, progress=progress)
            return method(data_access, name, **kwargs)
    except DataAccessError:
        raise
    except BaseException as e:
        raise _failure(e, kwargs.get('varname')) from None


def _outcome(future: Future):
    """The future's result, or the exception it raised."""
    try:
        return future.result()
    except Exception as e:
        return e


class _WorkerThread(Executor):
    """Makes the calls given to it one after the other, in a thread of its own that sets itself up first.

    The thread is a daemon: unlike those of a ThreadPoolExecutor, the application does not wait for the call in
    progress when it exits, which a data access client may not end.
    """

    def __init__(self, name: str, set_up: Callable[[], None]):
        self._calls = queue.SimpleQueue()
        self._lock = threading.Lock()
        self._closed = False
        # Set by a shutdown that cancels the calls not started, the one a worker took and did not start yet too.
        self._cancelling = False
        self._running = None  # type: Optional[Future]
        #: Done once the thread is set up, with the error that kept it from it.
        self.ready = Future()
        threading.Thread(target=self._work, args=(set_up,), name=name, daemon=True).start()

    def submit(self, fn, /, *args, **kwargs) -> Future:
        with self._lock:
            if self._closed:
                raise RuntimeError("The data access pool is shut down")
            future = Future()
            self._calls.put((future, fn, args, kwargs))
        return future

    def shutdown(self, wait: bool = True, *, cancel_futures: bool = False):
        """Make no more calls. `cancel_futures` cancels those not started, and ends the one in progress for those who
        wait for it: its result, if it ever comes, is dropped. `wait` is not supported: nothing waits for the thread."""
        with self._lock:
            self._closed = True
            if cancel_futures:
                self._cancelling = True
                while True:
                    try:
                        call = self._calls.get_nowait()
                    except queue.Empty:
                        break
                    if call is not None:
                        _cancel(call[0])
                if self._running is not None:
                    _settle(self._running, exception=DataAccessError(_STOPPED))
            self._calls.put(None)

    def _work(self, set_up: Callable[[], None]):
        try:
            set_up()
        except BaseException as error:
            self.ready.set_exception(error)
        else:
            self.ready.set_result(None)
        while True:
            call = self._calls.get()
            if call is None:
                return
            self._make(*call)
            # Nor its arguments, its result or its future, which this thread no longer keeps.
            del call

    def _make(self, future: Future, fn: Callable, args: tuple, kwargs: dict):
        with self._lock:
            if self._cancelling:
                _cancel(future)
                return
            if not future.set_running_or_notify_cancel():
                return
            self._running = future
        try:
            result = fn(*args, **kwargs)
        except BaseException as error:
            _settle(future, exception=error)
        else:
            _settle(future, result=result)
        finally:
            with self._lock:
                self._running = None


def _cancel(future: Future):
    """Cancel the future of a call not started, notifying who waits for it: wait() counts it as done, as it does once
    a worker skips it."""
    future.cancel()
    future.set_running_or_notify_cancel()


def _settle(future: Future, result=None, exception: BaseException = None):
    """Set the future's outcome, unless a shutdown has already ended it."""
    try:
        if exception is not None:
            future.set_exception(exception)
        else:
            future.set_result(result)
    except InvalidStateError:
        pass


class _Relay(QObject):
    """Calls in its thread, the GUI thread, from its event loop, the functions posted to it from any thread."""
    posted = Signal(object)

    def __init__(self):
        super().__init__()
        # Queued also for what its own thread posts: a function posted never runs within the poster's call.
        self.posted.connect(self._call, Qt.ConnectionType.QueuedConnection)

    @Slot(object)
    def _call(self, function: Callable[[], None]):
        function()


# Never destroyed: a Qt object can only be destroyed in its own thread, and a worker thread may let go last of what
# refers to it (see _Watch).
_relay = None  # type: Optional[_Relay]


def _gui_relay() -> _Relay:
    """The relay, made on first use in the GUI thread, where the futures are watched from."""
    global _relay
    if _relay is None:
        _relay = _Relay()
    return _relay


class _Watch:
    """Calls `check` in the GUI thread, from its event loop, whenever a future it watches is done, until released:
    the futures complete in the worker threads. The futures keep this object in their callbacks and a worker thread
    may let go of them last, so it holds no Qt object but the relay, and nothing of `check` once released."""

    def __init__(self, futures: Iterable[Future], check: Callable[[], None]):
        self._check = check
        self._relay = _gui_relay()
        futures = list(futures)
        for future in futures:
            future.add_done_callback(self._arrived)
        if not futures:
            self._arrived(None)

    def release(self):
        self._check = None

    def _arrived(self, _future: Optional[Future]):
        self._relay.posted.emit(self._on_arrival)

    def _on_arrival(self):
        if self._check is not None:
            self._check()


class PendingFetch:
    """Requests that AccessPool.fetch_later() runs in the worker threads."""

    def __init__(self, pool: 'AccessPool', futures: Dict[tuple, Future],
                 on_done: Callable[[Dict[tuple, object]], None], on_stopped: Optional[Callable[[], None]] = None,
                 progress: Optional[Callable[[int, int], None]] = None):
        self._pool = pool
        self._futures = futures
        self._on_done = on_done
        self._on_stopped = on_stopped
        self._progress = progress
        self._watch = _Watch(futures.values(), self._check)
        self._tell()

    def cancel(self):
        """Call neither on_done nor on_stopped, and leave unread the requests no worker started yet."""
        for future in self._futures.values():
            future.cancel()
        self._release()

    def _release(self):
        # The futures keep this object in their callbacks: it must not keep the data read with it.
        self._futures, self._on_done, self._on_stopped, self._progress = {}, None, None, None
        self._watch.release()

    def _tell(self):
        if self._progress is not None and self._futures:
            try:
                self._progress(sum(future.done() for future in self._futures.values()), len(self._futures))
            except Exception:
                logger.exception("Cannot tell how many of the data read in the background are there")

    def _check(self):
        if self._on_done is None:
            return
        # What it tells may cancel the read.
        self._tell()
        if self._on_done is None or not all(future.done() for future in self._futures.values()):
            return
        futures, on_done, on_stopped = self._futures, self._on_done, self._on_stopped
        self._release()
        try:
            if not self._pool.closed:
                on_done({key: _outcome(future) for key, future in futures.items()})
            elif on_stopped is not None:
                on_stopped()
        except Exception:
            logger.exception("Cannot draw the data read in the background")


class PendingCall:
    """A call that AccessPool.call_later() makes in a worker thread."""

    def __init__(self, on_done: Callable[[object], None], progress: Optional[Callable] = None):
        self._future = None  # type: Optional[Future]
        self._on_done = on_done
        self._progress = progress
        self._relay = _gui_relay()
        self._watch = None  # type: Optional[_Watch]

    def _reporter(self) -> Callable:
        """What the call is given to report its progress with, from its worker: what it reports goes through the
        relay that then tells this thread the call ended, so it arrives first."""
        return lambda *args: self._relay.posted.emit(partial(self._report, args))

    def _watch_future(self, future: Future):
        self._future = future
        self._watch = _Watch([future], self._check)

    def cancel(self):
        """Call neither on_done nor progress, and leave the call unmade if no worker started it yet: one started runs
        to its end, as a thread cannot be stopped."""
        if self._future is not None:
            self._future.cancel()
        self._release()

    def _release(self):
        # The future keeps this object in its callbacks: it must not keep the result with it.
        self._future, self._on_done, self._progress = None, None, None
        if self._watch is not None:
            self._watch.release()

    def _report(self, args: tuple):
        if self._progress is None:
            return
        try:
            self._progress(*args)
        except Exception:
            logger.exception("Cannot report the progress of a call made in the background")

    def _check(self):
        if self._on_done is None or not self._future.done():
            return
        future, on_done = self._future, self._on_done
        self._release()
        result = _outcome(future)
        if isinstance(result, CancelledError):
            # Left unmade by a shutdown.
            result = DataAccessError(_STOPPED)
        try:
            on_done(result)
        except Exception:
            logger.exception("Cannot take the result of a call made in the background")


class AccessPool:
    """Runs AccessHelper data access requests in worker threads.

    Requests to a data source of PARALLEL_SOURCE_TYPES run in up to `workers` threads at once;
    requests to other data sources share a single worker. A worker starts with the first request
    to its data sources, or ahead of it with prepare(). Each worker reads through a data access
    object of its own, made by `data_access_factory` (by default, one that sets up only the data
    sources of the types the worker reads), and logs through the loggers of the application.

    A request read before goes back to the worker that read it, whose data access cache may
    still hold the data; new requests go to the worker with the fewest requests to read.
    call() runs other methods of the data access object, or functions given it, from any thread;
    call_later() runs them without waiting for them, for those that take long.
    """

    def __init__(self, workers: int, data_access_factory: Callable = app_data_access):
        self._workers = max(1, workers)
        self._data_access_factory = data_access_factory
        # Guards the workers and their bookkeeping below, which call() also uses from other threads.
        self._lock = threading.RLock()
        self._executors = {}  # type: Dict[int, _WorkerThread] # key: worker slot
        # Requests given to each worker that it has not finished reading, by worker slot. They have a lock of their
        # own, as they are counted down from the worker threads.
        self._loads = defaultdict(int)
        self._loads_lock = threading.Lock()
        self._slots = OrderedDict()  # type: OrderedDict[tuple, int] # key: request key, last used last
        self._cache_epoch = 0
        # Counts the new requests, which the workers with the fewest requests to read take in turns.
        self._turn = 0
        self._closed = False

    @property
    def closed(self) -> bool:
        """Whether the pool is shut down."""
        return self._closed

    def prepare(self, data_source_names: Iterable[str]):
        """Start, ahead of their first request, the workers that requests to these data sources need: every
        worker of the parallel sources, or the single one of the others. Names of no configured data source
        are left out, and so are the workers already started."""
        if isinstance(data_source_names, str):
            data_source_names = (data_source_names,)
        configured = getattr(AccessHelper.da, 'ds_list', None) or {}
        slots = set()
        for name in data_source_names:
            if name in configured:
                slots.update(self._slots_of(name))
        with self._lock:
            if self._closed:
                return
            for slot in sorted(slots):
                self._executor(slot)

    def fetch(self, requests: Iterable[dict], progress: Callable[[int, int], None] = None) \
            -> Optional[Dict[tuple, object]]:
        """Run data access requests in the worker threads and wait for them.

        Returns, by AccessHelper.request_key(), the result of each request or the exception it
        raised; identical requests run once. While waiting, the GUI keeps painting and running
        its timers, and user input waits for the requests to finish. `progress` is called with
        the number of finished requests and their total. Returns None if the wait is
        interrupted, e.g. because the application quits. Raises RuntimeError if the worker
        threads cannot read.
        """
        self._check_workers()
        unique = self._unique(requests)
        futures = {key: self._submit(key, params) for key, params in unique.items()}
        if not self._wait(list(futures.values()), len(unique), progress):
            return None
        # A worker still setting up its data access when the requests were given to it may have failed to since.
        self._check_workers()
        return {key: _outcome(future) for key, future in futures.items()}

    def fetch_later(self, requests: Iterable[dict], on_done: Callable[[Dict[tuple, object]], None],
                    on_stopped: Optional[Callable[[], None]] = None,
                    progress: Optional[Callable[[int, int], None]] = None) -> PendingFetch:
        """Run data access requests in the worker threads without waiting for them.

        Once all are read, `on_done` is called in this thread, from its Qt event loop, with
        their results as fetch() returns them; never once the pool is shut down, which calls
        `on_stopped` instead, if given, for the caller to read them on its own. `progress`, if
        given, is called in this thread with the number of finished requests and their total,
        as fetch() calls it: at once, and then as each finishes. Raises RuntimeError if the
        worker threads cannot read.
        """
        self._check_workers()
        unique = self._unique(requests)
        return PendingFetch(self, {key: self._submit(key, params) for key, params in unique.items()}, on_done,
                            on_stopped, progress)

    def call(self, method, data_s_name: str, **kwargs):
        """Call a method of the data access object in a worker thread and wait for its result:
        ``call('get_archive_window', 'codacuda', varname=...)`` returns what
        ``get_archive_window('codacuda', varname=...)`` returns. `method` can also be a function,
        called with the data access object of the worker: ``method(data_access, data_s_name,
        **kwargs)``.

        A thread that does not run Qt waits without holding the GIL; the thread that runs Qt waits as
        fetch() does. Raises DataAccessError if the method fails, the worker has no such data source
        or the pool shuts down meanwhile, and RuntimeError if the worker threads cannot read or the
        pool is shut down.
        """
        self._check_workers()
        with self._lock:
            future = self._run(self._free_slot(data_s_name), _call, method, data_s_name, kwargs, self._cache_epoch)
        if not self._wait([future], 1, None):
            raise DataAccessError(_STOPPED if self._closed else "The wait for the data access thread was interrupted")
        result = _outcome(future)
        if isinstance(result, CancelledError):
            raise DataAccessError(_STOPPED) from result
        if isinstance(result, Exception):
            raise result
        return result

    def call_later(self, method, data_s_name: str, on_done: Callable[[object], None],
                   progress: Optional[Callable] = None, **kwargs) -> PendingCall:
        """Make in a worker thread the call that call() makes, without waiting for it: for one that
        takes long, such as an export.

        Once made, `on_done` is called in this thread, from its Qt event loop, with its result or
        the DataAccessError it raised, which a shutdown that leaves it unmade raises too. With
        `progress`, a function given as `method` is also given ``progress=``, a callable whose
        arguments are given to `progress` in this thread, in the order reported and before the
        result. Raises RuntimeError if the worker threads cannot read or the pool is shut down.
        """
        self._check_workers()
        pending = PendingCall(on_done, progress)
        with self._lock:
            future = self._run(self._free_slot(data_s_name), _call, method, data_s_name, kwargs, self._cache_epoch,
                               pending._reporter() if progress is not None else None)
        pending._watch_future(future)
        return pending

    def clear_cache(self):
        """Make every worker clear its data access cache before its next request."""
        with self._lock:
            self._cache_epoch += 1
            # No worker holds the data of a request any more.
            self._slots.clear()

    def shutdown(self):
        """Stop the workers without waiting for the requests they are reading."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            executors = [self._executors.pop(slot) for slot in list(self._executors)]
        for executor in executors:
            executor.shutdown(wait=False, cancel_futures=True)

    def _check_workers(self):
        """Raise RuntimeError if a worker thread could not set up its data access."""
        with self._lock:
            if self._closed:
                # Requests to a pool shut down fail on their own.
                return
            readies = [executor.ready for executor in self._executors.values()]
        for ready in readies:
            error = ready.exception() if ready.done() else None
            if error is not None:
                raise RuntimeError(f"The data access threads cannot read: {error}") from error

    @staticmethod
    def _unique(requests: Iterable[dict]) -> Dict[tuple, dict]:
        unique = {}
        for params in requests:
            unique.setdefault(AccessHelper.request_key(params), params)
        return unique

    def _submit(self, key: tuple, params: dict) -> Future:
        with self._lock:
            return self._run(self._slot(key, params), _read, params, self._cache_epoch)

    def _run(self, slot: int, function: Callable, *args) -> Future:
        with self._lock:
            future = self._executor(slot).submit(function, *args)
            with self._loads_lock:
                self._loads[slot] += 1
        future.add_done_callback(partial(self._finished, slot))
        return future

    def _finished(self, slot: int, _future: Future):
        # Called from the worker thread, which must not wait for self._lock: _run() may hold it while it waits for
        # nothing else, but call() holds it from other threads too.
        with self._loads_lock:
            self._loads[slot] -= 1

    def _slot(self, key: tuple, params: dict) -> int:
        least_loaded = self._free_slot(params.get('data_s_name'))
        if least_loaded == _SERIAL_SLOT:
            return least_loaded
        slot = self._slots.pop(key, None)
        if slot is None or self._loads[slot] - self._loads[least_loaded] >= _AFFINITY_MAX_EXCESS:
            slot = least_loaded
        self._slots[key] = slot
        if len(self._slots) > _REMEMBERED_REQUESTS:
            self._slots.popitem(last=False)
        return slot

    def _free_slot(self, data_s_name: Optional[str]) -> int:
        """The worker slot for a new request to the data source: the one of its workers with the fewest requests to
        read. Workers with as few take turns, so that requests read one at a time fill the caches of them all."""
        slots = self._slots_of(data_s_name)
        if slots == (_SERIAL_SLOT,):
            return _SERIAL_SLOT
        self._turn += 1
        first = self._turn % len(slots)
        return min(slots[first:] + slots[:first], key=lambda candidate: self._loads[candidate])

    def _slots_of(self, data_s_name: Optional[str]) -> tuple:
        """The worker slots of the requests to the data source: those of the parallel workers, or the single one."""
        return tuple(range(self._workers)) if self._is_parallel(data_s_name) else (_SERIAL_SLOT,)

    def _executor(self, slot: int) -> _WorkerThread:
        if self._closed:
            raise RuntimeError("The data access pool is shut down")
        executor = self._executors.get(slot)
        if executor is None:
            parallel = slot != _SERIAL_SLOT
            executor = _WorkerThread(
                f"data access {'serial' if not parallel else slot}",
                partial(_start_worker, self._data_access_factory,
                        PARALLEL_SOURCE_TYPES if parallel else self._serial_source_types(),
                        self._workers if parallel else 1, self._unconnected()))
            self._executors[slot] = executor
        return executor

    @staticmethod
    def _serial_source_types() -> Optional[frozenset]:
        """The types of the configured data sources whose requests share the single worker: none if they are
        all parallel, when it reads only requests to data sources the application does not have; every type
        (None) if the data access object lists no data sources."""
        data_sources = getattr(AccessHelper.da, 'ds_list', None)
        if data_sources is None:
            return None
        types = {getattr(ds, 'source_type', None) for ds in data_sources.values()} - set(PARALLEL_SOURCE_TYPES)
        types.discard(None)
        return frozenset(types)

    @staticmethod
    def _unconnected() -> frozenset:
        """The data sources the application could not connect to, which the workers leave unconnected: a
        worker would take as long to fail, over a minute at times, before it could read anything."""
        return frozenset(getattr(AccessHelper.da, 'unconnected', None) or ())

    @staticmethod
    def _is_parallel(data_s_name: Optional[str]) -> bool:
        get_data_source = getattr(AccessHelper.da, 'get_data_source', None)
        data_source = get_data_source(data_s_name) if get_data_source is not None else None
        return getattr(data_source, 'source_type', None) in PARALLEL_SOURCE_TYPES

    def _wait(self, futures: list, total: int, progress: Optional[Callable[[int, int], None]]) -> bool:
        """Wait for the futures, reporting those done out of `total`. False if interrupted."""
        app = QCoreApplication.instance()
        if app is None or QThread.currentThread() != app.thread():
            # A shutdown ends the futures still waited for (see _WorkerThread.shutdown). wait() would not count one
            # cancelled and not yet skipped by its worker.
            wait([future for future in futures if not future.done()])
            if progress is not None:
                progress(len(futures), total)
            return not self._closed
        loop = QEventLoop()

        def check():
            done = sum(future.done() for future in futures)
            # Before the progress report, which may fail, so that the wait ends anyway.
            if done == len(futures):
                loop.quit()
            if progress is not None:
                progress(done, total)

        watch = _Watch(futures, check)
        check()
        if not all(future.done() for future in futures):
            loop.exec(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)
        watch.release()
        return all(future.done() for future in futures) and not self._closed


AccessHelper.reads_in_parallel = staticmethod(AccessPool._is_parallel)
