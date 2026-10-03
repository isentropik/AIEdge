import hashlib, json, tempfile, threading, unittest, urllib.request, urllib.error
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from http.server import ThreadingHTTPServer
from meter_profile import MeterProfile, validate
from setup_store import Setup
from reading_format import FormatStore

PROFILE = {'version': 1, 'type': 'gas', 'unit': 'ft3'}
PIPELINE = 'a' * 64


class MeterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.meter = MeterProfile(self.root, Setup._atomic)
        self.worker = SimpleNamespace(lock=threading.Lock(), reader=SimpleNamespace(pipeline_id=PIPELINE, dials=[{}]))
        self.formats = FormatStore(self.root, self.worker, self.meter)

    def tearDown(self):
        self.temp.cleanup()

    def format(self, unit='ft3'):
        return {'version': 1, 'pipeline_id': PIPELINE, 'unit': unit,
                'dials': [{'index': 0, 'value_per_revolution': 1000, 'position_error': .1}]}

    def test_profile_without_camera_reference_or_calibration_persists(self):
        setup = Setup(self.root, lambda _: self.fail('No reader construction'), self.worker)
        saved = setup.meter.save(PROFILE, None)
        restored = Setup(self.root, lambda _: self.fail('No reader construction'), self.worker)
        self.assertEqual(restored.status()['meter'], saved)
        self.assertIsNone(restored.status()['calibration'])
        self.assertFalse((self.root / 'reading-format.json').exists())

    def test_invalid_and_unsupported_combinations_never_write(self):
        for value in (None, [], {}, dict(PROFILE, version=True), dict(PROFILE, type='solar'),
                      dict(PROFILE, unit='L'), dict(PROFILE, unit=[]), dict(PROFILE, extra=True),
                      dict(PROFILE, type='electric'), dict(PROFILE, version=2)):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'meter_profile_invalid'):
                self.meter.save(value, None)
        self.assertFalse(self.meter.saved.path.exists())
        for type_, units in [('gas', ['ft3', 'm3']), ('water', ['ft3', 'm3', 'L', 'gal_us']), ('electric', ['kWh'])]:
            for unit in units:
                validate({'version': 1, 'type': type_, 'unit': unit})

    def test_unit_change_preserves_active_format_until_explicit_matching_save(self):
        saved = self.formats.save(self.format(), None)
        before = self.formats.path.read_bytes()
        self.meter.save(dict(PROFILE, unit='m3'), None)
        self.assertEqual(self.formats.status(), saved)
        self.assertEqual(self.formats.path.read_bytes(), before)
        with self.assertRaisesRegex(ValueError, 'meter_units_changed_review_format'):
            self.formats.save(self.format(), saved['revision'])
        changed = self.formats.save(self.format('m3'), saved['revision'])
        self.assertEqual(changed['format']['unit'], 'm3')
        self.assertEqual(FormatStore(self.root, self.worker, self.meter).status(), changed)

    def test_revision_conflict_and_failed_write_preserve_current_choices(self):
        saved = self.meter.save(PROFILE, None)
        before = self.meter.saved.path.read_bytes()
        with self.assertRaisesRegex(ValueError, 'changed_reload'):
            self.meter.save(dict(PROFILE, unit='m3'), None)
        with patch.object(self.meter, 'atomic', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                self.meter.save(dict(PROFILE, unit='m3'), saved['revision'])
        self.assertEqual(self.meter.status(), saved)
        self.assertEqual(self.meter.saved.path.read_bytes(), before)

    def test_noop_avoids_write_but_external_edits_are_not_overwritten(self):
        saved = self.meter.save(PROFILE, None)
        with patch.object(self.meter, 'atomic', side_effect=AssertionError('No write expected')):
            self.assertEqual(self.meter.save(PROFILE, saved['revision']), saved)
        self.meter.saved.path.write_text('{"external":true}')
        before = self.meter.saved.path.read_bytes()
        with self.assertRaisesRegex(ValueError, 'changed_reload'):
            self.meter.save(PROFILE, saved['revision'])
        with self.assertRaisesRegex(ValueError, 'changed_reload'):
            self.formats.save(self.format(), None)
        self.assertEqual(self.meter.saved.path.read_bytes(), before)

    def test_corrupt_choices_are_retained_before_validated_replacement(self):
        raw = b'{invalid profile'
        self.meter.saved.path.write_bytes(raw)
        broken = MeterProfile(self.root, Setup._atomic)
        self.assertTrue(broken.status()['recovery']['original_preserved'])
        self.assertIsNone(broken.status()['profile'])
        with self.assertRaisesRegex(ValueError, 'meter_profile_unavailable'):
            FormatStore(self.root, self.worker, broken).save(self.format(), None)
        saved = broken.save(PROFILE, broken.status()['revision'])
        backup = self.root / 'recovery' / ('meter-profile-' + hashlib.sha256(raw).hexdigest() + '.json')
        self.assertEqual(backup.read_bytes(), raw)
        self.assertEqual(MeterProfile(self.root, Setup._atomic).status(), saved)

    def test_simultaneous_unit_change_cannot_commit_a_stale_format(self):
        saved = self.meter.save(PROFILE, None)
        old = self.formats.save(self.format(), None)
        entered, release = threading.Event(), threading.Event()
        outcomes = []
        def atomic(path, blob):
            entered.set()
            if not release.wait(5):
                raise RuntimeError('test did not release write')
            Setup._atomic(path, blob)
        self.meter.atomic = atomic
        change = threading.Thread(target=lambda: self.meter.save(dict(PROFILE, unit='m3'), saved['revision']))
        def save_format():
            try:
                self.formats.save(self.format(), old['revision'])
            except ValueError as error:
                outcomes.append(str(error))
        change.start()
        self.assertTrue(entered.wait(5))
        formatting = threading.Thread(target=save_format)
        formatting.start()
        release.set()
        change.join(5)
        formatting.join(5)
        self.assertFalse(change.is_alive() or formatting.is_alive())
        self.assertEqual(outcomes, ['meter_units_changed_review_format'])
        self.assertEqual(self.formats.status(), old)

    def test_http_profile_requires_token_and_exact_payload_then_reads_back(self):
        from capture import Store
        from service import handler
        setup = Setup(self.root, lambda _: self.fail('No reader construction'), self.worker)
        server = ThreadingHTTPServer(('127.0.0.1', 0), handler(Store(self.root), False, None, self.worker, setup))
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        origin = f'http://127.0.0.1:{server.server_port}'
        def post(payload, token=None):
            headers = {'Content-Type': 'application/json'}
            if token:
                headers['X-AIEdge-Setup'] = token
            request = urllib.request.Request(origin + '/api/setup/meter', data=json.dumps(payload).encode(), headers=headers)
            try:
                with urllib.request.urlopen(request) as response:
                    return response.status, json.load(response)
            except urllib.error.HTTPError as error:
                with error:
                    return error.code, None
        try:
            with urllib.request.urlopen(origin + '/api/setup') as response:
                state = json.load(response)
            payload = {'profile': PROFILE, 'revision': None}
            self.assertEqual(post(payload)[0], 403)
            self.assertEqual(post(dict(payload, extra=True), state['token'])[0], 400)
            code, saved = post(payload, state['token'])
            self.assertEqual(code, 200)
            with urllib.request.urlopen(origin + '/api/setup') as response:
                self.assertEqual(json.load(response)['meter'], saved)
            self.assertEqual(post(payload, state['token'])[0], 400)
            with urllib.request.urlopen(origin + '/meter-profile.js') as response:
                self.assertEqual(response.headers.get_content_type(), 'text/javascript')
        finally:
            server.shutdown()
            thread.join()
            server.server_close()
