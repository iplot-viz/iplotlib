"""
Data access requests run in worker processes.

A data access client can keep the GIL for the whole of a blocking request, so a request
made from a worker thread still stalls the GUI thread. Worker processes leave the GUI
thread free and let independent requests run at the same time.
"""

import faulthandler
import inspect
import logging
import logging.handlers
import multiprocessing
import multiprocessing.connection
import os
import queue
import signal
import threading
import time
from collections import OrderedDict, defaultdict
from concurrent.futures import CancelledError, Future, ProcessPoolExecutor, wait
from concurrent.futures.process import BrokenProcessPool
from functools import partial
from typing import Callable, Dict, Iterable, Optional

from PySide6.QtCore import QCoreApplication, QEventLoop, QThread, QTimer

from iplotDataAccess.dataSource import DS_CODAC_TYPE
from iplotLogging import setupLogger
from iplotlib.interface.iplotSignalAdapter import AccessHelper, DataAccessError

logger = setupLogger.get_logger(__name__)

#: Data source types whose requests may run in several worker processes at once. Requests to
#: other sources share a single worker: an IMAS HDF5 entry cannot be opened by two processes.
PARALLEL_SOURCE_TYPES = frozenset({DS_CODAC_TYPE})

_POLL_INTERVAL_MS = 50

# Worker slot of the data sources whose requests share a single worker.
_SERIAL_SLOT = -1

# Requests whose worker is remembered: far more than the data access caches hold.
_REMEMBERED_REQUESTS = 4096

# A request read before goes back to its worker unless that worker has this many more requests to read than the
# least loaded one.
_AFFINITY_MAX_EXCESS = 2

# Seconds a worker may be stopped before its executor counts as waiting for the rest of a result.
_STUCK_AFTER_S = 2.0

_STOPPED = "The data access process stopped while reading the data"

# State of a worker process: what sets its data access up, the data source types it reads (all if
# None), the data sources it leaves unconnected, the number of workers that share the caches of their
# data sources, the cache generation it last cleared its data access cache for, and the data sources it
# tried to connect to again.
_worker_data_access_factory = None
_worker_source_types = None
_worker_leave_unconnected = frozenset()
_worker_cache_share = 1
_worker_cache_epoch = 0
_worker_reconnected = set()


def app_data_access():
    """Data access configured as the application's, from the data sources file AppDataAccess finds: with
    the data sources of the types this worker reads only, and none of those the application could not
    connect to, as far as iplotDataAccess can leave them out."""
    from iplotDataAccess.appDataAccess import AppDataAccess
    accepted = inspect.signature(AppDataAccess.initialize).parameters
    asked = dict(source_types=_worker_source_types, leave_unconnected=_worker_leave_unconnected)
    configured = AppDataAccess.initialize(**{name: value for name, value in asked.items() if name in accepted})
    data_access = AppDataAccess.get_data_access()
    # A worker of no type serves only requests to data sources the application does not have, and so does
    # a worker whose data sources the application could not connect to.
    if not configured and _worker_source_types != frozenset() and not getattr(data_access, 'unconnected', None):
        logger.error("No data sources found for the data access worker")
    return data_access


def _init_worker(log_queue, parent_log_file, data_access_factory, num_samples, num_samples_override,
                 source_types, cache_share, leave_unconnected):
    global _worker_data_access_factory, _worker_source_types, _worker_cache_share, _worker_leave_unconnected
    # Ctrl+C is the application's to handle, and a worker stops when the application does.
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    threading.Thread(target=_watch_parent, daemon=True).start()
    # A crash of a compiled data access client leaves its Python traceback on stderr.
    faulthandler.enable()
    _forward_logging(log_queue, parent_log_file)
    AccessHelper.num_samples = num_samples
    AccessHelper.num_samples_override = num_samples_override
    _worker_data_access_factory = data_access_factory
    _worker_source_types = source_types
    _worker_cache_share = cache_share
    _worker_leave_unconnected = leave_unconnected
    _set_up_data_access()
    # The modules imported to set up data access made loggers of their own.
    _drop_log_handlers()


