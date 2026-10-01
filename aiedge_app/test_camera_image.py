import copy, hashlib, json, tempfile, threading, unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from camera_image import CameraImage, Config, capabilities, validate
from capture import Camera

CONFIG = b'''# retain unrelated bytes\r\n[TakeImage]\r\nCamAec = false ; automatic exposure\r\nCamAec2 = false\r\nCamAecValue = 600\r\nCamAeLevel = 0\r\nCamAgc = false\r\nCamAgcGain = 0\r\nCamGainceiling = X4\r\nCamHmirror = false\r\nCamVflip = false\r\nCamContrast = 1\r\nLEDIntensity = 29\r\n[Network]\r\nPassword = SECRET-private\r\n[Unknown]\r\nFutureField = keep me\r\n'''
CAPS = {'version': 1, 'mode': 'remote-camera', 'saved_controls_apply': True, 'model': 'OV2640',
        'compensation_limit': 2, 'apply_path': '/apply-image-controls', 'apply_method': 'POST', 'private': 'SECRET'}
def sha(raw): return hashlib.sha256(raw).hexdigest()

class ImageConfigTests(unittest.TestCase):
    def test_noop_and_single_edit_preserve_other_bytes(self):
        config = Config(CONFIG, 'OV2640'); choices = config.controls()
        self.assertEqual(config.plan(choices), CONFIG)
        choices['exposure'] = 1200
        self.assertEqual(config.plan(choices), CONFIG.replace(b'CamAecValue = 600', b'CamAecValue = 1200'))

    def test_supported_sensor_bounds_and_gain_aliases(self):
        choices = Config(CONFIG, 'OV2640').controls(); self.assertEqual(choices['gain_limit'], 1)
        for model, bound in (('OV2640', 2), ('OV3660', 5), ('OV5640', 5)):
            choices['compensation'] = bound; validate(choices, model)
            choices['compensation'] = bound + 1
            with self.assertRaises(ValueError): validate(choices, model)
        for number, label in enumerate(('X2','X4','X8','X16','X32','X64','X128')):
            raw = CONFIG.replace(b'CamGainceiling = X4', ('CamGainceiling = ' + label).encode())
            self.assertEqual(Config(raw, 'OV2640').controls()['gain_limit'], number)

    def test_untyped_out_of_range_or_unknown_choices_are_rejected(self):
        base = Config(CONFIG, 'OV2640').controls()
        for patch in ({'exposure': True},{'auto_gain': 1},{'gain': 31},{'gain_limit': 7},{'compensation': -3},
                      {'mirror': 'false'},{'gain': 1.1},{'extra': 1}):
            choice = dict(base, **patch)
            with self.subTest(patch=patch), self.assertRaises(ValueError): Config(CONFIG,'OV2640').plan(choice)

    def test_ambiguous_missing_and_malformed_saved_settings_are_rejected(self):
        for raw in (CONFIG + b'[TakeImage]\n', CONFIG.replace(b'[TakeImage]', b';[TakeImage]'),
                    CONFIG.replace(b'CamAgc = false', b';CamAgc = false'), CONFIG.replace(b'CamAgc = false', b'CamAgc = false\nCamAgc = true'),
                    CONFIG.replace(b'CamAec = false', b'CamAec = disabled'), CONFIG.replace(b'CamAecValue = 600', b'CamAecValue = 1201'),
                    CONFIG + b'\0', CONFIG.replace(b'CamAecValue = 600',b'CamAecValue = 00000')):
            with self.subTest(hash=sha(raw)), self.assertRaises(ValueError): Config(raw,'OV2640').controls()

    def test_contract_requires_exact_mode_path_and_types(self):
        clean = capabilities(CAPS); self.assertNotIn('SECRET', json.dumps(clean))
        for patch in ({'version': True},{'mode':'full-reader'},{'saved_controls_apply':1},
                      {'model':'unknown'},{'compensation_limit':5},{'apply_path':'/editflow?task=cam_settings'}):
            with self.subTest(patch=patch), self.assertRaises(ValueError): capabilities(dict(CAPS,**patch))

