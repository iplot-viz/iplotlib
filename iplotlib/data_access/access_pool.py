"""
Data access requests run in worker processes.

A data access client can keep the GIL for the whole of a blocking request, so a request
made from a worker thread still stalls the GUI thread. Worker processes leave the GUI
thread free and let independent requests run at the same time.
"""

import logging
import logging.handlers
import multiprocessing
import os
from collections import OrderedDict, defaultdict
from concurrent.futures import Future, ProcessPoolExecutor, wait
from concurrent.futures.process import BrokenProcessPool
from typing import Callable, Dict, Iterable, Optional

from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer

from iplotLogging import setupLogger
from iplotlib.interface.iplotSignalAdapter import AccessHelper, DataAccessError

logger = setupLogger.get_logger(__name__)

#: Data source types whose requests may run in several worker processes at once. Requests to
#: other sources share a single worker: an IMAS HDF5 entry cannot be opened by two processes.
PARALLEL_SOURCE_TYPES = frozenset({'CODAC_UDA'})

_POLL_INTERVAL_MS = 50

# Worker slot of the data sources whose requests share a single worker.
_SERIAL_SLOT = -1

# Requests whose worker is remembered: far more than the data access caches hold.
_REMEMBERED_REQUESTS = 4096

# Cache generation this worker process last cleared its data access cache for.
_worker_cache_epoch = 0


def app_data_access():
    """Data access configured as the application's, from the data sources file AppDataAccess finds."""
    from iplotDataAccess.appDataAccess import AppDataAccess
    if not AppDataAccess.initialize():
        logger.error("No data sources found for the data access worker")
    return AppDataAccess.get_data_access()


def _init_worker(log_queue, parent_log_file, data_access_factory, num_samples, num_samples_override):
    _forward_logging(log_queue, parent_log_file)
    AccessHelper.num_samples = num_samples
    AccessHelper.num_samples_override = num_samples_override
    # A failure here would stop the worker and fail every request with no reason given;
    # instead it is logged and the worker's requests report it (see _read).
    try:
        AccessHelper.da = data_access_factory()
    except Exception:
        logger.exception("Cannot set up data access in the worker process")


def _forward_logging(log_queue, parent_log_file):
    """Send this worker's log records to the parent process rather than to a log file of its own."""
    queue_handler = logging.handlers.QueueHandler(log_queue)
    own_file = setupLogger.FileHandlerIplot.fhandler
    # Loggers made from now on, and those made while this process imported its modules.
    setupLogger.FileHandlerIplot.fhandler = queue_handler
    for existing in list(logging.Logger.manager.loggerDict.values()):
        if isinstance(existing, logging.Logger) and own_file in existing.handlers:
            existing.removeHandler(own_file)
            existing.addHandler(queue_handler)
    own_file.close()
    own_path = getattr(own_file, 'baseFilename', None)
    if own_path and own_path != parent_log_file:
        try:
            if os.path.getsize(own_path) == 0:
                os.remove(own_path)
        except OSError:
            pass  # The empty file is only clutter.


def _read(params: dict, cache_epoch: int) -> dict:
    global _worker_cache_epoch
    if AccessHelper.da is None:
        raise DataAccessError("Data access could not be set up in the worker process, see the log")
    if cache_epoch != _worker_cache_epoch:
        AccessHelper.da.clear_cache()
        _worker_cache_epoch = cache_epoch
    return AccessHelper._request_data(**params)


def _ready() -> int:
    return os.getpid()


def _outcome(future: Future):
    """The future's result, or the exception it raised."""
    try:
        return future.result()
    except Exception as e:
        return e


def _stop(executor: Optional[ProcessPoolExecutor]):
    """Shut the executor down without waiting for the requests in progress."""
    if executor is None:
        return
    terminate_workers = getattr(executor, 'terminate_workers', None)  # Python 3.14
    if terminate_workers is not None:
        terminate_workers()
        return
    # Before that, the executor only exposes its workers through its process table.
    for process in list((getattr(executor, '_processes', None) or {}).values()):
        process.terminate()
    executor.shutdown(wait=False, cancel_futures=True)


