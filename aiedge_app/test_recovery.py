"""Damaged persisted setup must not make the recovery UI unreachable."""
import copy, hashlib, json, tempfile, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from capture import Store
from recognition import Recognition
from setup_store import Setup
from reading_format import FormatStore
from test_setup import Candidate, DESIGN, reference
from test_reading_format import document, PIPELINE


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = Store(self.root)
        self.worker = Recognition(self.store)

    def tearDown(self):
        self.temp.cleanup()

    def assert_original(self, name, blob):
        digest = hashlib.sha256(blob).hexdigest()
        backup = self.root / 'recovery' / (Path(name).stem + '-' + digest + '.json')
        self.assertEqual(backup.read_bytes(), blob)

    def test_bad_calibration_remains_until_valid_explicit_replacement(self):
        path = self.root / 'calibration.json'
        for blob in (b'{broken', b'\xff', b'{}', b'x' * 262145):
            with self.subTest(length=len(blob)):
                path.write_bytes(blob)
                worker = Recognition(self.store)
                setup = Setup(self.root, Candidate, worker)
                state = setup.status()
                self.assertIsNone(worker.reader)
                self.assertEqual(path.read_bytes(), blob)
                self.assertTrue(state['recovery']['replacement_allowed'])
                self.assertEqual(state['revision'], 'recovery:' + hashlib.sha256(blob).hexdigest())
                ref = setup.add_reference(reference())
                with self.assertRaisesRegex(ValueError, 'changed'):
                    setup.save(ref, DESIGN, None)
                bad = copy.deepcopy(DESIGN);bad['markers'] = []
                with self.assertRaises(ValueError):
                    setup.save(ref, bad, state['revision'])
                self.assertEqual(path.read_bytes(), blob)
                saved = setup.save(ref, DESIGN, state['revision'])
                self.assertNotIn('recovery', saved)
                self.assertIsNotNone(worker.reader)
                self.assert_original(path.name, blob)
                self.assertEqual(Setup(self.root, Candidate, Recognition(self.store)).status(), saved)

    def test_missing_reference_or_model_leaves_calibration_intact(self):
        setup = Setup(self.root, Candidate, self.worker)
        ref = setup.add_reference(reference());setup.save(ref, DESIGN, None)
        before = setup.path.read_bytes()
        with patch.object(Setup, 'reference', side_effect=FileNotFoundError()):
            recovery = Setup(self.root, Candidate, Recognition(self.store))
        self.assertEqual(recovery.status()['recovery']['code'], 'saved_reference_unavailable')
        self.assertEqual(setup.path.read_bytes(), before)
        with patch('test_recovery.Candidate', side_effect=ValueError('model_hash_mismatch:main')):
            recovery = Setup(self.root, Candidate, Recognition(self.store))
        self.assertIsNone(recovery.active)
        self.assertEqual(setup.path.read_bytes(), before)

    def test_bad_schema_values_are_recoverable(self):
        setup = Setup(self.root, Candidate, self.worker)
        ref = setup.add_reference(reference());saved = setup.save(ref, DESIGN, None)
        for field in ('markers', 'dials'):
            corrupted = copy.deepcopy(saved['calibration']);corrupted[field][0] = None
            setup.path.write_text(json.dumps(corrupted), encoding='utf-8')
            recovery = Setup(self.root, Candidate, Recognition(self.store))
            self.assertIn('recovery', recovery.status())

    def test_external_change_is_not_overwritten(self):
        path = self.root / 'calibration.json';path.write_bytes(b'broken')
        setup = Setup(self.root, Candidate, self.worker)
        revision = setup.status()['revision'];ref = setup.add_reference(reference())
        path.write_bytes(b'changed elsewhere')
        with self.assertRaisesRegex(ValueError, 'changed'):
            setup.save(ref, DESIGN, revision)
        self.assertEqual(path.read_bytes(), b'changed elsewhere')
        self.assertIsNone(self.worker.reader)

    def test_backup_or_replace_failure_keeps_recovery_and_reader_off(self):
        path = self.root / 'calibration.json';path.write_bytes(b'broken')
        setup = Setup(self.root, Candidate, self.worker)
        state = setup.status();ref = setup.add_reference(reference())
        with patch('saved_file.shutil.copyfileobj', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):setup.save(ref, DESIGN, state['revision'])
        self.assertEqual(setup.status(), state)
        self.assertEqual(path.read_bytes(), b'broken');self.assertIsNone(self.worker.reader)
        # A later attempt can recover when storage is writable again.
        setup.save(ref, DESIGN, state['revision'])
        self.assert_original(path.name, b'broken')
        self.assertIsNotNone(self.worker.reader)

    def test_failed_atomic_replace_preserves_verified_original(self):
        path = self.root / 'calibration.json';path.write_bytes(b'broken')
        setup = Setup(self.root, Candidate, self.worker)
        state = setup.status();ref = setup.add_reference(reference())
        with patch.object(setup, '_atomic', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):setup.save(ref, DESIGN, state['revision'])
        self.assert_original(path.name, b'broken')
        self.assertEqual(path.read_bytes(), b'broken');self.assertEqual(setup.status(), state)
        setup.save(ref, DESIGN, state['revision'])
        self.assertIsNotNone(self.worker.reader)

    def test_format_recovery_never_returns_old_value(self):
        self.worker.reader = SimpleNamespace(pipeline_id=PIPELINE, dials=[{}, {}])
        path = self.root / 'reading-format.json';path.write_bytes(b'{broken')
        formats = FormatStore(self.root, self.worker)
        state = formats.status()
        self.assertEqual(formats.evaluate({})['state'], 'unavailable')
        self.assertIsNone(formats.evaluate({})['value'])
        with self.assertRaisesRegex(ValueError, 'changed_reload'):
            formats.save(document([1000, 100]), None)
        formats.save(document([1000, 100]), state['revision'])
        self.assert_original(path.name, b'{broken')
        self.assertNotIn('recovery', formats.status())
        self.assertEqual(FormatStore(self.root, self.worker).status(), formats.status())

    def test_long_data_directory_can_preserve_recovery_copy(self):
        from saved_file import SavedFile
        # Common on desktop development checkouts; temp names must not append to
        # the already long content-addressed backup filename.
        root = self.root / ('long-data-directory-' + 'x' * 65)
        root.mkdir()
        path = root / 'reading-format.json';path.write_bytes(b'broken')
        saved = SavedFile(path);saved.read();saved.failed('invalid')
        saved.replace(b'{}', Setup._atomic, 'changed')
        self.assertEqual(path.read_bytes(), b'{}')
        self.assertEqual(next((root/'recovery').glob('*.json')).read_bytes(), b'broken')

    def test_oversized_reference_keeps_startup_recoverable(self):
        from capture import MAX_IMAGE
        setup=Setup(self.root,Candidate,self.worker)
        ref=setup.add_reference(reference());setup.save(ref,DESIGN,None)
        path=setup.references/(ref+'.image')
        with path.open('wb') as stream:stream.seek(MAX_IMAGE);stream.write(b'x')
        worker=Recognition(self.store);restarted=Setup(self.root,Candidate,worker)
        self.assertIsNone(worker.reader)
        self.assertEqual(restarted.status()['recovery']['code'],'saved_reference_unavailable')
        self.assertEqual(path.stat().st_size,MAX_IMAGE+1)
    def test_unreadable_file_cannot_be_silently_replaced(self):
        with patch('saved_file.Path.open', side_effect=PermissionError()):
            setup = Setup(self.root, Candidate, self.worker)
        state = setup.status()
        self.assertFalse(state['recovery']['replacement_allowed'])
        self.assertFalse(state['recovery']['original_preserved'])
        ref = setup.add_reference(reference())
        with self.assertRaisesRegex(OSError, 'unreadable_restart_required'):
            setup.save(ref, DESIGN, state['revision'])


