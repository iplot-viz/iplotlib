"""Tests for AccessPool: data access requests run in worker threads, each with a data access object of its own,
results come back by request key, and the GUI thread keeps running while it waits."""

import ctypes
import gc
import logging
import os
import subprocess
import sys
import threading
import time
import unittest
import weakref
from concurrent.futures import Future, wait
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
from PySide6.QtCore import QObject, Qt, QTimer

import iplotDataAccess.dataAccess as ida_data_access
from iplotDataAccess.appDataAccess import AppDataAccess
from iplotDataAccess.dataCommon import DataObj
from iplotLogging import setupLogger

import iplotlib.data_access.access_pool as access_pool
from iplotlib.data_access.access_pool import AccessPool
from iplotlib.interface.iplotSignalAdapter import AccessHelper, DataAccessError
from iplotlib.qt.testing import ensure_qapp

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

logger = setupLogger.get_logger(__name__)

T0 = 1_700_000_000_000_000_000
T1 = T0 + 60_000_000_000

_SAMPLE_LIMIT = ('Number of samples in reply exceeds available limit. Reduce request interval, use decimation '
                 'or read data by chunks.')


class _WorkerDataAccess:
    """Data access of the worker threads; the variable name selects the behaviour."""

    def __init__(self):
        self.clears = 0

    def get_data(self, data_s_name, **kwargs):
        name = kwargs['varname']
        if name == 'stall':
            time.sleep(30)
        if name.startswith('slow'):
            time.sleep(1.0)
        if name == 'missing':
            return SimpleNamespace(errcode=-1, errdesc='no data')
        if name == 'log':
            logger.warning("record from a worker")
        if name == 'fail':
            raise ValueError("the client failed")
        if name == 'limit':
            if kwargs['nbp'] == -1:
                return SimpleNamespace(errcode=-1, errdesc=_SAMPLE_LIMIT)
            return SimpleNamespace(errcode=0, errdesc='', xdata=T0 + np.arange(3), ydata=np.full(3, kwargs['nbp']),
                                   xunit='ns', yunit='A', resolved_pulse=None)
        values = {'slow-thread': [threading.get_ident()], 'clears': [self.clears],
                  'own': [id(self), id(AccessHelper.thread_data_access())]}.get(name, [1.0, 2.0])
        return SimpleNamespace(errcode=0, errdesc='', xdata=T0 + np.arange(len(values)),
                               ydata=np.asarray(values, dtype=float), xunit='ns', yunit='A', resolved_pulse=None)

    def get_archive_window(self, data_s_name, **kwargs):
        name = kwargs['varname']
        if name == 'stall':
            time.sleep(30)
        if name == 'fail':
            raise ValueError("no archive for fail")
        held = _hold_gil(0.8) if name == 'gil' else 0.0
        if name == 'sleep':
            time.sleep(0.8)
        reply = DataObj()
        reply.xdata, reply.ydata = T0 + np.arange(3), np.array([threading.get_ident(), held, float(kwargs['tsS'])])
        reply.xunit, reply.yunit = 'ns', 'A'
        return reply

    def clear_cache(self):
        self.clears += 1


def _hold_gil(seconds: float) -> float:
    """Sleep in C for `seconds` keeping the GIL, as a data access client built without releasing it does while it
    reads: ctypes calls the functions of a PyDLL without releasing it. The time it took."""
    start = time.perf_counter()
    if os.name == 'nt':
        ctypes.PyDLL('kernel32').Sleep(int(seconds * 1000))
    else:
        ctypes.PyDLL(None).usleep(int(seconds * 1e6))
    return time.perf_counter() - start


def _worker_data_access():
    return _WorkerDataAccess()


class _WorkerDataAccessOfSources(_WorkerDataAccess):
    """A data access object of the data sources it lists, as iplotDataAccess's DataAccess."""

    ds_list = {'uda': None, 'imas': None}


def _worker_data_access_of_sources():
    return _WorkerDataAccessOfSources()


class _WorkerDataAccessOfUdaOnly(_WorkerDataAccess):
    """A data access object that could not connect to the data source uda2 when it was made."""

    ds_list = {'uda': None}

    def get_connected_data_source_names(self):
        return ['uda']


class _Cache:
    """The query cache of a data source, as the LRUCache of cachetools."""

    def __init__(self, maxsize):
        self.maxsize = maxsize


class _WorkerDataAccessWithCaches(_WorkerDataAccess):
    """Data sources with a query cache each, and what a worker knows of the types it reads."""

    def __init__(self):
        super().__init__()
        self.ds_list = {'uda': SimpleNamespace(access_cache=_Cache(300)),
                        'imas': SimpleNamespace(access_cache=_Cache(300))}

    def cache_size(self, data_s_name):
        return self.ds_list[data_s_name].access_cache.maxsize

    def source_types(self, data_s_name):
        return sorted(access_pool._worker.source_types or [])

    def leave_unconnected(self, data_s_name):
        return sorted(access_pool._worker.leave_unconnected)


def _worker_data_access_with_caches():
    return _WorkerDataAccessWithCaches()


class _OverlapsRecorded:
    """Data access of the application and of the workers at once, that records how many reads of each data source
    type it makes at the same time."""

    ds_list = {'uda': SimpleNamespace(source_type='CODAC_UDA'), 'imas': SimpleNamespace(source_type='IMAS')}
    lock = threading.Lock()
    inside = {}
    most = {}

    def get_data_source(self, name):
        return self.ds_list.get(name)

    def get_data(self, data_s_name, **kwargs):
        with self.lock:
            self.inside[data_s_name] = self.inside.get(data_s_name, 0) + 1
            self.most[data_s_name] = max(self.most.get(data_s_name, 0), self.inside[data_s_name])
        time.sleep(0.5)
        with self.lock:
            self.inside[data_s_name] -= 1
        return SimpleNamespace(errcode=0, errdesc='', xdata=T0 + np.arange(2), ydata=np.ones(2), xunit='ns', yunit='A',
                               resolved_pulse=None)

    def clear_cache(self):
        pass


