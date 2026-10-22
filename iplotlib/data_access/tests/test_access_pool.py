"""Tests for AccessPool: data access requests run in worker processes, results come back
by request key, and the GUI thread keeps running while it waits. Until the workers have
started, the requests are read in this process."""

import ctypes
import gc
import logging
import multiprocessing
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import weakref
from concurrent.futures import Future, ProcessPoolExecutor
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
from PySide6.QtCore import QTimer

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

_cache_clears = 0

_SAMPLE_LIMIT = ('Number of samples in reply exceeds available limit. Reduce request interval, use decimation '
                 'or read data by chunks.')


class _UnpicklableError(Exception):
    """Cannot be rebuilt from its arguments, like some errors of compiled data access clients."""

    def __init__(self, code, text):
        super().__init__(f"{code}: {text}")


class _WorkerDataAccess:
    """Data access of the worker processes; the variable name selects the behaviour."""

    def get_data(self, data_s_name, **kwargs):
        name = kwargs['varname']
        if name == 'crash':
            os._exit(3)
        if name == 'stall':
            time.sleep(30)
        if name.startswith('slow'):
            time.sleep(1.0)
        if name == 'missing':
            return SimpleNamespace(errcode=-1, errdesc='no data')
        if name == 'log':
            logger.warning("record from a worker")
        if name == 'unpicklable':
            raise _UnpicklableError(7, "the client failed")
        if name == 'limit':
            if kwargs['nbp'] == -1:
                return SimpleNamespace(errcode=-1, errdesc=_SAMPLE_LIMIT)
            return SimpleNamespace(errcode=0, errdesc='', xdata=T0 + np.arange(3), ydata=np.full(3, kwargs['nbp']),
                                   xunit='ns', yunit='A', resolved_pulse=None)
        values = {'slow-pid': [os.getpid()], 'clears': [_cache_clears]}.get(name, [1.0, 2.0])
        return SimpleNamespace(errcode=0, errdesc='', xdata=T0 + np.arange(len(values)),
                               ydata=np.asarray(values, dtype=float), xunit='ns', yunit='A', resolved_pulse=None)

    def get_archive_window(self, data_s_name, **kwargs):
        name = kwargs['varname']
        if name == 'crash':
            os._exit(3)
        if name == 'crash-once' and not os.path.exists(kwargs['marker']):
            open(kwargs['marker'], 'w').close()
            os._exit(3)
        if name == 'stall':
            time.sleep(30)
        if name == 'fail':
            raise ValueError("no archive for fail")
        held = _hold_gil(0.8) if name == 'gil' else 0.0
        reply = DataObj()
        reply.xdata, reply.ydata = T0 + np.arange(3), np.array([os.getpid(), held, float(kwargs['tsS'])])
        reply.xunit, reply.yunit = 'ns', 'A'
        return reply

    def clear_cache(self):
        global _cache_clears
        _cache_clears += 1