class AccessPool:
    """Runs AccessHelper data access requests in worker processes.

    Requests to a data source of PARALLEL_SOURCE_TYPES run in up to `workers` processes at
    once; requests to other data sources share a single worker. Each worker reads through
    a data access object of its own, made by `data_access_factory` (a picklable callable),
    and logs to this process's log file.

    A request read before goes back to the worker that read it, whose data access cache may
    still hold the data; new requests go to the worker with the fewest requests to read.
    """

    def __init__(self, workers: int, data_access_factory: Callable = app_data_access):
        self._workers = max(1, workers)
        self._data_access_factory = data_access_factory
        # Forking a process that runs Qt and other threads is unsafe: workers start afresh everywhere.
        self._context = multiprocessing.get_context('spawn')
        self._log_queue = self._context.Queue()
        log_file = setupLogger.FileHandlerIplot.fhandler
        self._log_file = getattr(log_file, 'baseFilename', None)
        self._log_listener = logging.handlers.QueueListener(self._log_queue, log_file, respect_handler_level=True)
        self._log_listener.start()
        self._executors = {}  # type: Dict[int, ProcessPoolExecutor] # key: worker slot
        self._slots = OrderedDict()  # type: OrderedDict[tuple, int] # key: request key, last used last
        self._cache_epoch = 0
        self._closed = False

    def start(self):
        """Start the workers for the configured data sources ahead of the first request."""
        data_sources = getattr(AccessHelper.da, 'ds_list', None) or {}
        parallel = {ds.source_type in PARALLEL_SOURCE_TYPES for ds in data_sources.values()}
        slots = (list(range(self._workers)) if True in parallel else []) + ([_SERIAL_SLOT] if False in parallel else [])
        for slot in slots:
            self._executor(slot).submit(_ready)

    def fetch(self, requests: Iterable[dict], progress: Callable[[int, int], None] = None) \
            -> Optional[Dict[tuple, object]]:
        """Run data access requests in the worker processes and wait for them.

        Returns, by AccessHelper.request_key(), the result of each request or the exception it
        raised; identical requests run once. While waiting, the GUI keeps painting and running
        its timers, and user input waits for the requests to finish. `progress` is called with
        the number of finished requests and their total. Returns None if the wait is
        interrupted, e.g. because the application quits.
        """
        unique = {}
        for params in requests:
            unique.setdefault(AccessHelper.request_key(params), params)
        load = defaultdict(int)
        futures = {key: self._submit(key, params, load) for key, params in unique.items()}
        if not self._wait(list(futures.values()), 0, len(unique), progress):
            return None
        results = {key: _outcome(future) for key, future in futures.items()}
        # A worker that stops fails every request it was given. They are read again one by one,
        # so that a request that stops its worker each time fails on its own.
        stopped = [key for key, result in results.items() if isinstance(result, BrokenProcessPool)]
        if stopped and not self._closed:
            logger.warning(f"A data access process stopped, reading {len(stopped)} request(s) again")
        for done, key in enumerate(stopped, start=len(unique) - len(stopped)):
            result = DataAccessError("The data access process stopped while reading the data")
            if not self._closed:
                future = self._submit(key, unique[key], defaultdict(int))
                if not self._wait([future], done, len(unique), progress):
                    return None
                read_again = _outcome(future)
                if not isinstance(read_again, BrokenProcessPool):
                    result = read_again
            results[key] = result
        return results

    def clear_cache(self):
        """Make every worker clear its data access cache before its next request."""
        self._cache_epoch += 1

    def shutdown(self):
        """Stop the workers without waiting for the requests they are reading."""
        self._closed = True
        for slot in list(self._executors):
            _stop(self._executors.pop(slot))
        if self._log_listener is not None:
            self._log_listener.stop()
            self._log_listener = None

    def _submit(self, key: tuple, params: dict, load: Dict[int, int]) -> Future:
        slot = self._slot(key, params, load)
        load[slot] += 1
        try:
            return self._executor(slot).submit(_read, params, self._cache_epoch)
        except BrokenProcessPool:
            # The worker of this slot stopped earlier: a new one takes the request.
            _stop(self._executors.pop(slot))
            return self._executor(slot).submit(_read, params, self._cache_epoch)

    def _slot(self, key: tuple, params: dict, load: Dict[int, int]) -> int:
        if not self._is_parallel(params):
            return _SERIAL_SLOT
        slot = self._slots.pop(key, None)
        if slot is None:
            slot = min(range(self._workers), key=lambda candidate: load[candidate])
        self._slots[key] = slot
        if len(self._slots) > _REMEMBERED_REQUESTS:
            self._slots.popitem(last=False)
        return slot

    def _executor(self, slot: int) -> ProcessPoolExecutor:
        if self._closed:
            raise RuntimeError("The data access pool is shut down")
        executor = self._executors.get(slot)
        if executor is None:
            executor = ProcessPoolExecutor(
                max_workers=1,
                mp_context=self._context,
                initializer=_init_worker,
                initargs=(self._log_queue, self._log_file, self._data_access_factory,
                          AccessHelper.num_samples, AccessHelper.num_samples_override))
            self._executors[slot] = executor
        return executor

    @staticmethod
    def _is_parallel(params: dict) -> bool:
        data_source = AccessHelper.da.get_data_source(params.get('data_s_name')) if AccessHelper.da else None
        return getattr(data_source, 'source_type', None) in PARALLEL_SOURCE_TYPES

    @staticmethod
    def _wait(futures: list, finished: int, total: int, progress: Optional[Callable[[int, int], None]]) -> bool:
        """Wait for the futures, reporting `finished` plus those done out of `total`. False if interrupted."""

        def all_done() -> bool:
            done = sum(future.done() for future in futures)
            if progress is not None:
                progress(finished + done, total)
            return done == len(futures)

        if QCoreApplication.instance() is None:
            wait(futures)
            return all_done()
        loop = QEventLoop()
        timer = QTimer()
        timer.timeout.connect(lambda: all_done() and loop.quit())
        timer.start(_POLL_INTERVAL_MS)
        if not all_done():
            loop.exec(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)
        timer.stop()
        return all(future.done() for future in futures)
