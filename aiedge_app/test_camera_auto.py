"""Loopback camera substitute: exercises transport/persistence, not hardware."""
from datetime import datetime, timedelta, timezone
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from auto_capture import Choice
from camera_auto import CameraAuto, digest
from camera_image import CameraImage, Config as ImageConfig
from camera_lighting import CameraLighting, Config as LightingConfig
from capture import Camera, Store, Collector
from test_auto_capture import image
from test_camera_image import CONFIG as IMAGE_CONFIG, CAPS as IMAGE_CAPS
from test_camera_lighting import CONFIG as LIGHT_CONFIG, CAPS as LIGHT_CAPS

CONFIG = IMAGE_CONFIG.replace(b'[Network]', LIGHT_CONFIG[LIGHT_CONFIG.index(b'[GPIO]'):LIGHT_CONFIG.index(b'[Network]')] + b'[Network]')
AUTO_CAPS = dict(version=1, mode='remote-camera', model='OV2640', path='/api/v1/capture/temporary',
    method='POST', frame_size=[640, 480], temporary_controls=True, restore_before_response=True,
    sd_writes=0, max_capture_seconds=20)


class Reference:
    def __init__(self):
        self.blobs = []
    def add_reference(self, blob):
        self.blobs.append(blob)
        return digest(blob)