def _hold_gil(seconds: float) -> float:
    """Sleep in C for `seconds` keeping the GIL, as a compiled data access client can keep it while it
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


class _Cache:
    """The query cache of a data source, as the LRUCache of cachetools."""

    def __init__(self, maxsize):
        self.maxsize = maxsize


class _WorkerDataAccessWithCaches(_WorkerDataAccess):
    """Data sources with a query cache each, and what a worker knows of the types it reads."""

    def __init__(self):
        self.ds_list = {'uda': SimpleNamespace(access_cache=_Cache(300)),
                        'imas': SimpleNamespace(access_cache=_Cache(300))}

    def cache_size(self, data_s_name):
        return self.ds_list[data_s_name].access_cache.maxsize

    def source_types(self, data_s_name):
        return sorted(access_pool._worker_source_types or [])

    def leave_unconnected(self, data_s_name):
        return sorted(access_pool._worker_leave_unconnected)


def _worker_data_access_with_caches():
    return _WorkerDataAccessWithCaches()


def _broken_data_access():
    raise RuntimeError("no configuration")


def _slow_data_access():
    time.sleep(10)
    return _WorkerDataAccess()


def _slow_to_start_again_data_access():
    """Sets up at once the first time, and in 10 s once the file that IPLOT_TEST_SET_UP names says it did."""
    marker = os.environ['IPLOT_TEST_SET_UP']
    if os.path.exists(marker):
        time.sleep(10)
    else:
        open(marker, 'w').close()
    return _WorkerDataAccess()


class _ParentDataAccess:
    """What the pool looks up in this process: the type of each data source."""

    ds_list = {'uda': SimpleNamespace(source_type='CODAC_UDA'), 'imas': SimpleNamespace(source_type='IMAS')}

    def get_data_source(self, name):
        return self.ds_list.get(name)


class _ParentDataAccessWithOneDown(_ParentDataAccess):
    """An application that could not connect to one of its UDA data sources."""

    unconnected = {'down'}


class _ParentDataAccessThatReads(_ParentDataAccess, _WorkerDataAccess):
    """The data access object of this process, which reads as those of the workers do. It notes what it is asked
    for, and fails what stops a worker instead of stopping this process."""

    def __init__(self):
        self.asked = []
        # A read of 'until-started' lasts until this says so.
        self.started = lambda: True

    def get_data(self, data_s_name, **kwargs):
        self.asked.append(kwargs['varname'])
        if kwargs['varname'] == 'crash':
            raise RuntimeError("read in the application")
        while kwargs['varname'] == 'until-started' and not self.started():
            time.sleep(0.05)
        return super().get_data(data_s_name, **kwargs)

    def get_archive_window(self, data_s_name, **kwargs):
        self.asked.append(kwargs['varname'])
        if kwargs['varname'] == 'crash':
            raise RuntimeError("called in the application")
        return super().get_archive_window(data_s_name, **kwargs)


def _workers_started(pool: AccessPool, *data_sources) -> AccessPool:
    """The pool, once the workers of the data sources (all by default) have started, or failed to: until then, it
    reads the requests in this process."""
    pool.prepare(data_sources or ('uda', 'imas'))
    for ready in list(pool._ready.values()):
        ready.exception(timeout=120)
    return pool


def _alive(pid: int) -> bool:
    if os.name == 'nt':
        import ctypes
        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        code = ctypes.c_ulong()
        ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(handle)
        return code.value == 259  # STILL_ACTIVE
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


# An application that starts a worker, prints its process id and waits to be killed.
_APPLICATION = """
from PySide6.QtCore import QCoreApplication
from iplotlib.data_access.access_pool import AccessPool
from iplotlib.data_access.tests.test_access_pool import (_ParentDataAccess, _params, _worker_data_access,
                                                         _workers_started)
from iplotlib.interface.iplotSignalAdapter import AccessHelper
app = QCoreApplication([])
AccessHelper.da = _ParentDataAccess()
pool = _workers_started(AccessPool(1, data_access_factory=_worker_data_access), 'uda')
print(int(list(pool.fetch([_params('slow-pid')]).values())[0]['d1'][0]), flush=True)
input()
"""


# An application whose worker stops while another of its threads gives that worker a request (see
# AccessPool._run). Prints whether the request was given, or the wait for it ended.
_STOPPED_WHILE_GIVEN = """
import os, signal, threading, time
from iplotlib.data_access.access_pool import AccessPool, _read
from iplotlib.data_access.tests.test_access_pool import (_ParentDataAccess, _params, _worker_data_access, T1,
                                                         _workers_started)
from iplotlib.interface.iplotSignalAdapter import AccessHelper
AccessHelper.da = _ParentDataAccess()
pool = _workers_started(AccessPool(1, data_access_factory=_worker_data_access), 'uda')
worker = pool._ready[0].result()
# Requests the worker has not read yet: its executor fails them, calling back the pool, when it stops.
for n in range(2):
    params = _params('stall', end=T1 + n)
    pool._submit(AccessHelper.request_key(params), params)
given = threading.Event()

def give_a_request():
    with pool._lock:
        os.kill(worker, signal.SIGTERM)
        time.sleep(3)
        try:
            pool._executors[0].submit(_read, _params('plain'), 0)
        except Exception:
            pass
    given.set()

