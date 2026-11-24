import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from capture import Collector
from options import InvalidOptions, load, split_capture_schedule, validate
from service import run_service


class CaptureIntervalTests(unittest.TestCase):
    def test_existing_intervals_and_new_install_default(self):
        for previous, expected in [(6, 10), (9, 10), (10, 10), (15, 15), (30, 30), (3600, 3600)]:
            with self.subTest(previous=previous):
                validated = validate({'interval_seconds': previous})
                effective, source = split_capture_schedule(validated)
                self.assertEqual(effective, expected)
                self.assertEqual(source, validated)
        self.assertEqual(split_capture_schedule(validate({}))[0], 30)

    def test_explicit_interval_changes_only_the_schedule(self):
        policy = {'normal_interval_seconds': 6, 'urgent_interval_seconds': 6,
                  'full_refresh_seconds': 60, 'phase_probe_budget': 1, 'uncertainty_probe_width': .4}
        old = {'interval_seconds': 6, 'recognition_mode': 'EVENT_LAST_TWO', 'event_selection_policy': policy}
        for seconds in (10, 11, 20, 30, 3600):
            with self.subTest(seconds=seconds):
                effective, source = split_capture_schedule(validate({**old, 'capture_interval_seconds': seconds}))
                self.assertEqual(effective, seconds)
                self.assertEqual(source, validate(old))
        self.assertEqual(split_capture_schedule(validate({'interval_seconds': 30, 'capture_interval_seconds': 10}))[0], 10)

    def test_invalid_values_identify_the_photo_interval(self):
        for value in (True, 9, 3601, '10', 10.0, None):
            with self.subTest(value=value), self.assertRaises(InvalidOptions) as caught:
                validate({'capture_interval_seconds': value})
            self.assertEqual(caught.exception.field, 'capture_interval_seconds')

    def test_service_configures_real_collector_from_saved_options(self):
        actual = []
        def inspect_runtime(runtime):
            try:
                collector, = [worker for worker in runtime.workers if isinstance(worker, Collector)]
                actual.append(collector.interval)
            finally:
                runtime.server.server_close()
            return True

        for override, expected in [(None, 10), (20, 20)]:
            with self.subTest(override=override), tempfile.TemporaryDirectory() as directory:
                document = {'capture_enabled': True, 'camera_url': 'http://localhost', 'interval_seconds': 6}
                if override is not None:
                    document['capture_interval_seconds'] = override
                path = Path(directory) / 'options.json'
                path.write_text(json.dumps(document), encoding='utf-8')
                original = path.read_bytes()
                self.assertEqual(load(directory)[1], {'state': 'ready'})
                with patch('sys.argv', ['service', '--data', directory, '--port', '0']), \
                        patch('lifecycle.ServiceRuntime.run', inspect_runtime):
                    run_service(Mock())
                self.assertEqual(actual[-1], expected)
                self.assertEqual(path.read_bytes(), original)
