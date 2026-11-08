"""Restart recovery uses synthetic camera/ledger fixtures only."""
import unittest
from unittest.mock import patch
from capture import Collector, Store
from camera_status import ReadinessTransportError
from test_capture_continuation import configure
import test_transfer_recovery as fixtures
import capture_recovery as r


class TimeoutRestartTests(unittest.TestCase):
    setUp = fixtures.TransferRecoveryTests.setUp
    tearDown = fixtures.TransferRecoveryTests.tearDown
    rows = fixtures.TransferRecoveryTests.rows
    failed = fixtures.TransferRecoveryTests.failed

    def restart(self):
        return configure(Collector(Store(self.temp.name), self.camera, 6, recovery_floor=2))

    def test_restart_preserves_all_evidence_and_accepts_once(self):
        self.failed()
        tables = ('frames', 'capture_events', 'capture_clocks', 'failures',
                  'capture_failure_boundaries', 'continuous_capture_attempts',
                  'continuous_capture_outcomes', 'capture_transfer_timeouts')
        before = {t: self.rows(t) for t in tables}
        worker = self.restart()
        self.assertFalse(worker.stop.is_set())
        self.assertEqual(worker.transfer_attempt, self.worker.transfer_attempt)
        worker.once()  # readiness and durable acceptance only
        self.assertEqual(self.camera.calls, 2)
        for table, rows in before.items():
            self.assertEqual(self.rows(table), rows)
        worker = self.restart()  # crash after acceptance, before next capture
        worker.once()
        self.assertEqual(self.camera.calls, 3)
        self.assertEqual(len(self.rows('capture_continuations')), 1)
        with self.store.connect() as db:
            self.assertTrue(r.boundary(db, 2))
        self.assertEqual(self.rows('continuous_capture_outcomes')[1][1:4],
                         ('unknown', None, 'camera_timeout'))

    def test_restart_busy_then_outage_then_ready_never_replays(self):
        self.failed()
        worker = self.restart()
        self.camera.ready['state'] = 'busy'
        for _ in range(8): worker.once()
        self.assertEqual(worker.readiness_retry_delay, 60)
        with patch.object(self.camera, 'readiness', side_effect=ReadinessTransportError()):
            worker.once()
        self.assertEqual(self.camera.calls, 2)
        self.assertEqual(self.rows('capture_continuations'), [])
        worker = self.restart()
        self.camera.ready['state'] = 'ready'
        worker.once()
        self.assertEqual(self.camera.calls, 2)
        worker.once()
        self.assertEqual(self.camera.calls, 3)

    def test_restart_context_change_holds_before_probe(self):
        self.failed()
        worker = self.restart()
        worker.continuation_context = lambda: {'changed': True}
        probes = self.camera.probes
        worker.once()
        self.assertTrue(worker.stop.is_set())
        self.assertEqual(self.camera.probes, probes)
        self.assertEqual(self.rows('capture_continuations'), [])

    def test_restart_later_hard_fault_is_not_cleared(self):
        self.failed()
        self.store.fail('camera_authentication_failed')
        worker = self.restart()
        probes = self.camera.probes
        worker.once()
        self.assertTrue(worker.stop.is_set())
        self.assertEqual(self.camera.probes, probes)

    def test_restart_pending_attempt_is_not_cleared(self):
        self.failed()
        with self.store.connect() as db:
            db.execute('INSERT INTO continuous_capture_attempts VALUES(?,?,?,?)',
                       ('b'*32, 1, 1, '2026-01-01T00:00:00+00:00'))
        worker = self.restart()
        worker.once()
        self.assertTrue(worker.stop.is_set())
        self.assertEqual(self.camera.calls, 2)

    def test_restart_conflicting_evidence_is_not_accepted(self):
        self.failed()
        with self.store.connect() as db:
            row = db.execute('SELECT attempt_id,binding_sha256,context_sha256 FROM capture_transfer_timeouts').fetchone()
            db.execute('INSERT INTO capture_request_timeouts VALUES(?,?,?)', row)
        worker = self.restart()
        worker.once()
        self.assertTrue(worker.stop.is_set())
        self.assertEqual(self.rows('capture_continuations'), [])

    def test_restart_tampered_binding_is_not_accepted(self):
        self.failed()
        with self.store.connect() as db:
            db.execute("UPDATE continuous_capture_outcomes SET finished_at='2020-01-01T00:00:00+00:00' WHERE outcome='unknown'")
        worker = self.restart()
        self.assertTrue(worker.stop.is_set())
        self.assertEqual(self.rows('capture_continuations'), [])

    def test_shutdown_after_restart_does_not_probe_or_capture(self):
        self.failed()
        worker = self.restart()
        probes = self.camera.probes
        worker.request_stop()
        worker.once()
        self.assertEqual(self.camera.probes, probes)
        self.assertEqual(self.camera.calls, 2)


if __name__ == '__main__': unittest.main()