threading.Thread(target=give_a_request, daemon=True).start()
print('given' if given.wait(30) else 'blocked', flush=True)
os._exit(0)
"""


def _params(varname, source='uda', end=T1):
    return dict(data_s_name=source, varname=varname, tsS=T0, tsE=end, tsFormat='absolute', pulse=None,
                envelope=False, extremities=False, nbp=-1)


def _key(params):
    return AccessHelper.request_key(params)


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
        AccessHelper.da = _ParentDataAccess()
        cls.pool = _workers_started(AccessPool(2, data_access_factory=_worker_data_access))

    @classmethod
    def tearDownClass(cls):
        cls.pool.shutdown()
        AccessHelper.da = cls._da

    def _own_pool(self, factory=_worker_data_access, started=('uda', 'imas')):
        """A pool of its own, once the workers of the data sources `started` have started."""
        pool = AccessPool(2, data_access_factory=factory)
        self.addCleanup(pool.shutdown)
        return _workers_started(pool, *started) if started else pool

    def test_results_and_errors_come_back_by_request_key(self):
        plain, missing = _params('plain'), _params('missing')

        results = self.pool.fetch([plain, missing, dict(plain)])

        self.assertEqual(set(results), {_key(plain), _key(missing)})
        np.testing.assert_array_equal(results[_key(plain)]['d1'], [1.0, 2.0])
        self.assertIsInstance(results[_key(missing)], DataAccessError)

    def test_requests_to_a_parallel_source_run_at_the_same_time(self):
        requests = [_params('slow-pid', end=T1 + i) for i in range(2)]

        results = self.pool.fetch(requests)

        pids = {results[_key(params)]['d1'][0] for params in requests}
        self.assertEqual(len(pids), 2)

    def test_requests_to_other_sources_share_one_worker(self):
        requests = [_params('slow-pid', source='imas', end=T1 + i) for i in range(2)]

        results = self.pool.fetch(requests)

        pids = {results[_key(params)]['d1'][0] for params in requests}
        self.assertEqual(len(pids), 1)

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

    def test_an_error_this_process_cannot_rebuild_comes_back_with_its_message(self):
        unpicklable, plain = _params('unpicklable'), _params('plain', end=T1 + 70)

        results = self.pool.fetch([unpicklable, plain])

        self.assertIsInstance(results[_key(unpicklable)], DataAccessError)
        self.assertEqual(str(results[_key(unpicklable)]), "7: the client failed")
        np.testing.assert_array_equal(results[_key(plain)]['d1'], [1.0, 2.0])

    def test_workers_read_with_the_sample_settings_of_this_process(self):
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

    def test_worker_log_records_reach_the_logger_of_the_same_name(self):
        # Here as in the worker: the module's logger, whose handlers include the log file.
        records = _CapturingHandler()
        logger.addHandler(records)
        self.addCleanup(logger.removeHandler, records)

        def from_a_worker():
            return [record for record in records.records
                    if record.getMessage() == "record from a worker" and record.process != os.getpid()]

        self.pool.fetch([_params('log')])
        deadline = time.monotonic() + 5
        while not from_a_worker() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.05)

        self.assertTrue(from_a_worker())
        self.assertEqual(len(from_a_worker()), 1)

    def test_a_worker_that_stops_fails_only_its_own_request(self):
        pool = self._own_pool(started=('uda',))
        crash, plain = _params('crash'), _params('plain')

        results = pool.fetch([crash, plain])

        self.assertIsInstance(results[_key(crash)], DataAccessError)
        self.assertIn("stopped", str(results[_key(crash)]))
        np.testing.assert_array_equal(results[_key(plain)]['d1'], [1.0, 2.0])
        later = pool.fetch([_params('plain', end=T1 + 40)])
        self.assertEqual(len(later), 1)

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
        QTimer.singleShot(2000, pool.shutdown)

        started = time.perf_counter()
        results = pool.fetch([stall])

        self.assertLess(time.perf_counter() - started, 15)
        self.assertIsInstance(results[_key(stall)], Exception)
        with self.assertRaises(RuntimeError):
            pool.fetch([_params('plain')])

    def test_requests_are_read_here_while_their_workers_start(self):
        pool = self._own_pool(factory=_slow_data_access, started=())
        uda, imas = _params('slow-pid'), _params('slow-pid', source='imas')

        with patch.object(AccessHelper, 'da', _ParentDataAccessThatReads()):
            results = pool.fetch([uda, imas])

        # The workers take 10 s to start.
        self.assertFalse(any(ready.done() for ready in pool._ready.values()))
        self.assertEqual([results[_key(uda)]['d1'][0], results[_key(imas)]['d1'][0]], [os.getpid()] * 2)
        self.assertEqual(set(pool._executors), {0, 1, access_pool._SERIAL_SLOT})

    def test_a_request_still_to_read_here_goes_to_a_worker_that_started_meanwhile(self):
        pool = self._own_pool(started=())
        here = _ParentDataAccessThatReads()
        here.started = lambda: any(ready.done() for ready in list(pool._ready.values()))
        requests = [_params('until-started')] + [_params('slow-pid', end=T1 + n) for n in range(3)]

        with patch.object(AccessHelper, 'da', here):
            results = pool.fetch(requests)

        self.assertEqual(here.asked, ['until-started'])
        self.assertNotIn(os.getpid(), [results[_key(params)]['d1'][0] for params in requests[1:]])

    def test_requests_go_to_the_workers_once_they_have_started(self):
        pool = self._own_pool(started=())
        first, then = _params('slow-pid', end=T1 + 1), _params('slow-pid', end=T1 + 2)

        with patch.object(AccessHelper, 'da', _ParentDataAccessThatReads()):
            here = pool.fetch([first])[_key(first)]['d1'][0]
            _workers_started(pool)
            there = pool.fetch([then])[_key(then)]['d1'][0]

        self.assertEqual(here, os.getpid())
        self.assertNotEqual(there, os.getpid())

    def test_a_read_in_the_background_is_made_here_while_its_workers_start(self):
        pool = self._own_pool(factory=_slow_data_access, started=())
        delivered = []

        with patch.object(AccessHelper, 'da', _ParentDataAccessThatReads()):
            pending = pool.fetch_later([_params('slow-pid', source='imas')], delivered.append)
        deadline = time.monotonic() + 5
        while not delivered and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.01)

        self.assertEqual(list(delivered[0].values())[0]['d1'][0], os.getpid())
        self.assertEqual(pending._futures, {})

    def test_a_call_is_made_here_while_its_workers_start(self):
        pool = self._own_pool(factory=_slow_data_access, started=())

        with patch.object(AccessHelper, 'da', _ParentDataAccessThatReads()):
            reply, _ = self._in_thread(lambda: self._call('plain', pool))

        # The workers take 10 s to start.
        self.assertFalse(any(ready.done() for ready in pool._ready.values()))
        self.assertEqual(reply.ydata[0], os.getpid())

    def test_once_a_worker_has_started_requests_wait_for_it_to_start_again_after_it_stopped(self):
        # Read here, a request that stopped a worker would stop the application too. The fetch reads the request
        # once more in a worker, which it stops again; the call comes while that worker starts once more.
        pool = _workers_started(AccessPool(1, data_access_factory=_worker_data_access), 'uda')
        self.addCleanup(pool.shutdown)
        here, crash = _ParentDataAccessThatReads(), _params('crash')

        with patch.object(AccessHelper, 'da', here):
            results = pool.fetch([crash])
            error, _ = self._in_thread(lambda: self._call('crash', pool))

        self.assertEqual(str(results[_key(crash)]), access_pool._STOPPED)
        self.assertEqual(str(error), access_pool._STOPPED)
        self.assertEqual(here.asked, [])

    def test_a_request_read_again_while_its_worker_starts_again_ends_when_the_pool_shuts_down(self):
        marker = os.path.join(tempfile.mkdtemp(), 'set up')
        self.addCleanup(os.rmdir, os.path.dirname(marker))
        self.addCleanup(os.remove, marker)
        crash = _params('crash')

        with patch.dict(os.environ, {'IPLOT_TEST_SET_UP': marker}):
            pool = _workers_started(AccessPool(1, data_access_factory=_slow_to_start_again_data_access), 'uda')
            # Once the request stopped the worker, while the worker takes 10 s to start again.
            QTimer.singleShot(3000, pool.shutdown)
            started = time.perf_counter()
            results = pool.fetch([crash])
            error, _ = self._in_thread(lambda: self._call('plain', pool))

        self.assertLess(time.perf_counter() - started, 8)
        self.assertEqual(str(results[_key(crash)]), access_pool._STOPPED)
        self.assertIsInstance(error, RuntimeError)
        self.assertIn("shut down", str(error))

    def test_start_launches_the_workers_of_the_configured_sources(self):
        pool = self._own_pool(started=())

        pool.start()

        self.assertEqual(set(pool._executors), {0, 1, access_pool._SERIAL_SLOT})

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
        with patch.object(AccessHelper, 'da', _ParentDataAccessWithOneDown()):
            pool = self._own_pool(factory=_worker_data_access_with_caches)
            parallel, _ = self._in_thread(lambda: pool.call('leave_unconnected', 'uda'))
            serial, _ = self._in_thread(lambda: pool.call('leave_unconnected', 'imas'))

        self.assertEqual(parallel, ['down'])
        self.assertEqual(serial, ['down'])

    def test_workers_stop_when_the_application_is_killed(self):
        application = subprocess.Popen([sys.executable, '-c', _APPLICATION], stdin=subprocess.PIPE,
                                       stdout=subprocess.PIPE, text=True)
        self.addCleanup(application.kill)
        worker = next(int(line) for line in application.stdout if line.strip().isdigit())
        self.assertTrue(_alive(worker))

        application.kill()
        application.wait()
        deadline = time.monotonic() + 10
        while _alive(worker) and time.monotonic() < deadline:
            time.sleep(0.1)

        self.assertFalse(_alive(worker))

    def test_a_worker_that_stops_while_it_is_given_a_request_blocks_no_thread(self):
        # Python 3.12.1 and later fail the requests of a stopped worker holding the lock that submit() takes.
        # The application bounds its wait for the request itself. The timeout only ends one that hangs before, and
        # leaves it the minutes that starting Python and a worker can take on a loaded machine.
        application = subprocess.run([sys.executable, '-c', _STOPPED_WHILE_GIVEN], capture_output=True, text=True,
                                     timeout=600)

        self.assertIn('given', application.stdout.split(), application.stdout + application.stderr[-2000:])

    @unittest.skipUnless(os.name == 'posix', "Ctrl+C reaches every process of the console the same way on Windows")
    def test_ctrl_c_is_left_to_the_application(self):
        pid = self.pool.fetch([_params('slow-pid', end=T1 + 80)])
        worker = int(list(pid.values())[0]['d1'][0])

        os.kill(worker, signal.SIGINT)
        time.sleep(0.5)

        self.assertTrue(_alive(worker))
        again = self.pool.fetch([_params('slow-pid', end=T1 + 80)])
        self.assertEqual(int(list(again.values())[0]['d1'][0]), worker)

    def test_the_pool_keeps_no_result(self):
        result = self.pool.fetch([_params('plain', end=T1 + 90)])
        data = weakref.ref(list(result.values())[0]['d1'])

        del result
        gc.collect()

        self.assertIsNone(data())

    def test_a_read_in_the_background_keeps_no_result(self):
        delivered = []
        pending = self.pool.fetch_later([_params('plain', end=T1 + 91)], delivered.append)
        deadline = time.monotonic() + 30
        while not delivered and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.01)
        data = weakref.ref(list(delivered[0].values())[0]['d1'])

        delivered.clear()
        gc.collect()

        self.assertIsNone(data())
        self.assertEqual(pending._futures, {})

    def test_requests_read_before_by_one_worker_are_spread_when_read_together(self):
        requests = [_params('slow-pid', end=T1 + 100 + i) for i in range(4)]
        for params in requests:
            self.pool.fetch([params])

        results = self.pool.fetch(requests)

        self.assertEqual(len({result['d1'][0] for result in results.values()}), 2)

    def test_an_executor_whose_worker_stopped_while_it_sent_a_result_sees_it(self):
        pool = self._own_pool(started=())
        writer = SimpleNamespace(closed=False)
        writer.close = lambda: setattr(writer, 'closed', True)
        pool._executors[0] = SimpleNamespace(_processes={1: SimpleNamespace(is_alive=lambda: False)}, _broken=False,
                                             _result_queue=SimpleNamespace(_writer=writer))
        self.addCleanup(pool._executors.pop, 0, None)

        with patch.object(access_pool.time, 'monotonic', side_effect=[100.0, 101.0, 100.0 + access_pool._STUCK_AFTER_S]):
            pool._release_stuck_executors()
            pool._release_stuck_executors()
            self.assertFalse(writer.closed)
            pool._release_stuck_executors()

        self.assertTrue(writer.closed)

    def test_new_requests_read_one_at_a_time_take_turns_between_the_workers(self):
        # Each worker keeps its share of the cache of the data source (see _share_cache).
        pids = set()
        for n in range(4):
            params = _params('slow-pid', end=T1 + 300 + n)
            pids.add(self.pool.fetch([params])[_key(params)]['d1'][0])

        self.assertEqual(len(pids), 2)

    def test_a_request_read_before_goes_back_to_its_worker(self):
        first, second = _params('slow-pid', end=T1 + 50), _params('slow-pid', end=T1 + 51)
        pids = self.pool.fetch([first, second])

        again = self.pool.fetch([second])

        self.assertNotEqual(pids[_key(first)]['d1'][0], pids[_key(second)]['d1'][0])
        self.assertEqual(again[_key(second)]['d1'][0], pids[_key(second)]['d1'][0])

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
        reply, stall = self._in_thread(lambda: self._call('gil'))

        pid, held, start = reply.ydata
        self.assertNotEqual(pid, os.getpid())
        self.assertEqual((reply.xunit, reply.yunit, start), ('ns', 'A', 5.0))
        np.testing.assert_array_equal(reply.xdata, T0 + np.arange(3))
        self.assertLess(stall, held / 2)

    def test_the_same_read_in_a_thread_of_this_process_stops_the_gui_thread(self):
        # What the worker processes spare the GUI thread: the read keeps the GIL.
        reply, stall = self._in_thread(lambda: _WorkerDataAccess().get_archive_window('uda', varname='gil', tsS='5'))

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
        # The executors count a request out after they hand its reply over.
        deadline = time.monotonic() + 5
        while any(self.pool._loads.values()) and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertEqual(set(self.pool._loads.values()), {0})

    def test_a_call_whose_worker_stops_is_made_once_more(self):
        marker = os.path.join(tempfile.mkdtemp(), 'stopped')
        self.addCleanup(os.rmdir, os.path.dirname(marker))
        self.addCleanup(os.remove, marker)
        pool = self._own_pool(started=('uda',))

        reply, _ = self._in_thread(lambda: self._call('crash-once', pool, marker=marker))
        error, _ = self._in_thread(lambda: self._call('crash', pool))

        self.assertTrue(os.path.exists(marker))
        self.assertEqual(reply.ydata[2], 5.0)
        self.assertIsInstance(error, DataAccessError)
        self.assertEqual(str(error), access_pool._STOPPED)

    def test_a_method_that_fails_raises_its_message(self):
        with self.assertRaisesRegex(DataAccessError, "no archive for fail"):
            self._call('fail')

    def test_a_call_still_waiting_when_the_pool_shuts_down_ends(self):
        pool = _workers_started(AccessPool(1, data_access_factory=_worker_data_access), 'uda')
        # The call reads for 30 s.
        QTimer.singleShot(2000, pool.shutdown)

        started = time.perf_counter()
        error, _ = self._in_thread(lambda: self._call('stall', pool))

        self.assertLess(time.perf_counter() - started, 15)
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
        QTimer.singleShot(2000, pool.shutdown)
        deadline = time.monotonic() + 20
        while any(thread.is_alive() for thread in threads) and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.05)

        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual([str(outcome) for outcome in outcomes], [access_pool._STOPPED] * 8)

    def test_stopping_an_executor_ends_the_pipe_its_manager_thread_reads(self):
        executor = ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context('spawn'))
        executor.submit(os.getpid).result(timeout=120)
        writer = executor._result_queue._writer

        access_pool._stop(executor)

        self.assertTrue(writer.closed)

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


class AppDataAccessTests(unittest.TestCase):
    """The data access a worker sets up, as the application's: for the data source types it reads."""

    def _set_up(self, initialize):
        with patch.object(access_pool, '_worker_source_types', frozenset({'IMAS'})), \
                patch.object(AppDataAccess, 'initialize', staticmethod(initialize)):
            access_pool.app_data_access()

    def test_only_the_data_sources_of_the_types_the_worker_reads_are_set_up(self):
        asked = []

        def initialize(config_file=None, source_types=None):
            asked.append(source_types)
            return True

        self._set_up(initialize)

        self.assertEqual(asked, [frozenset({'IMAS'})])

    def test_an_iplotdataaccess_that_sets_up_every_type_is_asked_for_all(self):
        asked = []

        def initialize(config_file=None):
            asked.append(config_file)
            return True

        self._set_up(initialize)

        self.assertEqual(asked, [None])

    def test_the_data_sources_the_application_could_not_connect_to_are_left_unconnected(self):
        asked = []

        def initialize(config_file=None, source_types=None, leave_unconnected=()):
            asked.append((source_types, leave_unconnected))
            return True

        with patch.object(access_pool, '_worker_leave_unconnected', frozenset({'down'})):
            self._set_up(initialize)

        self.assertEqual(asked, [(frozenset({'IMAS'}), frozenset({'down'}))])

    def test_a_worker_whose_data_sources_are_all_left_unconnected_reports_none_missing(self):
        with patch.object(access_pool, '_worker_leave_unconnected', frozenset({'down'})), \
                patch.object(AppDataAccess, 'da', SimpleNamespace(unconnected={'down'})), \
                patch.object(access_pool.logger, 'error') as error:
            self._set_up(lambda config_file=None, source_types=None, leave_unconnected=(): False)

        error.assert_not_called()

    def test_a_request_to_a_data_source_left_unconnected_does_not_set_data_access_up_again(self):
        epoch = access_pool._worker_cache_epoch
        with patch.object(AccessHelper, 'da', SimpleNamespace(get_connected_data_source_names=lambda: ['uda'])), \
                patch.object(access_pool, '_worker_leave_unconnected', frozenset({'down'})), \
                patch.object(access_pool, '_worker_reconnected', set()), \
                patch.object(access_pool, '_set_up_data_access') as set_up:
            access_pool._data_access('down', epoch)
            left_unconnected = set_up.call_count
            # One the application connected to, but the worker could not.
            access_pool._data_access('lost', epoch)

        self.assertEqual(left_unconnected, 0)
        self.assertEqual(set_up.call_count, 1)

    def test_the_single_worker_reads_no_type_when_every_data_source_is_parallel(self):
        with patch.object(AccessHelper, 'da', SimpleNamespace(ds_list={'uda': SimpleNamespace(source_type='CODAC_UDA')})):
            self.assertEqual(AccessPool._serial_source_types(), frozenset())
        with patch.object(AccessHelper, 'da', SimpleNamespace()):
            self.assertIsNone(AccessPool._serial_source_types())

    def test_a_worker_of_no_type_reports_no_missing_data_sources(self):
        with patch.object(access_pool, '_worker_source_types', frozenset()), \
                patch.object(AppDataAccess, 'initialize', staticmethod(lambda config_file=None, source_types=None: False)), \
                patch.object(access_pool.logger, 'error') as error:
            access_pool.app_data_access()

        error.assert_not_called()

    def test_a_cache_keeps_its_share_when_data_access_is_set_up_again(self):
        data_access = SimpleNamespace(ds_list={'uda': SimpleNamespace(access_cache=_Cache(300))})

        access_pool._share_cache(data_access, 2)
        access_pool._share_cache(data_access, 2)

        self.assertEqual(data_access.ds_list['uda'].access_cache.maxsize, 150)


if __name__ == '__main__':
    unittest.main()