def _broken_data_access():
    raise RuntimeError("no configuration")


class _ApplicationDataAccess:
    """What the pool looks up in the application: the type of each data source."""

    ds_list = {'uda': SimpleNamespace(source_type='CODAC_UDA'), 'imas': SimpleNamespace(source_type='IMAS')}

    def get_data_source(self, name):
        return self.ds_list.get(name)


class _ApplicationDataAccessOfTwoUda(_ApplicationDataAccess):
    """An application connected to two UDA data sources."""

    ds_list = dict(_ApplicationDataAccess.ds_list, uda2=SimpleNamespace(source_type='CODAC_UDA'))


class _ApplicationDataAccessWithOneDown(_ApplicationDataAccess):
    """An application that could not connect to one of its UDA data sources."""

    unconnected = {'down'}


def _workers_started(pool: AccessPool, *data_sources) -> AccessPool:
    """The pool, once the workers of the data sources (all by default) have set up their data access, or failed to."""
    pool.prepare(data_sources or ('uda', 'imas'))
    for executor in list(pool._executors.values()):
        executor.ready.exception(timeout=60)
    return pool


# An application whose worker reads for 30 s when it exits. Prints when it asks for the read.
_EXIT_WHILE_READING = """
import sys
from PySide6.QtCore import QCoreApplication, QTimer
from iplotlib.data_access.access_pool import AccessPool
from iplotlib.data_access.tests.test_access_pool import _ApplicationDataAccess, _params, _worker_data_access
from iplotlib.interface.iplotSignalAdapter import AccessHelper
app = QCoreApplication([])
AccessHelper.da = _ApplicationDataAccess()
pool = AccessPool(1, data_access_factory=_worker_data_access)
pool.fetch_later([_params('stall')], print)
print('reading', flush=True)
QTimer.singleShot(1000, app.quit)
app.exec()
pool.shutdown()
sys.exit(0)
"""


def _params(varname, source='uda', end=T1):
    return dict(data_s_name=source, varname=varname, tsS=T0, tsE=end, tsFormat='absolute', pulse=None,
                envelope=False, extremities=False, nbp=-1)


def _key(params):
    return AccessHelper.request_key(params)


def _note_destructions(qobjects: list, threads: list):
    """Note in `threads` the thread that destroys each of the Qt objects."""
    for qobject in qobjects:
        qobject.destroyed.connect(lambda *_: threads.append(threading.current_thread()),
                                  Qt.ConnectionType.DirectConnection)


class _CapturingHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)


class AccessPoolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = ensure_qapp()
        cls._da = AccessHelper.da
        AccessHelper.da = _ApplicationDataAccess()
        cls.pool = _workers_started(AccessPool(2, data_access_factory=_worker_data_access))

    @classmethod
    def tearDownClass(cls):
        cls.pool.shutdown()
        AccessHelper.da = cls._da

    def _own_pool(self, factory=_worker_data_access, started=('uda', 'imas'), workers=2):
        """A pool of its own, once the workers of the data sources `started` have set up their data access."""
        pool = AccessPool(workers, data_access_factory=factory)
        self.addCleanup(pool.shutdown)
        return _workers_started(pool, *started) if started else pool

    def _arrived(self, delivered: list, seconds: float = 30):
        deadline = time.monotonic() + seconds
        while not delivered and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.01)
        return delivered

    def test_results_and_errors_come_back_by_request_key(self):
        plain, missing, fail = _params('plain'), _params('missing'), _params('fail')

        results = self.pool.fetch([plain, missing, dict(plain), fail])

        self.assertEqual(set(results), {_key(plain), _key(missing), _key(fail)})
        np.testing.assert_array_equal(results[_key(plain)]['d1'], [1.0, 2.0])
        self.assertIsInstance(results[_key(missing)], DataAccessError)
        self.assertIsInstance(results[_key(fail)], DataAccessError)
        self.assertEqual(str(results[_key(fail)]), "the client failed")

    def test_requests_to_a_parallel_source_run_at_the_same_time(self):
        requests = [_params('slow-thread', end=T1 + i) for i in range(2)]

        started = time.perf_counter()
        results = self.pool.fetch(requests)

        threads = {results[_key(params)]['d1'][0] for params in requests}
        self.assertEqual(len(threads), 2)
        self.assertLess(time.perf_counter() - started, 1.9)

    def test_requests_to_other_sources_share_one_worker(self):
        requests = [_params('slow-thread', source='imas', end=T1 + i) for i in range(2)]

        results = self.pool.fetch(requests)

        threads = {results[_key(params)]['d1'][0] for params in requests}
        self.assertEqual(len(threads), 1)
        self.assertNotIn(threading.get_ident(), threads)

    def test_each_worker_reads_through_a_data_access_object_of_its_own(self):
        requests = [_params('own', end=T1 + i) for i in range(2)] + [_params('own', source='imas')]

        results = self.pool.fetch(requests)

        owners = [tuple(results[_key(params)]['d1']) for params in requests]
        # The object that reads is the worker's, and each worker has another one.
        self.assertTrue(all(reader == own for reader, own in owners))
        self.assertEqual(len({reader for reader, _ in owners}), 3)
        self.assertNotIn(id(AccessHelper.da), {reader for reader, _ in owners})
        self.assertIsNone(AccessHelper.thread_data_access())

    def test_the_gui_thread_keeps_running_while_it_waits(self):
        ticks = []
        timer = QTimer()
        timer.timeout.connect(lambda: ticks.append(time.perf_counter()))
        timer.start(10)

        self.pool.fetch([_params('slow', end=T1 + 7)])
        timer.stop()

        self.assertGreater(len(ticks), 20)
        self.assertLess(max(b - a for a, b in zip(ticks, ticks[1:])), 0.5)

    def test_progress_counts_the_finished_requests(self):
        reports = []
        requests = [_params('plain', end=T1 + 10 + i) for i in range(3)]

        self.pool.fetch(requests, progress=lambda done, total: reports.append((done, total)))

        self.assertEqual(reports[-1], (3, 3))
        self.assertEqual([done for done, _ in reports], sorted(done for done, _ in reports))

    def test_a_failing_progress_report_does_not_hold_the_wait(self):
        reports = []

        def progress(done, total):
            reports.append(done)
            if len(reports) > 1:
                raise RuntimeError("progress bar gone")

        results = self.pool.fetch([_params('slow', end=T1 + 60)], progress=progress)

        self.assertEqual(len(results), 1)

    def test_workers_read_with_the_sample_settings_of_the_application(self):
        self.addCleanup(setattr, AccessHelper, 'num_samples', AccessHelper.num_samples)
        AccessHelper.num_samples = 777
        limit = _params('limit')

        result = self._own_pool(started=('uda',)).fetch([limit])[_key(limit)]

        np.testing.assert_array_equal(result['d1'], [777.0] * 3)
        self.assertTrue(result['isds'])

    def test_workers_clear_their_cache_when_asked(self):
        before = self.pool.fetch([_params('clears', source='imas', end=T1 + 20)])
        self.pool.clear_cache()
        after = self.pool.fetch([_params('clears', source='imas', end=T1 + 21)])

        cleared = [list(result.values())[0]['d1'][0] for result in (before, after)]
        self.assertEqual(cleared[1], cleared[0] + 1)

    def test_an_interrupted_wait_returns_nothing(self):
        class _QuitLoop:
            ProcessEventsFlag = access_pool.QEventLoop.ProcessEventsFlag

            def exec(self, flags):
                return 0

            def quit(self):
                pass

        with patch.object(access_pool, 'QEventLoop', _QuitLoop):
            self.assertIsNone(self.pool.fetch([_params('slow', end=T1 + 30)]))

    def test_worker_log_records_reach_the_loggers_of_the_application(self):
        records = _CapturingHandler()
        logger.addHandler(records)
        self.addCleanup(logger.removeHandler, records)

        self.pool.fetch([_params('log')])

        self.assertEqual([record.getMessage() for record in records.records], ["record from a worker"])
        self.assertTrue(records.records[0].threadName.startswith('data access'))

    def test_workers_that_cannot_set_up_data_access_say_so(self):
        pool = self._own_pool(factory=_broken_data_access, started=('uda',))

        with self.assertRaisesRegex(RuntimeError, "could not be set up"):
            pool.fetch([_params('plain')])
        with self.assertRaisesRegex(RuntimeError, "could not be set up"):
            pool.fetch_later([_params('plain')], lambda results: None)

    def test_shutdown_does_not_wait_for_requests_in_progress(self):
        pool = _workers_started(AccessPool(1, data_access_factory=_worker_data_access), 'uda')
        stall = _params('stall')
        # The request reads for 30 s.
        QTimer.singleShot(1000, pool.shutdown)

        started = time.perf_counter()
        results = pool.fetch([stall])

        self.assertLess(time.perf_counter() - started, 10)
        self.assertIsNone(results)
        with self.assertRaises(RuntimeError):
            pool.fetch([_params('plain')])

    def test_the_application_does_not_wait_at_exit_for_a_read_in_progress(self):
        started = time.perf_counter()
        application = subprocess.run([sys.executable, '-c', _EXIT_WHILE_READING], capture_output=True, text=True,
                                     timeout=60)

        # Importing iplotDataAccess may print before.
        self.assertEqual(application.stdout.split()[-1:], ['reading'], application.stderr[-2000:])
        self.assertEqual(application.returncode, 0)
        # The read lasts 30 s.
        self.assertLess(time.perf_counter() - started, 25)

    def test_a_read_in_the_background_is_never_delivered_within_the_call_that_asks_for_it(self):
        delivered = []

        self.pool.fetch_later([], delivered.append)
        nothing_yet = list(delivered)

        self.assertEqual(nothing_yet, [])
        self.assertEqual(self._arrived(delivered), [{}])

    def test_a_read_in_the_background_is_delivered_once_all_its_requests_are_read(self):
        delivered, threads = [], []
        requests = [_params('slow', end=T1 + 40), _params('plain', end=T1 + 41), _params('plain', source='imas')]

        def on_done(results):
            threads.append(threading.current_thread())
            delivered.append(results)

        self.pool.fetch_later(requests, on_done)

        results = self._arrived(delivered)[0]
        self.assertEqual(set(results), {_key(params) for params in requests})
        np.testing.assert_array_equal(results[_key(requests[0])]['d1'], [1.0, 2.0])
        # The thread that asked, which can use its widgets, and not a worker.
        self.assertEqual(threads, [threading.main_thread()])

    def test_a_read_in_the_background_tells_how_many_of_its_requests_are_read_until_it_is_delivered(self):
        told, delivered = [], []
        # Each read lasts a second: none is read before the call returns.
        requests = [_params('slow', end=T1 + 45), _params('slow', end=T1 + 46), _params('slow', source='imas',
                                                                                         end=T1 + 47)]

        self.pool.fetch_later(requests, lambda results: delivered.append(len(told)),
                              progress=lambda done, total: told.append((done, total, threading.current_thread())))
        at_once = list(told)
        self._arrived(delivered)

        self.assertEqual(at_once, [(0, 3, threading.main_thread())])
        counts = [done for done, _, _ in told]
        self.assertEqual(counts, sorted(counts))
        self.assertEqual(counts[-1], 3)
        self.assertEqual({(total, thread) for _, total, thread in told}, {(3, threading.main_thread())})
        # Told all of them before it delivers them.
        self.assertEqual(delivered, [len(told)])

    def test_a_read_in_the_background_whose_progress_cannot_be_told_is_delivered_anyway(self):
        delivered = []

        def failing(done, total):
            raise RuntimeError("the place is gone")

        with self.assertLogs('iplotlib.data_access.access_pool', level='ERROR'):
            self.pool.fetch_later([_params('plain', end=T1 + 48)], delivered.append, progress=failing)
            self._arrived(delivered)

        self.assertEqual(len(delivered), 1)

    def test_the_progress_of_a_wait_is_reported_in_the_waiting_thread(self):
        threads = set()

        self.pool.fetch([_params('slow', end=T1 + 43), _params('plain', source='imas', end=T1 + 44)],
                        progress=lambda done, total: threads.add(threading.current_thread()))

        self.assertEqual(threads, {threading.main_thread()})

    def test_reads_of_a_data_source_that_is_not_read_in_parallel_take_turns_whatever_their_thread(self):
        # As a read of this thread that was not made ahead does, while a worker reads the same data source.
        _OverlapsRecorded.inside, _OverlapsRecorded.most = {}, {}
        with patch.object(AccessHelper, 'da', _OverlapsRecorded()):
            pool = self._own_pool(factory=_OverlapsRecorded, started=('imas',))
            delivered = []
            pool.fetch_later([_params('read', source='imas')], delivered.append)
            time.sleep(0.2)

            AccessHelper._request_data(**_params('here', source='imas'))
            self._arrived(delivered)

        self.assertEqual(_OverlapsRecorded.most, {'imas': 1})

    def test_a_cancelled_read_in_the_background_is_not_delivered(self):
        delivered = []

        pending = self.pool.fetch_later([_params('slow', end=T1 + 42)], delivered.append)
        pending.cancel()
        time.sleep(1.5)
        self.app.processEvents()

        self.assertEqual(delivered, [])
        self.assertEqual(pending._futures, {})

    def test_a_fetch_dropped_while_it_reads_leaves_the_worker_no_qt_object_to_destroy(self):
        # The worker lets go of the future of its read once the read ends: a Qt object it held would be destroyed in
        # the worker thread, and Qt objects can only be destroyed in their own.
        pool = self._own_pool(started=('uda',), workers=1)
        destroyed_in = []
        before = [o for o in gc.get_objects() if isinstance(o, QObject)]

        pending = pool.fetch_later([_params('slow')], print)
        _note_destructions([o for o in gc.get_objects() if isinstance(o, QObject) and all(o is not b for b in before)],
                           destroyed_in)
        del before
        time.sleep(0.3)
        pending.cancel()
        del pending
        gc.collect()
        # Taken by the worker once it is done with the read.
        pool.fetch([_params('plain')])
        gc.collect()

        self.assertEqual(set(destroyed_in) - {threading.main_thread()}, set())

    def test_a_read_in_the_background_is_not_delivered_once_the_pool_is_shut_down(self):
        pool = self._own_pool(started=('uda',))
        delivered = []

        pool.fetch_later([_params('slow')], delivered.append)
        pool.shutdown()

        self.assertEqual(self._arrived(delivered, seconds=2), [])

    def test_a_read_in_the_background_that_a_shutdown_stops_says_so_if_asked(self):
        pool = self._own_pool(started=('uda',))
        delivered, stopped = [], []

        pool.fetch_later([_params('slow')], delivered.append, on_stopped=lambda: stopped.append(True))
        pool.shutdown()

        self.assertEqual(self._arrived(stopped, seconds=5), [True])
        self.assertEqual(delivered, [])

    def test_prepare_starts_only_the_workers_of_the_data_sources_given(self):
        pool = self._own_pool(started=())

        pool.prepare(['imas', 'not configured'])
        serial = dict(pool._executors)
        pool.prepare(['uda', 'imas'])

        self.assertEqual(set(serial), {access_pool._SERIAL_SLOT})
        self.assertEqual(set(pool._executors), {0, 1, access_pool._SERIAL_SLOT})
        self.assertIs(pool._executors[access_pool._SERIAL_SLOT], serial[access_pool._SERIAL_SLOT])

    def test_prepare_takes_a_single_name_too(self):
        pool = self._own_pool(started=())

        pool.prepare('uda')

        self.assertEqual(set(pool._executors), {0, 1})

    def test_a_shut_down_pool_starts_no_worker(self):
        pool = self._own_pool(started=())
        pool.shutdown()

        pool.prepare(['uda', 'imas'])

        self.assertEqual(pool._executors, {})

    def test_each_worker_reads_the_data_source_types_of_its_requests(self):
        pool = self._own_pool(factory=_worker_data_access_with_caches)

        parallel, _ = self._in_thread(lambda: pool.call('source_types', 'uda'))
        serial, _ = self._in_thread(lambda: pool.call('source_types', 'imas'))

        self.assertEqual(parallel, sorted(access_pool.PARALLEL_SOURCE_TYPES))
        self.assertEqual(serial, ['IMAS'])

    def test_the_workers_of_a_parallel_source_share_its_cache(self):
        pool = self._own_pool(factory=_worker_data_access_with_caches)

        parallel, _ = self._in_thread(lambda: pool.call('cache_size', 'uda'))
        serial, _ = self._in_thread(lambda: pool.call('cache_size', 'imas'))

        self.assertEqual(parallel, 150)
        self.assertEqual(serial, 300)

    def test_the_workers_leave_unconnected_the_data_sources_the_application_could_not_connect_to(self):
        with patch.object(AccessHelper, 'da', _ApplicationDataAccessWithOneDown()):
            pool = self._own_pool(factory=_worker_data_access_with_caches)
            parallel, _ = self._in_thread(lambda: pool.call('leave_unconnected', 'uda'))
            serial, _ = self._in_thread(lambda: pool.call('leave_unconnected', 'imas'))

        self.assertEqual(parallel, ['down'])
        self.assertEqual(serial, ['down'])

    def test_the_pool_keeps_no_result(self):
        result = self.pool.fetch([_params('plain', end=T1 + 90)])
        data = weakref.ref(list(result.values())[0]['d1'])

        del result
        gc.collect()

        self.assertIsNone(data())

    def test_a_read_in_the_background_keeps_no_result(self):
        delivered = []
        pending = self.pool.fetch_later([_params('plain', end=T1 + 91)], delivered.append)
        data = weakref.ref(list(self._arrived(delivered)[0].values())[0]['d1'])

        delivered.clear()
        gc.collect()

        self.assertIsNone(data())
        self.assertEqual(pending._futures, {})

    def test_requests_read_before_by_one_worker_are_spread_when_read_together(self):
        requests = [_params('slow-thread', end=T1 + 100 + i) for i in range(4)]
        for params in requests:
            self.pool.fetch([params])

        results = self.pool.fetch(requests)

        self.assertEqual(len({result['d1'][0] for result in results.values()}), 2)

    def test_new_requests_read_one_at_a_time_take_turns_between_the_workers(self):
        # Each worker keeps its share of the cache of the data source (see _share_cache).
        threads = set()
        for n in range(4):
            params = _params('slow-thread', end=T1 + 300 + n)
            threads.add(self.pool.fetch([params])[_key(params)]['d1'][0])

        self.assertEqual(len(threads), 2)

    def test_a_request_read_before_goes_back_to_its_worker(self):
        first, second = _params('slow-thread', end=T1 + 50), _params('slow-thread', end=T1 + 51)
        threads = self.pool.fetch([first, second])

        again = self.pool.fetch([second])

        self.assertNotEqual(threads[_key(first)]['d1'][0], threads[_key(second)]['d1'][0])
        self.assertEqual(again[_key(second)]['d1'][0], threads[_key(second)]['d1'][0])

    def _in_thread(self, target):
        """What `target` returns, or raises, run in another thread while this one runs its Qt events, and
        the longest time this thread could not run them meanwhile."""
        outcome, ticks = [], []

        def run():
            try:
                outcome.append(target())
            except Exception as e:
                outcome.append(e)

        timer = QTimer()
        timer.timeout.connect(lambda: ticks.append(time.perf_counter()))
        timer.start(10)
        thread = threading.Thread(target=run)
        ticks.append(time.perf_counter())
        thread.start()
        while thread.is_alive():
            self.app.processEvents()
            time.sleep(0.005)
        ticks.append(time.perf_counter())
        timer.stop()
        return outcome[0], max(b - a for a, b in zip(ticks, ticks[1:]))

    def _call(self, varname, pool=None, **kwargs):
        return (pool or self.pool).call('get_archive_window', 'uda', varname=varname, tsS='5', tsE='6', **kwargs)

    def test_a_call_from_another_thread_reads_in_a_worker_while_the_gui_thread_runs(self):
        reply, stall = self._in_thread(lambda: self._call('sleep'))

        reader, _, start = reply.ydata
        self.assertNotEqual(reader, threading.get_ident())
        self.assertEqual((reply.xunit, reply.yunit, start), ('ns', 'A', 5.0))
        np.testing.assert_array_equal(reply.xdata, T0 + np.arange(3))
        self.assertLess(stall, 0.4)

    def test_a_read_that_keeps_the_gil_stops_the_gui_thread_from_a_worker_too(self):
        # What a worker thread cannot spare the GUI thread: a client that does not release the GIL while it reads.
        reply, stall = self._in_thread(lambda: self._call('gil'))

        self.assertGreater(stall, reply.ydata[1] / 2)

    def test_calls_from_several_threads_at_once_get_their_own_replies(self):
        replies = {}

        def calls(thread):
            for i in range(5):
                start = thread * 100 + i
                replies[start] = self.pool.call('get_archive_window', 'uda' if i % 2 else 'imas',
                                                varname='plain', tsS=str(start))

        threads = [threading.Thread(target=calls, args=(thread,)) for thread in range(4)]
        for thread in threads:
            thread.start()
        fetched = self.pool.fetch([_params('plain', end=T1 + 300)])
        for thread in threads:
            thread.join(60)

        self.assertEqual(sorted(replies), sorted(thread * 100 + i for thread in range(4) for i in range(5)))
        self.assertTrue(all(reply.ydata[2] == start for start, reply in replies.items()))
        np.testing.assert_array_equal(list(fetched.values())[0]['d1'], [1.0, 2.0])
        # The workers count a request out right after they hand its reply over.
        deadline = time.monotonic() + 5
        while any(self.pool._loads.values()) and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertEqual(set(self.pool._loads.values()), {0})

    def test_a_method_that_fails_raises_its_message(self):
        with self.assertRaisesRegex(DataAccessError, "no archive for fail"):
            self._call('fail')

    def test_a_call_still_waiting_when_the_pool_shuts_down_ends(self):
        pool = _workers_started(AccessPool(1, data_access_factory=_worker_data_access), 'uda')
        # The call reads for 30 s.
        QTimer.singleShot(1000, pool.shutdown)

        started = time.perf_counter()
        error, _ = self._in_thread(lambda: self._call('stall', pool))

        self.assertLess(time.perf_counter() - started, 10)
        self.assertIsInstance(error, DataAccessError)
        with self.assertRaises(RuntimeError):
            self._call('plain', pool)

    def test_a_wait_in_another_thread_ends_for_a_request_that_a_shutdown_cancels(self):
        pool = self._own_pool(started=())
        cancelled = Future()
        cancelled.cancel()
        waits = []
        thread = threading.Thread(target=lambda: waits.append(pool._wait([cancelled], 1, None)), daemon=True)

        thread.start()
        thread.join(10)

        self.assertFalse(thread.is_alive())
        self.assertEqual(waits, [True])

    def test_calls_still_queued_when_the_pool_shuts_down_end_too(self):
        pool = _workers_started(AccessPool(1, data_access_factory=_worker_data_access), 'uda')
        outcomes = []

        def call():
            try:
                outcomes.append(self._call('stall', pool))
            except Exception as e:
                outcomes.append(e)

        threads = [threading.Thread(target=call, daemon=True) for _ in range(8)]
        for thread in threads:
            thread.start()
        # The first call reads for 30 s and the others wait.
        QTimer.singleShot(1000, pool.shutdown)
        deadline = time.monotonic() + 20
        while any(thread.is_alive() for thread in threads) and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.05)

        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual([str(outcome) for outcome in outcomes], [access_pool._STOPPED] * 8)

    def test_a_call_that_a_worker_took_as_the_pool_shuts_down_is_not_made(self):
        pool = _workers_started(AccessPool(1, data_access_factory=_worker_data_access), 'uda')
        executor = pool._executors[0]
        taken = threading.Event()
        make = executor._make

        def make_late(*call):
            # The worker took the call from its queue, and the shutdown comes before the call starts.
            taken.set()
            time.sleep(0.5)
            make(*call)

        executor._make = make_late
        future = pool._submit(_key(_params('slow')), _params('slow'))
        taken.wait(10)
        pool.shutdown()
        wait([future], timeout=10)

        self.assertTrue(future.cancelled())

    def test_a_fetch_made_while_the_workers_set_up_raises_if_they_cannot_read(self):
        def fails_later():
            time.sleep(1.0)
            raise RuntimeError("the data access set-up failed")

        pool = self._own_pool(factory=fails_later, started=())

        # So that the application reads in the GUI thread instead, as it does once a worker reports it cannot read.
        with self.assertRaisesRegex(RuntimeError, "cannot read"):
            pool.fetch([_params('plain')])

    def test_a_worker_that_cannot_connect_again_keeps_its_data_access(self):
        set_ups = []

        def connects_once():
            set_ups.append(threading.current_thread())
            if len(set_ups) > 1:
                raise OSError(28, "No space left on device")
            return _WorkerDataAccessOfUdaOnly()

        with patch.object(AccessHelper, 'da', _ApplicationDataAccessOfTwoUda()):
            pool = self._own_pool(factory=connects_once, started=('uda',), workers=1)
            pool.fetch([_params('plain', source='uda2')])
            plain = _params('plain', end=T1 + 80)
            results = pool.fetch([plain])

        self.assertEqual(len(set_ups), 2)
        np.testing.assert_array_equal(results[_key(plain)]['d1'], [1.0, 2.0])

    def test_a_call_to_a_data_source_the_worker_does_not_have_says_so(self):
        # Rather than read its default data source, as the data access object would.
        pool = self._own_pool(factory=_worker_data_access_of_sources)

        error, _ = self._in_thread(lambda: pool.call('get_archive_window', 'other', varname='plain', tsS='5'))
        reply, _ = self._in_thread(lambda: self._call('plain', pool))

        self.assertIsInstance(error, DataAccessError)
        self.assertIn("no data source other", str(error))
        self.assertEqual(reply.ydata[2], 5.0)

    def test_a_call_to_workers_that_cannot_set_up_data_access_says_so(self):
        pool = self._own_pool(factory=_broken_data_access, started=('uda',))

        error, _ = self._in_thread(lambda: self._call('plain', pool))

        self.assertIsInstance(error, RuntimeError)
        self.assertIn("could not be set up", str(error))

    def test_a_call_runs_a_function_given_the_data_access_object_of_a_worker(self):
        made, _ = self._in_thread(lambda: self.pool.call(_report_steps, 'uda', steps=0))

        thread, source, data_access = made
        self.assertNotIn(thread, (threading.get_ident(), threading.main_thread().ident))
        self.assertEqual(source, 'uda')
        self.assertIsInstance(data_access, _WorkerDataAccess)

    def _call_later(self, pool, method, seconds=30, **kwargs):
        """What on_done is given once the call made in the background ends, the progress reported until then with
        the thread it was reported in, and the longest time this thread could not run its Qt events meanwhile."""
        done, reported, ticks = [], [], []
        timer = QTimer()
        timer.timeout.connect(lambda: ticks.append(time.perf_counter()))
        timer.start(10)
        ticks.append(time.perf_counter())
        pool.call_later(method, 'uda', lambda result: done.append((result, list(reported))),
                        progress=lambda *args: reported.append((args, threading.current_thread())), **kwargs)
        self._arrived(done, seconds)
        ticks.append(time.perf_counter())
        timer.stop()
        self.assertTrue(done, "The call made in the background did not end")
        result, reported_before = done[0]
        return result, reported_before, max(b - a for a, b in zip(ticks, ticks[1:]))

    def test_a_call_in_the_background_reports_its_progress_in_this_thread_before_its_result(self):
        result, reported, stall = self._call_later(self.pool, _report_steps, steps=5, pause=0.2)

        self.assertNotEqual(result[0], threading.get_ident())
        self.assertEqual(result[1], 'uda')
        self.assertEqual(reported, [((step, 'uda'), threading.main_thread()) for step in range(5)])
        # The worker took a second, without the GIL.
        self.assertLess(stall, 0.5)

    def test_a_call_in_the_background_is_never_delivered_within_the_call_that_asks_for_it(self):
        done = []

        self.pool.call_later(_report_steps, 'uda', done.append, steps=0)
        nothing_yet = list(done)

        self.assertEqual(nothing_yet, [])
        self.assertEqual(self._arrived(done)[0][1], 'uda')

    def test_a_call_in_the_background_that_fails_gives_its_error(self):
        result, _, _ = self._call_later(self.pool, _fail)

        self.assertIsInstance(result, DataAccessError)
        self.assertIn("cannot export", str(result))

    def test_a_call_in_the_background_does_not_stop_this_thread_while_its_worker_sets_up(self):
        pool = self._own_pool(factory=_slow_worker_data_access, started=())

        result, _, stall = self._call_later(pool, _report_steps, steps=1)

        # The worker takes a second to set its data access up.
        self.assertEqual(result[1], 'uda')
        self.assertLess(stall, 0.5)

    def test_a_call_in_the_background_cancelled_before_it_starts_is_not_made(self):
        pool = self._own_pool(started=('uda',), workers=1)
        done, done_cancelled, reported = [], [], []

        pool.call_later(_report_steps, 'uda', done.append, steps=1, pause=1.0)
        cancelled = pool.call_later(_report_steps, 'uda', done_cancelled.append,
                                    progress=lambda *args: reported.append(args), steps=1)
        cancelled.cancel()
        pool.call_later(_report_steps, 'uda', done.append, steps=0)
        deadline = time.monotonic() + 30
        while len(done) < 2 and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.01)
        self._arrived([], seconds=0.3)

        self.assertEqual(len(done), 2)
        self.assertEqual(done_cancelled, [])
        self.assertEqual(reported, [])

    def test_a_call_in_the_background_cancelled_while_it_runs_reports_nothing_more(self):
        pool = self._own_pool(started=('uda',), workers=1)
        done, reported = [], []
        started = threading.Event()

        pending = pool.call_later(_report_steps, 'uda', done.append, progress=lambda *args: reported.append(args),
                                  steps=3, pause=0.3, started=started)
        self.assertTrue(started.wait(30))
        pending.cancel()
        # Made after the one cancelled, which runs to its end first.
        after = []
        pool.call_later(_report_steps, 'uda', after.append, steps=0)
        self._arrived(after)

        self.assertEqual(done, [])
        self.assertEqual(reported, [])

    def test_a_call_in_the_background_that_a_shutdown_leaves_unmade_or_unfinished_ends_too(self):
        pool = _workers_started(AccessPool(1, data_access_factory=_worker_data_access), 'uda')
        running, waiting = [], []

        pool.call_later(_report_steps, 'uda', running.append, steps=1, pause=30)
        pool.call_later(_report_steps, 'uda', waiting.append, steps=0)
        QTimer.singleShot(500, pool.shutdown)
        self._arrived(running, seconds=10)
        self._arrived(waiting, seconds=5)

        self.assertIsInstance(running[0], DataAccessError)
        self.assertEqual(str(running[0]), access_pool._STOPPED)
        self.assertIsInstance(waiting[0], DataAccessError)
        self.assertEqual(str(waiting[0]), access_pool._STOPPED)

    def test_a_call_in_the_background_to_a_shut_down_pool_says_so(self):
        pool = self._own_pool(started=('uda',))
        pool.shutdown()

        with self.assertRaises(RuntimeError):
            pool.call_later(_report_steps, 'uda', print, steps=0)


