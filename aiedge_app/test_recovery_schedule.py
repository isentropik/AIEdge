"""Synthetic regression for duplicate recovery waits; no physical device IO."""
import unittest
from unittest.mock import patch
from test_request_timeout import RequestRecoveryTests
from test_transfer_recovery import TransferRecoveryTests
import capture_recovery as r

class RecoveryScheduleTests(unittest.TestCase):
    def fixture(self, cls=RequestRecoveryTests):
        f=cls();f.setUp();self.addCleanup(f.tearDown);return f
    def accepted(self,f,delay):
        before=f.rows('continuous_capture_outcomes');calls=f.camera.calls
        with patch('capture.time.monotonic',return_value=1000):
            f.worker.once()
        self.assertEqual(f.camera.calls,calls)
        self.assertEqual(f.rows('continuous_capture_outcomes'),before)
        self.assertEqual(f.worker.readiness_retry_delay,0)
        self.assertEqual(f.worker.transfer_not_before,1006)
        self.assertIsNone(f.worker.transfer_attempt)
        self.assertFalse(f.worker.stop.is_set())
    def test_second_timeout_does_not_charge_twelve_seconds_twice(self):
        f=self.fixture();f.camera.results=iter([r.RequestTimeout(),r.RequestTimeout(),True])
        f.worker.once();self.accepted(f,6)
        f.worker.once();self.assertEqual(f.worker.readiness_retry_delay,12)
        self.accepted(f,12)
        self.assertEqual(f.worker.transfer_failures,2)
        f.worker.once();self.assertEqual(f.camera.calls,3)
        self.assertEqual([x[1] for x in f.rows('continuous_capture_outcomes')],['unknown','unknown','committed'])
    def test_eight_failures_keep_next_failure_backoff(self):
        f=self.fixture();f.camera.results=iter([r.RequestTimeout() for _ in range(9)])
        for n in range(8):
            f.worker.once();self.assertEqual(f.worker.readiness_retry_delay,min(60,6*2**min(n,4)))
            self.accepted(f,min(60,6*2**min(n,4)))
        f.worker.once();self.assertEqual(f.worker.readiness_retry_delay,60)
    def test_busy_probes_keep_backoff_until_ready(self):
        f=self.fixture();f.failed();f.camera.ready['state']='busy'
        for _ in range(7):f.worker.once()
        self.assertEqual(f.worker.readiness_retry_delay,60)
        self.assertEqual(f.rows('capture_continuations'),[])
        f.camera.ready['state']='ready';self.accepted(f,60)
    def test_body_timeout_uses_same_corrected_schedule(self):
        f=self.fixture(TransferRecoveryTests);f.failed();f.worker.readiness_retry_delay=12
        self.accepted(f,12)
        self.assertEqual(f.rows('continuous_capture_outcomes')[-1][1],'unknown')
    def test_configured_minimum_interval_is_preserved(self):
        f=self.fixture();f.worker.interval=30;f.failed()
        with patch('capture.time.monotonic',return_value=1000):f.worker.once()
        self.assertEqual(f.worker.transfer_not_before,1030)
        self.assertEqual(f.camera.calls,2)

if __name__=='__main__':unittest.main()