class ProcessRecoveryTests(unittest.TestCase):
    def test_damaged_files_do_not_stop_http_startup(self):
        import os, socket, subprocess, sys, time, urllib.request
        library = os.environ.get('AIEDGE_NATIVE_LIBRARY')
        models = os.environ.get('AIEDGE_MODELS_FIXTURE')
        if not library or not models:
            self.skipTest('native runtime fixture required')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'calibration.json').write_bytes(b'{broken calibration')
            (root/'reading-format.json').write_bytes(b'{broken format')
            with socket.socket() as probe:
                probe.bind(('127.0.0.1',0));port=probe.getsockname()[1]
            process=subprocess.Popen([sys.executable,str(Path(__file__).with_name('service.py')),
                '--data',directory,'--port',str(port),'--native-library',library,'--models',models],
                stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
            try:
                deadline=time.monotonic()+20
                while True:
                    if process.poll() is not None:
                        self.fail('Service exited: '+''.join(process.communicate()))
                    try:
                        with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/status',timeout=1) as r:
                            status=json.load(r)
                        break
                    except OSError:
                        if time.monotonic()>deadline:raise
                        time.sleep(.1)
                self.assertEqual(status['setup_recovery']['code'],'saved_calibration_invalid')
                self.assertEqual(status['format_recovery']['code'],'saved_reading_format_invalid')
                self.assertIsNone(status['reading']['value'])
                self.assertFalse(status['capture_enabled'])
                self.assertEqual(status['mqtt']['state'],'disabled')
                with urllib.request.urlopen(f'http://127.0.0.1:{port}/') as r:
                    self.assertIn(b'Calibration',r.read())
                self.assertEqual((root/'calibration.json').read_bytes(),b'{broken calibration')
                self.assertEqual((root/'reading-format.json').read_bytes(),b'{broken format')
            finally:
                process.terminate()
                try:process.communicate(timeout=5)
                except subprocess.TimeoutExpired:process.kill();process.communicate()

if __name__ == '__main__':
    unittest.main()