def _report_steps(data_access, data_s_name, steps, pause=0.0, started=None, progress=None):
    """A call that takes long, as an export does: it reports each of `steps` steps after sleeping `pause` seconds,
    without the GIL, and gives the thread it ran in, its data source and its data access object."""
    if started is not None:
        started.set()
    for step in range(steps):
        time.sleep(pause)
        if progress is not None:
            progress(step, data_s_name)
    return threading.get_ident(), data_s_name, data_access


def _fail(data_access, data_s_name, progress=None):
    raise ValueError("cannot export")


def _slow_worker_data_access():
    time.sleep(1.0)
    return _WorkerDataAccess()


class _DataAccess:
    """iplotDataAccess's DataAccess as the worker makes it: it notes what it is made with."""
    made = []
    configured = True

    def __init__(self, source_types=None, leave_unconnected=()):
        _DataAccess.made.append((source_types, leave_unconnected))
        self.unconnected = set(leave_unconnected)

    def load_config(self, conf_file=None):
        return _DataAccess.configured


class _DataAccessOfEveryType:
    """The DataAccess of an iplotDataAccess that sets up every data source type."""
    made = 0

    def __init__(self):
        _DataAccessOfEveryType.made += 1

    def load_config(self, conf_file=None):
        return True


class AppDataAccessTests(unittest.TestCase):
    """The data access a worker sets up, as the application's: for the data source types it reads."""

    def setUp(self):
        _DataAccess.made = []
        _DataAccess.configured = True
        for name, value in dict(source_types=frozenset({'IMAS'}), leave_unconnected=frozenset(), cache_epoch=0,
                                reconnected=set()).items():
            setattr(access_pool._worker, name, value)
        self.addCleanup(access_pool._worker.__dict__.clear)

    def _set_up(self, data_access=_DataAccess):
        with patch.object(ida_data_access, 'DataAccess', data_access):
            return access_pool.app_data_access()

    def test_only_the_data_sources_of_the_types_the_worker_reads_are_set_up(self):
        self._set_up()

        self.assertEqual(_DataAccess.made, [(frozenset({'IMAS'}), frozenset())])

    def test_the_data_access_of_a_worker_is_not_the_one_of_the_application(self):
        application = AppDataAccess.da

        data_access = self._set_up()

        self.assertIsInstance(data_access, _DataAccess)
        self.assertIs(AppDataAccess.da, application)

    def test_an_iplotdataaccess_that_sets_up_every_type_is_asked_for_all(self):
        _DataAccessOfEveryType.made = 0

        self._set_up(_DataAccessOfEveryType)

        self.assertEqual(_DataAccessOfEveryType.made, 1)

    def test_the_data_sources_the_application_could_not_connect_to_are_left_unconnected(self):
        access_pool._worker.leave_unconnected = frozenset({'down'})

        self._set_up()

        self.assertEqual(_DataAccess.made, [(frozenset({'IMAS'}), frozenset({'down'}))])

    def test_a_worker_whose_data_sources_are_all_left_unconnected_reports_none_missing(self):
        access_pool._worker.leave_unconnected = frozenset({'down'})
        _DataAccess.configured = False

        with patch.object(access_pool.logger, 'error') as error:
            self._set_up()

        error.assert_not_called()

    def test_a_worker_of_no_type_reports_no_missing_data_sources(self):
        access_pool._worker.source_types = frozenset()
        _DataAccess.configured = False

        with patch.object(access_pool.logger, 'error') as error:
            self._set_up()

        error.assert_not_called()

    def test_a_request_to_a_data_source_left_unconnected_does_not_set_data_access_up_again(self):
        access_pool._worker.leave_unconnected = frozenset({'down'})
        self.addCleanup(AccessHelper.set_thread_data_access, None)
        AccessHelper.set_thread_data_access(SimpleNamespace(get_connected_data_source_names=lambda: ['uda']))

        with patch.object(access_pool, '_set_up_data_access') as set_up:
            access_pool._data_access('down', 0)
            left_unconnected = set_up.call_count
            # One the application connected to, but the worker could not.
            access_pool._data_access('lost', 0)

        self.assertEqual(left_unconnected, 0)
        self.assertEqual(set_up.call_count, 1)

    def test_the_single_worker_reads_no_type_when_every_data_source_is_parallel(self):
        with patch.object(AccessHelper, 'da', SimpleNamespace(ds_list={'uda': SimpleNamespace(source_type='CODAC_UDA')})):
            self.assertEqual(AccessPool._serial_source_types(), frozenset())
        with patch.object(AccessHelper, 'da', SimpleNamespace()):
            self.assertIsNone(AccessPool._serial_source_types())

    def test_a_cache_keeps_its_share_when_data_access_is_set_up_again(self):
        data_access = SimpleNamespace(ds_list={'uda': SimpleNamespace(access_cache=_Cache(300))})

        access_pool._share_cache(data_access, 2)
        access_pool._share_cache(data_access, 2)

        self.assertEqual(data_access.ds_list['uda'].access_cache.maxsize, 150)



