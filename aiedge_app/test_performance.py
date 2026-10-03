"""Timing privacy, failed-operation accounting and real loopback pipeline."""
import json
import tempfile
import threading
import time
import unittest
import sqlite3
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from capture import Camera, Store
from diagnostics import build
from performance import Timings, WINDOW
from recognition import Recognition
from test_capture import JPEG, headers
from test_recognition import Reader


class FixtureReader(Reader):
    dials = [{'name': 'PRIVATE-DIAL'}]


class PerformanceTests(unittest.TestCase):
    def test_window_outcomes_and_concurrent_snapshot_stay_bounded(self):
        stats = Timings()
        def record():
            for value in range(80):
                stats.record('recognition', value / 1000)
                stats.record('recognition', .001, 'failure')
                json.dumps(stats.snapshot(), allow_nan=False)
        threads = [threading.Thread(target=record) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(5)
            self.assertFalse(thread.is_alive())
        stage = stats.snapshot()['stages']['recognition']
        self.assertEqual(stage['retained_samples'], WINDOW)
        self.assertEqual(stage['counts_since_start']['success'], 320)
        self.assertEqual(stage['counts_since_start']['failure'], 320)
        self.assertGreater(stage['outcomes']['success']['samples'], 0)
        self.assertEqual(sum(row['samples'] for row in stage['outcomes'].values()), WINDOW)
        self.assertEqual(stage['outcomes']['failure']['maximum_seconds'], .001)
        for seconds in (float('nan'), float('inf'), -1, True, 'PRIVATE-PASSWORD', None):
            self.assertFalse(stats.record('capture', seconds))
        for value in ('PRIVATE-CAMERA', [], {}):
            self.assertFalse(stats.record(value, 1))
            self.assertFalse(stats.record('capture', 1, value))
        self.assertNotIn('PRIVATE-', json.dumps(stats.snapshot()))
        self.assertTrue(stats.record('capture', 1e308))
        self.assertTrue(stats.record('capture', 1e308))
        self.assertEqual(stats.snapshot()['stages']['capture']['outcomes']['success']['median_seconds'], 1e308)
        json.dumps(stats.snapshot(), allow_nan=False)

    def test_failures_preserve_exception_and_never_become_success(self):
        values = iter((1, 4, 10, 11))
        stats = Timings(clock=lambda: next(values))
        with self.assertRaisesRegex(ValueError, 'PRIVATE-ERROR'):
            with stats.measure('capture'):
                raise ValueError('PRIVATE-ERROR')
        with stats.measure('capture'):
            pass
        stage = stats.snapshot()['stages']['capture']
        self.assertEqual(stage['outcomes']['success']['median_seconds'], 1)
        self.assertEqual(stage['outcomes']['failure']['median_seconds'], 3)
        self.assertNotIn('PRIVATE-ERROR', json.dumps(stats.snapshot()))

    def test_loopback_headers_download_storage_and_inference_are_separate(self):
        class Fixture(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_POST(self):
                self.rfile.read(int(self.headers['Content-Length']))
                time.sleep(.025)
                self.send_response(200)
                self.send_header('Content-Type', 'image/jpeg')
                self.send_header('Content-Length', str(len(JPEG)))
                for key, value in headers().items():
                    self.send_header(key, value)
                self.end_headers()
                self.wfile.flush()
                time.sleep(.05)
                self.wfile.write(JPEG)
        server = ThreadingHTTPServer(('127.0.0.1', 0), Fixture)
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as directory:
                store = Store(directory)
                camera = Camera(f'http://127.0.0.1:{server.server_port}', token='PRIVATE-TOKEN',
                                performance=store.performance)
                blob, metadata = camera.capture()
                self.assertTrue(store.add(camera.origin, blob, metadata))
                self.assertFalse(store.add(camera.origin, blob, metadata))
                worker = Recognition(store, FixtureReader())
                self.assertTrue(worker.once())
                self.assertFalse(worker.once())
                result = worker.latest()
                report = build(store, recognition=worker)
                stages = report['performance']['stages']
                self.assertGreaterEqual(stages['camera_headers']['outcomes']['success']['minimum_seconds'], .02)
                self.assertGreaterEqual(stages['camera_download']['outcomes']['success']['minimum_seconds'], .04)
                capture = stages['capture']['outcomes']['success']['median_seconds']
                parts = sum(stages[s]['outcomes']['success']['median_seconds'] for s in ('camera_headers', 'camera_download'))
                self.assertGreaterEqual(capture, parts)
                self.assertEqual(stages['storage']['counts_since_start']['success'], 1)
                self.assertEqual(stages['storage']['counts_since_start']['duplicate'], 1)
                self.assertEqual(stages['recognition']['counts_since_start']['success'], 1)
                self.assertEqual(stages['inference_commit']['counts_since_start']['success'], 1)
                self.assertEqual(store.status()['captures'], 1)
                self.assertFalse(result['accuracy_verified'])
                self.assertFalse(result['training_allowed'])
                serialized = json.dumps(report)
                for secret in ('PRIVATE-TOKEN', directory, metadata['X-AIEdge-Frame-Id'], metadata['X-AIEdge-SHA256']):
                    # This fixture's frame-id is just "1", also used as a count.
                    if secret != '1':
                        self.assertNotIn(secret, serialized)
                files = sorted(path.name for path in Path(directory).iterdir())
                self.assertFalse(any('performance' in name or 'timing' in name for name in files))
                self.assertEqual(Store(directory).performance.snapshot()['state'], 'not_measured')
        finally:
            server.shutdown()
            thread.join(5)
            server.server_close()

    def test_reference_failure_rejection_and_failed_commit_are_not_fast_success(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            camera = Camera('http://127.0.0.1', performance=store.performance)
            with patch.object(camera.opener, 'open', side_effect=TimeoutError('PRIVATE-ERROR')):
                with self.assertRaisesRegex(ValueError, '^camera_timeout$'):
                    camera.capture(reference=True)
            self.assertNotIn('capture', store.performance.snapshot()['stages'])
            self.assertEqual(store.performance.snapshot()['stages']['reference_capture']['counts_since_start']['failure'], 1)
            invalid = headers()
            invalid.replace_header('X-AIEdge-SHA256', '0' * 64)
            with self.assertRaisesRegex(ValueError, 'image_hash_mismatch'):
                store.add('PRIVATE-CAMERA', JPEG, invalid)
            self.assertEqual(store.performance.snapshot()['stages']['storage']['counts_since_start']['failure'], 1)
            self.assertEqual(store.status()['captures'], 0)
            store.add('PRIVATE-CAMERA', JPEG, headers())
            reader = FixtureReader()
            def fail(blob):
                raise ValueError('alignment_rejected')
            reader.read_jpeg = fail
            worker = Recognition(store, reader)
            worker.once()
            self.assertEqual(worker.latest()['state'], 'rejected')
            stage = store.performance.snapshot()['stages']['recognition']
            self.assertEqual(stage['counts_since_start']['rejected'], 1)
            self.assertEqual(stage['counts_since_start']['success'], 0)
            self.assertEqual(store.performance.snapshot()['stages']['read_and_infer']['counts_since_start']['failure'], 1)
            self.assertNotIn('PRIVATE-', json.dumps(build(store, recognition=worker)))
            with patch('capture.sync_directory', side_effect=OSError('PRIVATE-DISK')):
                with self.assertRaises(OSError):
                    store.add('PRIVATE-CAMERA', JPEG, headers('2'))
            self.assertEqual(store.performance.snapshot()['stages']['storage']['counts_since_start']['failure'], 2)
            self.assertEqual(store.status()['captures'], 1)

    def test_failed_inference_commit_is_reported_and_result_stays_pending(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            store.add('camera', JPEG, headers())
            worker = Recognition(store, FixtureReader())
            connect = store.connect
            class Connection:
                def __init__(self, db):
                    self.db = db
                def execute(self, query, *args):
                    if query.startswith('INSERT INTO inference'):
                        raise sqlite3.OperationalError('PRIVATE-DISK')
                    return self.db.execute(query, *args)
            @contextmanager
            def failing_connect():
                with connect() as db:
                    yield Connection(db)
            with patch.object(store, 'connect', failing_connect):
                with self.assertRaises(sqlite3.OperationalError):
                    worker.once()
            self.assertEqual(worker.latest()['state'], 'pending')
            self.assertEqual(store.image(headers()['X-AIEdge-SHA256']), JPEG)
            stages = store.performance.snapshot()['stages']
            self.assertEqual(stages['recognition']['counts_since_start']['failure'], 1)
            self.assertEqual(stages['inference_commit']['counts_since_start']['failure'], 1)
            self.assertEqual(stages['recognition']['counts_since_start']['success'], 0)
            self.assertNotIn('PRIVATE-', json.dumps(build(store, recognition=worker)))
            self.assertTrue(worker.once())
            self.assertEqual(worker.latest()['state'], 'estimated')
            self.assertEqual(store.performance.snapshot()['stages']['recognition']['counts_since_start']['success'], 1)

    def test_camera_readiness_rejection_stops_before_capture_and_storage(self):
        from capture import Collector
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            camera = Camera('http://127.0.0.1', performance=store.performance)
            with patch.object(camera, 'readiness', return_value={'state': 'clock_unsynchronized'}), \
                 patch.object(camera, 'capture', side_effect=AssertionError('No photo authorized')):
                Collector(store, camera, 30).once()
            stages = store.performance.snapshot()['stages']
            self.assertIn('camera_readiness', stages)
            self.assertNotIn('capture', stages)
            self.assertNotIn('storage', stages)
            self.assertEqual(store.status()['captures'], 0)


if __name__ == '__main__':
    unittest.main()
