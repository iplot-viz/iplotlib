"""Tests for AccessPool: data access requests run in worker processes, results come back
by request key, and the GUI thread keeps running while it waits."""

import logging
import os
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
from PySide6.QtCore import QTimer

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
        values = {'slow-pid': [os.getpid()], 'clears': [_cache_clears]}.get(name, [1.0, 2.0])
        return SimpleNamespace(errcode=0, errdesc='', xdata=T0 + np.arange(len(values)),
                               ydata=np.asarray(values, dtype=float), xunit='ns', yunit='A', resolved_pulse=None)

    def clear_cache(self):
        global _cache_clears
        _cache_clears += 1


def _worker_data_access():
    return _WorkerDataAccess()


def _broken_data_access():
    raise RuntimeError("no configuration")


class _ParentDataAccess:
    """What the pool looks up in this process: the type of each data source."""

    ds_list = {'uda': SimpleNamespace(source_type='CODAC_UDA'), 'imas': SimpleNamespace(source_type='IMAS')}

    def get_data_source(self, name):
        return self.ds_list.get(name)


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
        # The log file the workers' records are written to.
        cls.log = _CapturingHandler()
        with patch.object(setupLogger.FileHandlerIplot, 'fhandler', cls.log):
            cls.pool = AccessPool(2, data_access_factory=_worker_data_access)

    @classmethod
    def tearDownClass(cls):
        cls.pool.shutdown()
        AccessHelper.da = cls._da

    def _own_pool(self, factory=_worker_data_access):
        pool = AccessPool(2, data_access_factory=factory)
        self.addCleanup(pool.shutdown)
        return pool

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

    def test_worker_log_records_reach_this_process(self):
        def from_a_worker():
            return [record for record in self.log.records
                    if record.getMessage() == "record from a worker" and record.process != os.getpid()]

        self.pool.fetch([_params('log')])
        deadline = time.monotonic() + 5
        while not from_a_worker() and time.monotonic() < deadline:
            time.sleep(0.05)

        self.assertTrue(from_a_worker())

    def test_a_worker_that_stops_fails_only_its_own_request(self):
        pool = self._own_pool()
        crash, plain = _params('crash'), _params('plain')

        results = pool.fetch([crash, plain])

        self.assertIsInstance(results[_key(crash)], DataAccessError)
        self.assertIn("stopped", str(results[_key(crash)]))
        np.testing.assert_array_equal(results[_key(plain)]['d1'], [1.0, 2.0])
        later = pool.fetch([_params('plain', end=T1 + 40)])
        self.assertEqual(len(later), 1)

    def test_a_worker_without_data_access_says_so(self):
        pool = self._own_pool(factory=_broken_data_access)

        results = pool.fetch([_params('plain')])

        error = results[_key(_params('plain'))]
        self.assertIsInstance(error, DataAccessError)
        self.assertIn("could not be set up", str(error))

    def test_shutdown_does_not_wait_for_requests_in_progress(self):
        pool = AccessPool(1, data_access_factory=_worker_data_access)
        stall = _params('stall')
        # The worker takes a few seconds to start; the request then reads for 30 s.
        QTimer.singleShot(8000, pool.shutdown)

        started = time.perf_counter()
        results = pool.fetch([stall])

        self.assertLess(time.perf_counter() - started, 15)
        self.assertIsInstance(results[_key(stall)], Exception)
        with self.assertRaises(RuntimeError):
            pool.fetch([_params('plain')])

    def test_start_launches_the_workers_of_the_configured_sources(self):
        pool = self._own_pool()

        pool.start()

        self.assertEqual(set(pool._executors), {0, 1, access_pool._SERIAL_SLOT})

    def test_a_request_read_before_goes_back_to_its_worker(self):
        first, second = _params('slow-pid', end=T1 + 50), _params('slow-pid', end=T1 + 51)
        pids = self.pool.fetch([first, second])

        again = self.pool.fetch([second])

        self.assertNotEqual(pids[_key(first)]['d1'][0], pids[_key(second)]['d1'][0])
        self.assertEqual(again[_key(second)]['d1'][0], pids[_key(second)]['d1'][0])


if __name__ == '__main__':
    unittest.main()