class _CancellableDataAccess(_WorkerDataAccess):
    """Reads 'held' until cancel() stops the read, as the UDA clients that can cancel do, or the test releases it."""
    started = threading.Event()
    released = threading.Event()
    cancels = []

    def __init__(self):
        super().__init__()
        self._stopped = threading.Event()

    def get_data(self, data_s_name, **kwargs):
        if kwargs['varname'] == 'held':
            type(self).started.set()
            while not (self._stopped.is_set() or self.released.is_set()):
                time.sleep(0.01)
            if self._stopped.is_set():
                self._stopped.clear()
                raise RuntimeError("The read was cancelled")
        return super().get_data(data_s_name, **kwargs)

    def cancel(self):
        type(self).cancels.append(threading.get_ident())
        self._stopped.set()
        return True


class StopReadingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = ensure_qapp()
        cls._da = AccessHelper.da
        AccessHelper.da = _ApplicationDataAccess()

    @classmethod
    def tearDownClass(cls):
        AccessHelper.da = cls._da

    def setUp(self):
        _CancellableDataAccess.started.clear()
        _CancellableDataAccess.released.clear()
        _CancellableDataAccess.cancels.clear()
        self.addCleanup(_CancellableDataAccess.released.set)
        self.pool = _workers_started(AccessPool(1, data_access_factory=_CancellableDataAccess), 'uda')
        self.addCleanup(self.pool.shutdown)

    def _reading(self, *varnames):
        delivered = []
        pending = self.pool.fetch_later([_params(name) for name in varnames], delivered.append)
        self.assertTrue(_CancellableDataAccess.started.wait(10))
        return pending, delivered

    def test_a_cancel_that_stops_reading_stops_the_read_its_worker_started(self):
        pending, delivered = self._reading('held')

        pending.cancel(stop_reading=True)
        start = time.monotonic()
        results = self.pool.fetch([_params('next')])

        self.assertLess(time.monotonic() - start, 5)
        self.assertNotIsInstance(list(results.values())[0], Exception)
        self.assertEqual(len(_CancellableDataAccess.cancels), 1)
        self.app.processEvents()
        self.assertEqual(delivered, [])

    def test_a_cancel_alone_lets_the_read_end(self):
        pending, delivered = self._reading('held')

        pending.cancel()
        _CancellableDataAccess.released.set()
        self.pool.fetch([_params('next')])

        self.assertEqual(_CancellableDataAccess.cancels, [])
        self.app.processEvents()
        self.assertEqual(delivered, [])

    def test_stopping_the_reads_of_a_fetch_leaves_alone_the_read_of_another(self):
        reading, _ = self._reading('held')
        waiting = self.pool.fetch_later([_params('next')], lambda results: None)

        waiting.cancel(stop_reading=True)

        self.assertEqual(_CancellableDataAccess.cancels, [])
        reading.cancel(stop_reading=True)
        self.assertEqual(len(_CancellableDataAccess.cancels), 1)

    def test_a_data_access_that_cannot_stop_a_read_lets_it_end(self):
        pool = _workers_started(AccessPool(1, data_access_factory=_worker_data_access), 'uda')
        self.addCleanup(pool.shutdown)
        pending = pool.fetch_later([_params('slow')], lambda results: None)
        time.sleep(0.2)

        pending.cancel(stop_reading=True)

        self.assertEqual(len(pool.fetch([_params('next')])), 1)


if __name__ == '__main__':
    unittest.main()