class ImageTransactions(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(); self.raw = CONFIG; self.calls = []; self.fail = None
        owner = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args): pass
            def answer(self,body,status=200,kind='application/json'):
                self.send_response(status); self.send_header('Content-Type',kind); self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body)
            def do_GET(self):
                owner.calls.append(('GET',self.path))
                if self.path == '/image-controls-capabilities':
                    self.answer(b'SECRET',404) if owner.fail == 'unsupported' else self.answer(json.dumps(CAPS).encode())
                elif self.path == '/fileserver/config/config.ini': self.answer(owner.raw,kind='text/plain')
                else: self.answer(b'SECRET',404)
            def do_POST(self):
                owner.calls.append(('POST',self.path)); body = self.rfile.read(int(self.headers['Content-Length']))
                if self.path == '/config-save':
                    data = json.loads(body)
                    if owner.raw.decode() != data['before']: self.answer(b'SECRET',409); return
                    owner.raw = data['after'].encode()
                    self.answer(b'{"saved":false}' if owner.fail == 'save' else b'{"saved":true}')
                elif self.path == '/apply-image-controls':
                    if body != owner.raw: self.answer(b'SECRET',409); return
                    if owner.fail == 'apply': self.answer(b'SECRET',500); return
                    if owner.fail == 'lost': self.answer(b'not JSON'); return
                    if owner.fail == 'changed-after': owner.raw += b'# another session\n'
                    revision = '0' * 64 if owner.fail == 'bad-ack' else sha(body)
                    self.answer(json.dumps({'saved':True,'active':True,'restart_required':False,'active_revision':revision}).encode())
                else: self.answer(b'SECRET',404)
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler); self.thread=threading.Thread(target=self.server.serve_forever); self.thread.start()
        self.camera=Camera(f'http://127.0.0.1:{self.server.server_port}',username='device',password='SECRET')
        self.camera.readiness=lambda:{'state':'ready'}
        self.client=CameraImage(self.camera,self.directory.name); self.camera.image_controls=self.client
    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(); self.directory.cleanup()
    def choice(self,**change): return dict(Config(self.raw,'OV2640').controls(),**change)
    def posts(self): return [p for method,p in self.calls if method == 'POST']

    def test_load_is_read_only_redacted_and_noop_has_no_write(self):
        result=self.client.load(); self.assertNotIn('SECRET',json.dumps(result)); self.assertFalse(result['active_verified'])
        result=self.client.apply(result['revision'],result['controls']); self.assertFalse(result['changed']); self.assertEqual(self.posts(),[])
        self.assertFalse(self.client.path.exists())
    def test_unknown_firmware_never_uses_legacy_preview_or_config_save(self):
        self.fail='unsupported'
        with self.assertRaisesRegex(ValueError,'unsupported'): self.client.apply(sha(CONFIG),self.choice(exposure=700))
        self.assertEqual(self.calls,[('GET','/image-controls-capabilities')]); self.assertEqual(self.posts(),[])
    def test_verified_apply_keeps_unrelated_config_and_does_not_capture_or_restart(self):
        result=self.client.apply(sha(CONFIG),self.choice(exposure=700))
        self.assertTrue(result['active_verified']); self.assertFalse(self.client.needs_attention())
        self.assertEqual(self.posts(),['/config-save','/apply-image-controls'])
        self.assertEqual(self.raw,CONFIG.replace(b'CamAecValue = 600',b'CamAecValue = 700'))
    def test_stale_baseline_has_no_write(self):
        self.raw+=b'# changed\n'
        with self.assertRaisesRegex(ValueError,'conflict'): self.client.apply(sha(CONFIG),self.choice(exposure=700))
        self.assertEqual(self.posts(),[]); self.assertFalse(self.client.path.exists())
    def test_lost_or_wrong_activation_ack_blocks_capture_and_survives_restart(self):
        for failure in ('lost','bad-ack','changed-after'):
            self.raw=CONFIG; self.calls=[]; self.fail=failure
            with self.subTest(failure=failure), self.assertRaises(ValueError): self.client.apply(sha(CONFIG),self.choice(exposure=700))
            self.assertEqual(self.posts(),['/config-save','/apply-image-controls']); self.assertTrue(self.client.needs_attention())
            restarted=CameraImage(self.camera,self.directory.name); self.assertTrue(restarted.needs_attention())
            with self.assertRaisesRegex(ValueError,'unverified'): restarted.require_capture()
            self.assertNotIn('SECRET',self.client.path.read_text())
    def test_failed_save_does_not_activate_and_explicit_recovery_does_not_resave(self):
        self.fail='save'
        with self.assertRaisesRegex(ValueError,'save_unverified'): self.client.apply(sha(CONFIG),self.choice(exposure=700))
        self.assertEqual(self.posts(),['/config-save'])
        self.fail=None; self.calls=[]; current=self.client.load()
        result=self.client.apply(current['revision'],current['controls'])
        self.assertTrue(result['active_verified']); self.assertEqual(self.posts(),['/apply-image-controls'])
    def test_orientation_requires_exact_new_photo_and_saved_calibration(self):
        self.client.apply(sha(CONFIG),self.choice(mirror=True)); self.assertTrue(self.client.requires_reference())
        with self.assertRaisesRegex(ValueError,'reference_required'): self.camera.require_capture()
        self.camera.require_capture(reference=True)
        reference='a'*64
        for headers in ({},{'X-AIEdge-Image-Orientation':'0'}):
            with self.assertRaisesRegex(ValueError,'orientation_unverified'): self.client.reference_taken(reference,headers)
        self.client.reference_taken(reference,{'X-AIEdge-Image-Orientation':'1'})
        self.client.calibration_saved('b'*64); self.assertTrue(self.client.requires_reference())
        restarted=CameraImage(self.camera,self.directory.name); restarted.calibration_saved(reference)
        self.assertFalse(restarted.requires_reference()); self.assertFalse(restarted.path.exists())
    def test_duplicate_orientation_headers_and_unactivated_reference_are_rejected(self):
        from email.message import Message
        self.client.apply(sha(CONFIG),self.choice(flip=True)); headers=Message()
        headers['X-AIEdge-Image-Orientation']='2'; headers['X-AIEdge-Image-Orientation']='2'
        with self.assertRaisesRegex(ValueError,'orientation_unverified'): self.client.reference_taken('a'*64,headers)
        self.client.pending['activation_verified']=False
        with self.assertRaisesRegex(ValueError,'unverified'): self.client.reference_taken('a'*64,{'X-AIEdge-Image-Orientation':'2'})
    def test_state_queries_do_not_wait_for_network_transaction_lock(self):
        self.client.operation_lock.acquire()
        try:
            result=[]; thread=threading.Thread(target=lambda: result.append(self.client.needs_attention())); thread.start(); thread.join(.5)
            self.assertFalse(thread.is_alive()); self.assertEqual(result,[False])
            with self.assertRaisesRegex(ValueError,'busy'): self.client.apply(sha(CONFIG),self.choice(exposure=700))
            self.assertEqual(self.calls,[])
        finally: self.client.operation_lock.release()
    def test_corrupt_state_prevents_changes_and_capture_without_device_calls(self):
        self.client.path.write_text('bad state'); client=CameraImage(self.camera,self.directory.name)
        with self.assertRaisesRegex(ValueError,'storage_unavailable'): client.apply(sha(CONFIG),self.choice(exposure=700))
        with self.assertRaisesRegex(ValueError,'unverified'): client.require_capture()
        self.assertEqual(self.calls,[])

if __name__=='__main__': unittest.main()