class AutoTransactions(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.raw, self.calls, self.requests, self.fail = CONFIG, [], [], None
        self.probes = 0
        self.journals = []
        self.render = lambda choice: image()
        self.utc = datetime(2026, 9, 22, tzinfo=timezone.utc)
        self.reference = Reference()
        owner = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def answer(self, blob, status=200, kind='application/json', headers=None):
                self.send_response(status)
                self.send_header('Content-Type', kind)
                self.send_header('Content-Length', str(len(blob) + (100 if owner.fail == 'truncated' and kind == 'image/jpeg' else 0)))
                for key, value in (headers or {}).items():
                    self.send_header(key, value)
                if owner.fail == 'duplicate' and kind == 'image/jpeg':
                    self.send_header('X-AIEdge-Settings-Restored', 'true')
                self.end_headers()
                self.wfile.write(blob)
            def do_GET(self):
                owner.calls.append(('GET', self.path))
                value = {'/temporary-capture-capabilities': AUTO_CAPS,
                         '/image-controls-capabilities': IMAGE_CAPS, '/lighting-capabilities': LIGHT_CAPS}.get(self.path)
                if self.path == '/temporary-capture-capabilities' and owner.fail == 'unsupported':
                    self.answer(b'SECRET-private', 404)
                elif self.path == '/fileserver/config/config.ini':
                    self.answer(owner.raw, kind='text/plain')
                elif value is not None:
                    self.answer(json.dumps(value).encode())
                else: self.answer(b'SECRET-private', 404)
            def do_POST(self):
                owner.calls.append(('POST', self.path))
                body = self.rfile.read(int(self.headers['Content-Length']))
                owner.requests.append((self.path, body, self.headers.get('Authorization')))
                if self.path == '/api/v1/capture/temporary':
                    owner.probes += 1
                    owner.journals.append(json.loads(owner.client.path.read_text()))
                    request = json.loads(body)
                    choice = Choice(request['intensity'], request['controls']['exposure'])
                    blob = owner.render(choice)
                    headers = owner.headers(blob, request['controls'], temporary=True)
                    headers.update({'X-AIEdge-Temporary-Request-SHA256': digest(body),
                        'X-AIEdge-Saved-Revision': digest(owner.raw), 'X-AIEdge-Restored-Revision': digest(owner.raw),
                        'X-AIEdge-Settings-Restored': 'true', 'X-AIEdge-Light-Off': 'true', 'X-AIEdge-Temporary-SD-Writes': '0'})
                    for failure, key, value in (
                        ('request-hash', 'X-AIEdge-Temporary-Request-SHA256', '0'*64),
                        ('revision', 'X-AIEdge-Saved-Revision', '0'*64),
                        ('restore', 'X-AIEdge-Settings-Restored', 'false'),
                        ('light', 'X-AIEdge-Light-Off', 'false'),
                        ('sd', 'X-AIEdge-Temporary-SD-Writes', '1'),
                        ('orientation', 'X-AIEdge-Image-Orientation', '3'),
                        ('image-hash', 'X-AIEdge-SHA256', '0'*64)):
                        if owner.fail == failure: headers[key] = value
                    if owner.fail == 'lost':
                        self.connection.shutdown(2); self.connection.close(); return
                    self.answer(blob, kind='image/jpeg', headers=headers)
                elif self.path == '/config-save':
                    owner.journals.append(json.loads(owner.client.path.read_text()))
                    change = json.loads(body)
                    if change['before'].encode() != owner.raw:
                        self.answer(b'SECRET-private', 409); return
                    if owner.fail != 'save-before': owner.raw = change['after'].encode()
                    self.answer(b'{"saved":false}' if owner.fail in ('save', 'save-before') else b'{"saved":true}')
                elif self.path in ('/apply-lighting', '/apply-image-controls'):
                    if body != owner.raw: self.answer(b'SECRET-private', 409); return
                    if owner.fail == self.path: self.answer(b'SECRET-private', 500); return
                    ack = dict(saved=True, active=True, restart_required=False, active_revision=digest(body))
                    if owner.fail == 'bad-ack' and self.path == '/apply-image-controls': ack['active_revision'] = '0'*64
                    if owner.fail == 'changed-after' and self.path == '/apply-image-controls': owner.raw += b'# another session\n'
                    self.answer(json.dumps(ack).encode())
                elif self.path == '/api/v1/capture':
                    if owner.fail == 'reference': self.answer(b'SECRET-private', 500); return
                    blob = image(level=70 if owner.fail == 'reference-dark' else 200)
                    self.answer(blob, kind='image/jpeg', headers=owner.headers(blob, ImageConfig(owner.raw, 'OV2640').controls()))
                else: self.answer(b'SECRET-private', 404)
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.start()
        self.camera = Camera(f'http://127.0.0.1:{self.server.server_port}', username='device', password='SECRET-private')
        self.camera.readiness = lambda: {'state': 'ready'}
        self.lighting = CameraLighting(self.camera, self.root)
        self.image_controls = CameraImage(self.camera, self.root)
        self.camera.lighting, self.camera.image_controls = self.lighting, self.image_controls
        self.client = CameraAuto(self.camera, self.root, self.lighting, self.image_controls)
        self.camera.auto_control = self.client

    def headers(self, blob, controls, temporary=False):
        count = self.probes if temporary else 100
        return {'X-AIEdge-Frame-Id': ('probe-' if temporary else 'normal-') + str(count),
                'X-AIEdge-SHA256': digest(blob), 'X-AIEdge-Captured-At': (self.utc + timedelta(seconds=count)).isoformat(),
                'X-AIEdge-Clock-Id': 'temporary-clock' if temporary else 'normal-clock',
                'X-AIEdge-Capture-Monotonic-Us': str(count * 1000000),
                'X-AIEdge-Image-Orientation': str(int(controls['mirror']) + 2 * int(controls['flip']))}

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(); self.directory.cleanup()

    def posts(self): return [path for method, path in self.calls if method == 'POST']
    def picture(self, orientation=0, **kwargs):
        return self.client.picture(digest(CONFIG), orientation, self.reference, **kwargs)
    def restart(self):
        return CameraAuto(self.camera, self.root, self.lighting, self.image_controls)

    def test_success_saves_once_after_probes_then_normal_reference(self):
        result = self.picture()
        self.assertEqual(self.posts(), ['/api/v1/capture/temporary']*2 + ['/config-save', '/apply-lighting', '/apply-image-controls', '/api/v1/capture'])
        self.assertEqual(LightingConfig(self.raw).lighting()['channels'], [0, 0, 0, 255])
        self.assertEqual(LightingConfig(self.raw).lighting()['intensity'], 25)
        controls = ImageConfig(self.raw, 'OV2640').controls()
        self.assertEqual(controls, Choice(25, 300).controls(0))
        self.assertTrue(result['auto_settings']['automatic'])  # Independent of sensor AEC/AGC.
        self.assertFalse(controls['auto_exposure']); self.assertFalse(controls['auto_gain'])
        self.assertIn(b'Password = SECRET-private\r\n', self.raw)
        self.assertIn(b'FutureField = keep me\r\n', self.raw)
        self.assertEqual(len(self.reference.blobs), 1)
        self.assertNotEqual(digest(self.reference.blobs[0]), result['auto_result']['selected']['sha256'])
        self.assertFalse(self.client.status()['needs_attention'])
        self.assertFalse(result['auto_result']['accuracy_verified'])
        self.assertFalse(result['auto_result']['physical_behavior_verified'])
        self.assertFalse(result['auto_result']['training_allowed'])
        self.assertNotIn('SECRET', json.dumps(result))

    def test_every_temporary_request_has_matching_durable_intent_and_auth(self):
        self.picture()
        for journal, (_, body, auth) in zip(self.journals[:2], self.requests[:2]):
            self.assertEqual(journal['request_sha256'], digest(body))
            self.assertEqual(journal['request_id'], json.loads(body)['request_id'])
            self.assertEqual(journal['before'], digest(CONFIG)); self.assertEqual(journal['after'], digest(CONFIG))
            self.assertEqual(journal['stage'], 'probe'); self.assertTrue(auth.startswith('Basic '))
            self.assertNotIn('SECRET', json.dumps(journal))
        self.assertEqual(self.journals[-1]['stage'], 'commit')

    def test_trial_hashes_and_metadata_are_separate_from_capture_ledger(self):
        self.picture()
        run = next(self.client.trials.iterdir())
        metadata = [json.loads((run / f'{n}.json').read_text()) for n in (1, 2)]
        for item in metadata:
            self.assertTrue(item['restoration_verified'])
            self.assertEqual(digest((run / (item['raw_sha256'] + '.jpg')).read_bytes()), item['raw_sha256'])
            self.assertFalse(item['training_allowed']); self.assertFalse(item['accuracy_verified'])
        store = Store(self.root)
        self.assertEqual(store.status()['captures'], 0)
        self.assertEqual(store.status()['unique_images'], 0)
        self.assertEqual(metadata[0]['sha256'], metadata[1]['sha256']) # Duplicate content is not accuracy evidence.

    def test_mode_persists_without_network_or_clearing_pending(self):
        self.client.set_mode(False)
        self.assertFalse(self.restart().status()['automatic']); self.assertEqual(self.calls, [])
        self.fail = 'restore'
        with self.assertRaises(ValueError): self.picture()
        self.client.set_mode(True)
        self.assertTrue(self.restart().status()['needs_attention'])

    def test_unsupported_firmware_fails_before_any_probe(self):
        self.fail = 'unsupported'
        with self.assertRaisesRegex(ValueError, 'auto_contract_unsupported'): self.picture()
        self.assertEqual(self.posts(), []); self.assertEqual(len(self.reference.blobs), 0)
        self.assertFalse(self.client.status()['needs_attention'])

    def test_stale_revision_fails_before_any_probe(self):
        self.raw += b'# changed\n'
        with self.assertRaisesRegex(ValueError, 'auto_config_conflict'): self.picture()
        self.assertEqual(self.posts(), [])

    def test_lost_reply_blocks_captures_and_survives_restart(self):
        self.fail = 'lost'
        with self.assertRaises(ValueError): self.picture()
        self.assertEqual(self.posts(), ['/api/v1/capture/temporary'])
        self.assertTrue(self.restart().status()['needs_attention'])
        with self.assertRaisesRegex(ValueError, 'auto_restore_unverified'): self.camera.require_capture()
        with self.assertRaisesRegex(ValueError, 'auto_restore_unverified'): self.picture()
        self.assertEqual(self.probes, 1)

    def test_rejected_receipts_and_images_are_retained_and_never_retried(self):
        for fail in ('request-hash', 'revision', 'restore', 'light', 'sd', 'orientation', 'image-hash', 'duplicate', 'truncated'):
            with self.subTest(fail=fail):
                self.fail = fail
                with self.assertRaises(ValueError): self.picture()
                self.assertTrue(self.client.status()['needs_attention'])
                self.assertTrue(self.restart().status()['needs_attention'])
                folder = max(self.client.trials.iterdir(), key=lambda p: p.stat().st_mtime_ns)
                rejected = json.loads((folder / '1-failed.json').read_text())
                self.assertFalse(rejected['restoration_verified'])
                self.assertEqual(digest((folder / (rejected['raw_sha256']+'.jpg')).read_bytes()), rejected['raw_sha256'])
                self.fail = None
                self.client.recover(digest(self.raw))
        self.assertEqual(self.probes, 9)
        self.assertEqual(len(self.reference.blobs), 0)

    def test_read_only_load_or_ping_does_not_clear_uncertainty(self):
        self.fail = 'restore'
        with self.assertRaises(ValueError): self.picture()
        self.image_controls.load()
        self.camera.readiness()
        self.assertTrue(self.client.status()['needs_attention'])

    def test_explicit_recovery_activates_saved_settings_without_resave_or_photo(self):
        self.fail = 'restore'
        with self.assertRaises(ValueError): self.picture()
        self.fail = None; self.calls = []
        result = self.restart().recover(digest(CONFIG))
        self.assertEqual(self.posts(), ['/apply-lighting', '/apply-image-controls'])
        self.assertFalse(result['auto_settings']['needs_attention'])
        self.assertEqual(self.raw, CONFIG); self.assertEqual(len(self.reference.blobs), 0)

    def test_recovery_rejects_changed_saved_revision_or_different_camera(self):
        self.fail = 'restore'
        with self.assertRaises(ValueError): self.picture()
        self.fail = None; self.calls = []; self.raw += b'# changed\n'
        with self.assertRaisesRegex(ValueError, 'auto_config_conflict'): self.client.recover(digest(self.raw))
        self.assertEqual(self.posts(), [])
        self.camera.origin = 'http://127.0.0.1:1'
        self.assertFalse(self.client.status()['recovery_available'])
        with self.assertRaisesRegex(ValueError, 'auto_recovery_unavailable'): self.client.recover(digest(CONFIG))

    def test_failed_commit_blocks_capture_and_explicit_recovery_handles_old_or_new(self):
        for fail in ('save', 'save-before', '/apply-lighting', '/apply-image-controls', 'bad-ack', 'changed-after'):
            with self.subTest(fail=fail):
                self.raw = CONFIG; self.fail = fail
                with self.assertRaises(ValueError): self.picture()
                self.assertTrue(self.restart().status()['needs_attention'])
                self.assertEqual(len(self.reference.blobs), 0)
                if fail == 'changed-after': self.raw = self.raw.replace(b'# another session\n', b'')
                self.fail = None; self.calls = []
                self.client.recover(digest(self.raw))
                self.assertEqual(self.posts(), ['/apply-lighting', '/apply-image-controls'])

    def test_flip_is_committed_only_at_end_and_requires_new_calibration(self):
        result = self.picture(3)
        for path, body, _ in self.requests:
            if path == '/api/v1/capture/temporary':
                self.assertEqual(json.loads(body)['controls'], Choice(json.loads(body)['intensity'], 300).controls(0))
        self.assertEqual(result['image_orientation'], 3)
        self.assertTrue(self.image_controls.requires_reference())
        with self.assertRaisesRegex(ValueError, 'reference_required'): self.camera.require_capture()
        self.camera.require_capture(reference=True)
        self.image_controls.calibration_saved(result['reference_sha256'])
        self.assertFalse(self.image_controls.requires_reference())

    def test_failure_after_activation_keeps_old_reference_and_does_not_repeat_save(self):
        self.fail = 'reference'
        with self.assertRaises(ValueError): self.picture(1)
        self.assertFalse(self.client.status()['needs_attention'])
        self.assertTrue(self.image_controls.requires_reference())
        self.assertEqual(len(self.reference.blobs), 0)
        self.assertEqual(self.posts().count('/config-save'), 1)

    def test_unusable_normal_reference_is_retained_but_does_not_replace_current_reference(self):
        self.fail = 'reference-dark'
        with self.assertRaisesRegex(ValueError, 'auto_reference_unusable'): self.picture()
        self.assertEqual(len(self.reference.blobs), 0); self.assertFalse(self.client.status()['needs_attention'])
        run = next(self.client.trials.iterdir())
        meta = json.loads((run/'reference.json').read_text())
        self.assertFalse(meta['quality']['accepted']); self.assertFalse(meta['training_allowed'])
        self.assertEqual(digest((run/(meta['raw_sha256']+'.jpg')).read_bytes()), meta['raw_sha256'])

    def test_cancel_after_verified_shot_has_no_save_or_new_shot(self):
        stop = threading.Event()
        with self.assertRaisesRegex(ValueError, 'auto_cancelled'):
            self.picture(cancelled=stop.is_set, progress=lambda value: stop.set())
        self.assertEqual(self.posts(), ['/api/v1/capture/temporary'])
        self.assertFalse(self.client.status()['needs_attention']); self.assertEqual(self.raw, CONFIG)

    def test_shutdown_during_commit_finishes_activation_without_starting_reference_capture(self):
        stop = threading.Event()
        with self.assertRaisesRegex(ValueError, 'auto_cancelled'):
            self.picture(1, cancelled=stop.is_set, progress=lambda value: stop.set() if value['stage'] == 'saving' else None)
        self.assertEqual(self.posts(), ['/api/v1/capture/temporary']*2 + ['/config-save', '/apply-lighting', '/apply-image-controls'])
        self.assertFalse(self.client.status()['needs_attention']); self.assertTrue(self.image_controls.requires_reference())
        self.assertEqual(len(self.reference.blobs), 0)

    def test_bad_scene_stops_without_saving_or_claiming_success(self):
        self.render = lambda choice: image(level=190, contrast=0)
        with self.assertRaisesRegex(ValueError, 'auto_no_usable_image'): self.picture()
        self.assertEqual(self.posts(), ['/api/v1/capture/temporary'])
        self.assertFalse(self.client.status()['needs_attention']); self.assertEqual(self.raw, CONFIG)

    def test_no_space_or_run_quota_fails_before_camera_changes(self):
        with patch('camera_auto.shutil.disk_usage', return_value=type('Disk', (), {'free': 1})()):
            with self.assertRaisesRegex(ValueError, 'auto_storage_full'): self.picture()
        self.assertEqual(self.posts(), [])
        self.client.trials.mkdir(exist_ok=True)
        for n in range(128): (self.client.trials / str(n)).mkdir()
        with self.assertRaisesRegex(ValueError, 'auto_storage_full'): self.picture()
        self.assertEqual(self.posts(), [])

    def test_journal_failure_prevents_transmission_and_guards_capture(self):
        original = __import__('camera_auto')._write
        def broken(path, value):
            if path == self.client.path: raise OSError('SECRET-private')
            return original(path, value)
        with patch('camera_auto._write', side_effect=broken):
            with self.assertRaises(ValueError): self.picture()
        self.assertEqual(self.posts(), []); self.assertTrue(self.client.status()['needs_attention'])

    def test_malformed_journal_fails_closed_and_mode_corruption_can_be_repaired_separately(self):
        self.client.path.write_text('{"version":1,"version":1}')
        client = self.restart()
        with self.assertRaisesRegex(ValueError, 'auto_restore_unverified'): client.require_capture()
        with self.assertRaisesRegex(ValueError, 'auto_recovery_unavailable'): client.recover(digest(CONFIG))
        self.client.mode_path.write_text('bad')
        client = self.restart(); self.assertTrue(client.status()['mode_storage_error'])
        client.set_mode(False); self.assertFalse(client.status()['mode_storage_error'])
        self.assertTrue(client.status()['needs_attention']); self.assertEqual(self.calls, [])

    def test_operation_lock_prevents_overlap_and_status_remains_available(self):
        ready, release = threading.Event(), threading.Event()
        def occupy():
            with self.camera.operation(): ready.set(); release.wait(5)
        thread = threading.Thread(target=occupy); thread.start(); ready.wait(1)
        try:
            self.assertTrue(self.client.status()['automatic'])
            with self.assertRaisesRegex(ValueError, 'camera_busy'): self.picture()
            self.assertEqual(self.calls, [])
        finally: release.set(); thread.join()

    def test_collector_honors_auto_guard_without_device_calls(self):
        self.fail = 'lost'
        with self.assertRaises(ValueError): self.picture()
        self.calls = []
        store = Store(self.root)
        collector = Collector(store, self.camera, 30); collector.once()
        self.assertEqual(self.calls, []); self.assertEqual(store.status()['captures'], 0)
        self.assertEqual(collector.last_error['error'], 'auto_restore_unverified')


class AutoSetupTests(unittest.TestCase):
    setUp = AutoTransactions.setUp
    tearDown = AutoTransactions.tearDown
    headers = AutoTransactions.headers
    posts = AutoTransactions.posts

    def worker(self):
        from camera_setup import CameraSetup
        return CameraSetup(self.camera, self.reference, 30, False, self.lighting, self.image_controls, self.client)

    def test_auto_mode_is_a_local_job_and_does_not_change_sensor_values(self):
        worker = self.worker(); worker.start('auto-mode', automatic=False); worker.once()
        self.assertFalse(worker.status()['auto_settings']['automatic'])
        self.assertEqual(self.calls, []); self.assertEqual(self.raw, CONFIG)

    def test_auto_picture_returns_one_normal_reference_and_progress(self):
        worker = self.worker(); worker.start('auto-picture', revision=digest(CONFIG), orientation=0); worker.once()
        status = worker.status()
        self.assertEqual(status['state'], 'ready'); self.assertEqual(status['progress']['stage'], 'reference')
        self.assertEqual(status['reference_sha256'], digest(self.reference.blobs[0]))
        self.assertEqual(status['settings']['revision'], status['image_settings']['revision'])
        self.assertTrue(status['auto_settings']['automatic'])

    def test_pending_job_result_is_cleared_before_other_setup_action(self):
        worker = self.worker(); worker.start('auto-picture', revision=digest(CONFIG), orientation=0); worker.once()
        self.assertIn('auto_result', worker.status()); worker.start('auto-mode', automatic=False)
        self.assertNotIn('auto_result', worker.status()); self.assertNotIn('image_settings', worker.status())
        self.assertNotIn('reference_sha256', worker.status())

    def test_restore_failure_is_exposed_with_guard_and_no_retry(self):
        self.fail = 'restore'; worker = self.worker()
        worker.start('auto-picture', revision=digest(CONFIG), orientation=0); worker.once()
        self.assertEqual(worker.status()['error'], 'auto_restore_unverified')
        self.assertTrue(worker.status()['auto_settings']['needs_attention'])
        self.assertFalse(worker.once()); self.assertEqual(self.probes, 1)

    def test_wrong_action_types_fail_before_jobs(self):
        worker = self.worker()
        for action, parameters in (('auto-mode', {'automatic': 1}), ('auto-picture', {'revision': digest(CONFIG), 'orientation': True}),
                                   ('auto-picture', {'revision': digest(CONFIG), 'orientation': 4}), ('auto-recover', {'revision': None})):
            with self.subTest(action=action), self.assertRaises(ValueError): worker.start(action, **parameters)
        self.assertEqual(self.calls, [])

    def test_image_load_reports_unsupported_auto_without_fake_sensor_fallback(self):
        worker = self.worker(); self.fail = 'unsupported'; worker.start('image-load'); worker.once()
        status = worker.status()
        self.assertEqual(status['state'], 'ready'); self.assertFalse(status['auto_settings']['supported'])
        self.assertEqual(status['image_settings']['controls'], ImageConfig(CONFIG, 'OV2640').controls())
        self.assertEqual(self.posts(), [])

    def test_http_auto_jobs_require_token_and_strict_payloads(self):
        import urllib.request
        from service import handler
        self.reference.status = lambda: {'revision': None, 'calibration': None}
        worker = self.worker()
        server = ThreadingHTTPServer(('127.0.0.1', 0), handler(Store(self.root), False, None, setup=self.reference, camera_setup=worker))
        thread = threading.Thread(target=server.serve_forever); thread.start()
        url = f'http://127.0.0.1:{server.server_port}'
        try:
            with urllib.request.urlopen(url+'/api/setup') as response: token = json.load(response)['token']
            for data in ({'action': 'auto-mode', 'automatic': False, 'extra': 1}, {'action': []},
                         {'action': 'auto-picture', 'revision': digest(CONFIG)}, {'action': 'auto-mode', 'automatic': 1}):
                request = urllib.request.Request(url+'/api/camera-setup', data=json.dumps(data).encode(),
                    headers={'Content-Type':'application/json', 'X-AIEdge-Setup':token}, method='POST')
                with self.subTest(data=data), self.assertRaises(urllib.error.HTTPError) as error: urllib.request.urlopen(request)
                self.assertEqual(error.exception.code, 400); error.exception.close()
            request = urllib.request.Request(url+'/api/camera-setup', data=b'{"action":"auto-mode","automatic":false}',
                headers={'Content-Type':'application/json'}, method='POST')
            with self.assertRaises(urllib.error.HTTPError) as error: urllib.request.urlopen(request)
            self.assertEqual(error.exception.code, 403); error.exception.close()
            request.add_header('X-AIEdge-Setup', token)
            with urllib.request.urlopen(request) as response: self.assertEqual(json.load(response)['state'], 'queued')
            worker.once()
            with urllib.request.urlopen(url+'/api/camera-setup') as response: self.assertFalse(json.load(response)['auto_settings']['automatic'])
            self.assertEqual(self.calls, [])
        finally:
            server.shutdown(); server.server_close(); thread.join()


if __name__ == '__main__': unittest.main()
