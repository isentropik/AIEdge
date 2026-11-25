import tempfile
import unittest

from capture import Collector, Store
from test_capture_continuation import Camera, configure, request


class BusyGapTest(unittest.TestCase):
    def setUp(self):
        self.store = Store(self.enterContext(tempfile.TemporaryDirectory()))
        self.camera = Camera([True, ValueError('camera_busy'), True])
        self.worker = configure(Collector(self.store, self.camera, 10))
        self.worker.once()
        self.worker.once()
        self.assertEqual(self.worker.recovery_status()['state'], 'held')
        self.action = request(self.worker)

    def test_review_then_resume_without_replaying_the_unknown_attempt(self):
        self.assertEqual(self.camera.calls, 2)
        result = self.worker.continue_after_gap(self.action)
        self.assertIsNone(result['gap_delta'])
        self.assertEqual(self.camera.calls, 2)
        self.worker.once()
        with self.store.connect() as db:
            rows = db.execute('SELECT attempt_id,outcome,event_id,error FROM continuous_capture_outcomes ORDER BY rowid').fetchall()
        self.assertEqual(rows[1], (self.action['attempt_id'], 'unknown', None, 'camera_busy'))
        self.assertEqual(rows[2][1:3], ('committed', 2))
        self.assertNotEqual(rows[1][0], rows[2][0])

    def test_camera_must_be_ready(self):
        self.camera.ready['state'] = 'busy'
        with self.assertRaises(ValueError):
            self.worker.continue_after_gap(self.action)
        self.assertEqual(self.worker.recovery_status()['state'], 'held')
        self.assertEqual(self.camera.calls, 2)

    def test_later_failure_blocks_acceptance(self):
        self.store.fail('camera_connection_failed')
        with self.assertRaisesRegex(ValueError, 'continuation_later_failure'):
            self.worker.continue_after_gap(self.action)
        self.assertEqual(self.camera.calls, 2)