def _watch_parent():
    # A worker left behind by an application that was killed would keep its connections open.
    multiprocessing.connection.wait([multiprocessing.parent_process().sentinel])
    os._exit(0)


def _set_up_data_access():
    # A failure here would stop the worker with no reason given: it is logged instead, and the
    # worker reports it when asked whether it can read (see _ready).
    try:
        AccessHelper.da = _worker_data_access_factory()
        _share_cache(AccessHelper.da, _worker_cache_share)
    except Exception:
        logger.exception("Cannot set up data access in the worker process")


def _share_cache(data_access, workers: int):
    """Keep in this worker its share of the query cache of each data source: the other workers that read
    the same data sources keep the rest, so that together they keep as many queries as one process would."""
    if workers <= 1:
        return
    for data_source in (getattr(data_access, 'ds_list', None) or {}).values():
        cache = getattr(data_source, 'access_cache', None)
        maxsize = getattr(cache, 'maxsize', None)
        # A data source kept when the worker sets up data access again (see _data_access) has its share.
        if maxsize and not getattr(data_source, '_shared_cache', False):
            data_source.access_cache = type(cache)(maxsize=max(1, int(maxsize) // workers))
            data_source._shared_cache = True


def _forward_logging(log_queue, parent_log_file):
    """Send this worker's log records to the parent process, which logs them as its own."""
    own_file = setupLogger.FileHandlerIplot.fhandler
    # setupLogger gives the loggers made from now on this handler instead of the file, which is closed below.
    setupLogger.FileHandlerIplot.fhandler = logging.NullHandler()
    _drop_log_handlers()
    logging.getLogger().addHandler(logging.handlers.QueueHandler(log_queue))
    logging.captureWarnings(True)
    own_file.close()
    own_path = getattr(own_file, 'baseFilename', None)
    if own_path and own_path != parent_log_file:
        try:
            if os.path.getsize(own_path) == 0:
                os.remove(own_path)
        except OSError:
            pass  # The empty file is only clutter.


def _drop_log_handlers():
    # Records go up to the root logger, whose handler sends them to the parent process.
    for existing in list(logging.Logger.manager.loggerDict.values()):
        if isinstance(existing, logging.Logger):
            for handler in list(existing.handlers):
                existing.removeHandler(handler)


def _log_as_own(record: logging.LogRecord):
    """Log a record of a worker process through the logger of the same name of this process."""
    logging.getLogger(record.name).handle(record)


class _AsOwnRecord(logging.Handler):
    def emit(self, record):
        _log_as_own(record)


def _data_access(name: Optional[str], cache_epoch: int):
    """The data access object of this worker, for a request to the data source `name`: set up once more the
    first time a request names a data source it could not connect to, and with its cache cleared if the
    application cleared the caches since the last request (see AccessPool.clear_cache)."""
    global _worker_cache_epoch
    if AccessHelper.da is None:
        raise DataAccessError("Data access could not be set up in the worker process, see the log")
    connected = getattr(AccessHelper.da, 'get_connected_data_source_names', None)
    if (name is not None and connected is not None and name not in connected() and name not in _worker_reconnected
            and name not in _worker_leave_unconnected):
        # The application connected to it, but this process could not when it started.
        _worker_reconnected.add(name)
        logger.warning(f"The data access process connects again to the data sources: {name} was not connected")
        _set_up_data_access()
    if cache_epoch != _worker_cache_epoch:
        _worker_cache_epoch = cache_epoch
        try:
            AccessHelper.da.clear_cache()
        except Exception:
            logger.exception("Cannot clear the data access cache of the worker process")
    return AccessHelper.da


def _picklable(error: BaseException, varname) -> DataAccessError:
    """The error raised reading `varname`, as it can reach the application. Call it while handling the error."""
    logger.debug(f"Error reading {varname}", exc_info=True)
    # Errors reach the application pickled, which not every exception survives. Their message
    # is all that AccessHelper._submit_fetch() reports.
    return DataAccessError(str(error) if isinstance(error, Exception) else repr(error))


def _read(params: dict, cache_epoch: int) -> dict:
    _data_access(params.get('data_s_name'), cache_epoch)
    try:
        return AccessHelper._request_data(**params)
    except DataAccessError:
        raise
    except BaseException as e:
        raise _picklable(e, params.get('varname')) from None


def _call(method: str, name: str, kwargs: dict, cache_epoch: int):
    """`method` of the data access object, called for the data source `name` (see AccessPool.call)."""
    data_access = _data_access(name, cache_epoch)
    sources = getattr(data_access, 'ds_list', None)
    if sources is not None and name not in sources:
        # The data access object would answer for its default data source instead.
        raise DataAccessError(f"The data access process has no data source {name}")
    try:
        return getattr(data_access, method)(name, **kwargs)
    except DataAccessError:
        raise
    except BaseException as e:
        raise _picklable(e, kwargs.get('varname')) from None


def _ready() -> int:
    """The worker process's id, once it can read data."""
    if AccessHelper.da is None:
        raise DataAccessError("Data access could not be set up in the worker process, see the log")
    return os.getpid()


def _outcome(future: Future):
    """The future's result, or the exception it raised."""
    try:
        return future.result()
    except Exception as e:
        return e


class PendingFetch:
    """Requests that AccessPool.fetch_later() runs in the worker processes."""

    def __init__(self, pool: 'AccessPool', futures: Dict[tuple, Future],
                 on_done: Callable[[Dict[tuple, object]], None]):
        self._pool = pool
        self._futures = futures
        self._on_done = on_done
        # Polled from this thread, which on_done then runs in: the futures complete in another one.
        self._timer = QTimer()
        self._timer.timeout.connect(self._check)
        self._timer.start(_POLL_INTERVAL_MS)

    def cancel(self):
        """Do not call on_done, and leave unread the requests no worker started yet."""
        self._timer.stop()
        for future in self._futures.values():
            future.cancel()
        self._release()

    def _release(self):
        # Some PySide6 releases keep the slot of the timer connection, with this object, for a while:
        # it must not keep the data read with it.
        self._futures, self._on_done = {}, None

    def _check(self):
        if self._on_done is None:
            return
        if not all(future.done() for future in self._futures.values()):
            self._pool._release_stuck_executors()
            return
        self._timer.stop()
        futures, on_done = self._futures, self._on_done
        self._release()
        results = {key: _outcome(future) for key, future in futures.items()}
        stopped = [key for key, result in results.items() if isinstance(result, (BrokenProcessPool, CancelledError))]
        if stopped:
            logger.warning(f"A data access process stopped ({results[stopped[0]]!r}), {len(stopped)} request(s) unread")
        # The requests a worker that stopped did not read are left out, to be asked for again.
        try:
            on_done({key: result for key, result in results.items() if key not in stopped})
        except Exception:
            logger.exception("Cannot draw the data read in the background")


def _stop(executor: ProcessPoolExecutor):
    """Shut the executor down without waiting for the requests in progress."""
    # Its manager thread could be waiting for the rest of a result that a stopped worker was sending (see
    # AccessPool._release_stuck_executors): the pipe it reads ends once this process closes its end, which
    # the executor no longer holds once it is shut down.
    writer = getattr(getattr(executor, '_result_queue', None), '_writer', None)
    # The executor exposes its workers only through its process table.
    for process in list((getattr(executor, '_processes', None) or {}).values()):
        process.terminate()
    executor.shutdown(wait=False, cancel_futures=True)
    if writer is not None and not writer.closed:
        writer.close()


class AccessPool:
    """Runs AccessHelper data access requests in worker processes.

    Requests to a data source of PARALLEL_SOURCE_TYPES run in up to `workers` processes at
    once; requests to other data sources share a single worker. A worker starts with the
    first request it is given, or ahead of it with prepare(). Each worker reads through a
    data access object of its own, made by `data_access_factory` (a picklable callable; the
    default one sets up only the data sources of the types the worker reads), and logs
    through the loggers of this process.

    A request read before goes back to the worker that read it, whose data access cache may
    still hold the data; new requests go to the worker with the fewest requests to read.
    call() runs other methods of the data access object, from any thread.
    """

    def __init__(self, workers: int, data_access_factory: Callable = app_data_access):
        self._workers = max(1, workers)
        self._data_access_factory = data_access_factory
        # Forking a process that runs Qt and other threads is unsafe: workers start afresh everywhere.
        self._context = multiprocessing.get_context('spawn')
        self._log_queue = self._context.Queue()
        self._log_file = getattr(setupLogger.FileHandlerIplot.fhandler, 'baseFilename', None)
        # The records of the workers are logged from the thread that runs Qt, if any: log
        # handlers that show them in a widget can only run there.
        self._log_timer = self._log_listener = None
        if QCoreApplication.instance() is not None:
            self._log_timer = QTimer()
            self._log_timer.timeout.connect(self._log_worker_records)
            self._log_timer.start(_POLL_INTERVAL_MS)
        else:
            self._log_listener = logging.handlers.QueueListener(self._log_queue, _AsOwnRecord())
            self._log_listener.start()
        # Guards the workers and their bookkeeping below, which call() also uses from other threads.
        self._lock = threading.RLock()
        self._executors = {}  # type: Dict[int, ProcessPoolExecutor] # key: worker slot
        self._ready = {}  # type: Dict[int, Future] # key: worker slot
        # Requests given to each worker that it has not finished reading, by worker slot. They have a lock
        # of their own, never held while a worker is given a request (see _finished).
        self._loads = defaultdict(int)
        self._loads_lock = threading.Lock()
        self._stopped_since = {}  # type: Dict[int, float] # key: worker slot
        self._slots = OrderedDict()  # type: OrderedDict[tuple, int] # key: request key, last used last
        self._cache_epoch = 0
        # The worker that a new request goes to first when several have as few requests to read.
        self._turn = 0
        self._closed = False

    def start(self):
        """Start the workers for the configured data sources ahead of the first request."""
        self.prepare(getattr(AccessHelper.da, 'ds_list', None) or {})

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
                slots.update(range(self._workers) if self._is_parallel(name) else (_SERIAL_SLOT,))
        with self._lock:
            if self._closed:
                return
            for slot in sorted(slots):
                self._executor(slot)

    def fetch(self, requests: Iterable[dict], progress: Callable[[int, int], None] = None) \
            -> Optional[Dict[tuple, object]]:
        """Run data access requests in the worker processes and wait for them.

        Returns, by AccessHelper.request_key(), the result of each request or the exception it
        raised; identical requests run once. While waiting, the GUI keeps painting and running
        its timers, and user input waits for the requests to finish. `progress` is called with
        the number of finished requests and their total. Returns None if the wait is
        interrupted, e.g. because the application quits. Raises RuntimeError if the worker
        processes cannot start.
        """
        self._check_workers()
        unique = self._unique(requests)
        futures = {key: self._submit(key, params) for key, params in unique.items()}
        if not self._wait(list(futures.values()), len(unique), progress):
            return None
        self._check_workers()
        results = {key: _outcome(future) for key, future in futures.items()}
        # A worker that stops fails every request it was given. They are read again one by one,
        # so that a request that stops its worker each time fails on its own.
        stopped = [key for key, result in results.items() if isinstance(result, (BrokenProcessPool, CancelledError))]
        if stopped and not self._closed:
            logger.warning(f"A data access process stopped ({results[stopped[0]]}), reading again: "
                           + ", ".join(str(unique[key].get('varname')) for key in stopped))
        for key in stopped:
            result = DataAccessError(_STOPPED)
            if not self._closed:
                future = self._submit(key, unique[key])
                if not self._wait([future], 1, None):
                    return None
                self._check_workers()
                read_again = _outcome(future)
                if isinstance(read_again, BrokenProcessPool):
                    logger.warning(f"Reading {unique[key].get('varname')} stops the data access process")
                else:
                    result = read_again
            results[key] = result
        return results

    def fetch_later(self, requests: Iterable[dict], on_done: Callable[[Dict[tuple, object]], None]) -> PendingFetch:
        """Run data access requests in the worker processes without waiting for them.

        Once all are read, `on_done` is called in this thread, which runs a Qt event loop, with
        their results as fetch() returns them, except for those that a worker that stopped did
        not read. Raises RuntimeError if the worker processes cannot start.
        """
        self._check_workers()
        return PendingFetch(self, {key: self._submit(key, params) for key, params in self._unique(requests).items()},
                            on_done)

    def call(self, method: str, data_s_name: str, **kwargs):
        """Call a method of the data access object in a worker process and wait for its result:
        ``call('get_archive_window', 'codacuda', varname=...)`` returns what
        ``get_archive_window('codacuda', varname=...)`` returns.

        A thread that does not run Qt waits without holding the GIL, so that the GUI thread keeps
        running while the worker reads; the thread that runs Qt waits as fetch() does. A call
        whose worker stops is made once more. Raises DataAccessError if the method fails, the
        worker has no such data source or the call stops its worker again, and RuntimeError if
        the worker processes cannot start or the pool is shut down.
        """
        self._check_workers()
        for attempt in range(2):
            with self._lock:
                future = self._run(self._free_slot(data_s_name), _call, method, data_s_name, kwargs,
                                   self._cache_epoch)
            if not self._wait([future], 1, None):
                raise DataAccessError(_STOPPED if self._closed else "The wait for the data access process was interrupted")
            self._check_workers()
            result = _outcome(future)
            if not isinstance(result, BrokenProcessPool) or self._closed or attempt:
                break
            logger.warning(f"A data access process stopped ({result}), calling {method} again")
        if isinstance(result, (BrokenProcessPool, CancelledError)):
            raise DataAccessError(_STOPPED) from result
        if isinstance(result, Exception):
            raise result
        return result

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
        # The records are taken while the workers live: one stopped while it sends a record would
        # leave it half sent.
        if self._log_timer is not None:
            self._log_timer.stop()
            self._log_worker_records()
        if self._log_listener is not None:
            self._log_listener.stop()
        for executor in executors:
            _stop(executor)
        # Nothing may wait at exit for records that a stopped worker never finished sending.
        self._log_queue.cancel_join_thread()
        self._log_queue.close()

    def _log_worker_records(self):
        while True:
            try:
                record = self._log_queue.get_nowait()
            except queue.Empty:
                return
            _log_as_own(record)

    def _release_stuck_executors(self):
        """Let an executor whose worker stopped while it sent a result see that the worker stopped.

        Its manager thread waits for the rest of the result, which never comes, and the pipe it
        reads does not end while this process keeps its end open.
        """
        now = time.monotonic()
        with self._lock:
            for slot, executor in list(self._executors.items()):
                processes = list((getattr(executor, '_processes', None) or {}).values())
                if not processes or any(process.is_alive() for process in processes) or \
                        getattr(executor, '_broken', False):
                    self._stopped_since.pop(slot, None)
                    continue
                if now - self._stopped_since.setdefault(slot, now) < _STUCK_AFTER_S:
                    continue
                writer = getattr(getattr(executor, '_result_queue', None), '_writer', None)
                if writer is not None and not writer.closed:
                    logger.warning("A data access process stopped while it sent its result")
                    writer.close()

    def _check_workers(self):
        """Raise RuntimeError if a worker process could not start reading."""
        with self._lock:
            if self._closed:
                # Workers that the shutdown stopped while they started could start; their requests fail.
                return
            readies = list(self._ready.values())
        for ready in readies:
            error = ready.exception() if ready.done() and not ready.cancelled() else None
            if error is not None:
                raise RuntimeError(f"The data access processes cannot start: {error}") from error

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
            try:
                future = self._executor(slot).submit(function, *args)
            except BrokenProcessPool:
                logger.warning("A data access process had stopped, starting a new one")
                _stop(self._executors.pop(slot))
                future = self._executor(slot).submit(function, *args)
            with self._loads_lock:
                self._loads[slot] += 1
        future.add_done_callback(partial(self._finished, slot))
        return future

    def _finished(self, slot: int, _future: Future):
        # Called from the thread of the executor, which fails the requests of a worker that stopped holding
        # the lock that submit() takes (Python 3.12.1 and later): waiting here for self._lock, which _run()
        # holds while it submits, would leave both threads waiting for each other.
        with self._loads_lock:
            self._loads[slot] -= 1

    def _slot(self, key: tuple, params: dict) -> int:
        least_loaded = self._free_slot(params.get('data_s_name'))
        if least_loaded == _SERIAL_SLOT:
            return _SERIAL_SLOT
        slot = self._slots.pop(key, None)
        if slot is None or self._loads[slot] - self._loads[least_loaded] >= _AFFINITY_MAX_EXCESS:
            slot = least_loaded
        self._slots[key] = slot
        if len(self._slots) > _REMEMBERED_REQUESTS:
            self._slots.popitem(last=False)
        return slot

    def _free_slot(self, data_s_name: Optional[str]) -> int:
        """The worker slot for a new request to the data source: the worker with the fewest requests to read.
        Workers with as few take turns, so that requests read one at a time fill the caches of them all."""
        if not self._is_parallel(data_s_name):
            return _SERIAL_SLOT
        self._turn = (self._turn + 1) % self._workers
        return min(((self._turn + offset) % self._workers for offset in range(self._workers)),
                   key=lambda candidate: self._loads[candidate])

    def _executor(self, slot: int) -> ProcessPoolExecutor:
        if self._closed:
            raise RuntimeError("The data access pool is shut down")
        executor = self._executors.get(slot)
        if executor is None:
            parallel = slot != _SERIAL_SLOT
            executor = ProcessPoolExecutor(
                max_workers=1,
                mp_context=self._context,
                initializer=_init_worker,
                initargs=(self._log_queue, self._log_file, self._data_access_factory,
                          AccessHelper.num_samples, AccessHelper.num_samples_override,
                          PARALLEL_SOURCE_TYPES if parallel else self._serial_source_types(),
                          self._workers if parallel else 1, self._unconnected()))
            self._executors[slot] = executor
            # Its first task tells whether the worker can read (see _check_workers).
            self._ready[slot] = executor.submit(_ready)
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
        data_source = AccessHelper.da.get_data_source(data_s_name) if AccessHelper.da else None
        return getattr(data_source, 'source_type', None) in PARALLEL_SOURCE_TYPES

    def _wait(self, futures: list, total: int, progress: Optional[Callable[[int, int], None]]) -> bool:
        """Wait for the futures, reporting those done out of `total`. False if interrupted."""

        app = QCoreApplication.instance()
        # Only the thread that runs Qt keeps processing its events while it waits.
        loop = QEventLoop() if app is not None and QThread.currentThread() == app.thread() else None
        # Emptied once waited for: some PySide6 releases keep the slot of the timer connection below,
        # and with it the futures and their data, for a while.
        waiting = list(futures)

        def check() -> bool:
            done = sum(future.done() for future in waiting)
            if done < len(waiting):
                self._release_stuck_executors()
            # Before the progress report, which may fail, so that the wait ends anyway.
            if done == len(waiting) and loop is not None:
                loop.quit()
            if progress is not None:
                progress(done, total)
            return done == len(waiting)

        if loop is None:
            # Polled as the event loop below is: wait() alone never counts the futures that a shutdown
            # cancels, and nothing waits for the rest once the pool is shut down.
            while not all(future.done() for future in waiting) and not self._closed:
                wait(waiting, timeout=_POLL_INTERVAL_MS / 1000)
                self._release_stuck_executors()
            all_done = check()
        else:
            timer = QTimer()
            timer.timeout.connect(check)
            timer.start(_POLL_INTERVAL_MS)
            if not check():
                loop.exec(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)
            timer.stop()
            all_done = all(future.done() for future in waiting)
        waiting.clear()
        return all_done
