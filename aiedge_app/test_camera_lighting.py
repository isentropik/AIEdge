import copy
import hashlib
import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from camera_lighting import CameraLighting, Config, capabilities, digest
from camera_setup import CameraSetup
from capture import Camera, Collector

CONFIG = b'''# retain comments\r\n[TakeImage]\r\nLEDIntensity = 25 ; master\r\nCameraExposure = 600\r\n[GPIO]\r\nIO0 = disabled disabled 10 false false unused\r\nIO1 = disabled disabled 10 false false unused\r\nIO3 = disabled disabled 10 false false unused\r\nIO4 = disabled disabled 10 false false unused\r\nIO12 = external-flash-ws281x   disabled 10 false false lighting # strip\r\nIO13 = disabled disabled 10 false false unused\r\nLEDType = SK6812_RGBW\r\nLEDNumbers = 19\r\nLEDColor = 0 0 0 255\r\n[Network]\r\nPassword = SECRET-private\r\n[Unknown]\r\nFutureSetting = preserve me\r\n'''
CAPS = {'version':1, 'builtin_pin':4, 'pins':[{'pin':n,'available':True,'reason':'SECRET-unsolicited'} for n in (0,1,3,4,12,13)]}


class ConfigTests(unittest.TestCase):
    def test_white_channel_and_master_intensity_stay_separate(self):
        parsed=Config(CONFIG);choice=parsed.lighting()
        self.assertEqual(choice['channels'],[0,0,0,255]);self.assertEqual(choice['intensity'],25)
        choice['intensity']=100
        after=parsed.plan(choice,capabilities(CAPS))
        self.assertEqual(after,CONFIG.replace(b'LEDIntensity = 25 ;',b'LEDIntensity = 100 ;'))
        self.assertEqual(Config(after).lighting()['channels'],[0,0,0,255])

    def test_noop_preserves_every_byte(self):
        config=Config(CONFIG);self.assertEqual(config.plan(config.lighting(),capabilities(CAPS)),CONFIG)

    def test_switching_light_preserves_other_gpio_fields_and_credentials(self):
        choice=Config(CONFIG).lighting();choice.update(source='builtin',pin=4)
        after=Config(CONFIG).plan(choice,capabilities(CAPS))
        self.assertIn(b'IO12 = disabled disabled 10 false false lighting # strip\r\n',after)
        self.assertIn(b'IO4 = built-in-led disabled 10 false false unused\r\n',after)
        self.assertIn(b'Password = SECRET-private\r\n',after)
        self.assertIn(b'FutureSetting = preserve me\r\n',after)
        self.assertEqual(Config(after).lighting(),choice)

    def test_ambiguous_or_invalid_configs_are_not_guessed(self):
        for raw in (CONFIG+b'[GPIO]\n',CONFIG.replace(b'LEDNumbers = 19',b'LEDNumbers = 19\nLEDNumbers = 20'),CONFIG.replace(b'[GPIO]',b';[GPIO]'),CONFIG.replace(b'LEDIntensity = 25',b'LEDIntensity = 101'),CONFIG.replace(b'SK6812_RGBW',b'SK6812'),CONFIG.replace(b'external-flash-ws281x',b'external-flash-pwm')):
            with self.subTest(raw=hashlib.sha256(raw).hexdigest()):
                with self.assertRaisesRegex(ValueError,'config_unsupported'):Config(raw).lighting()

    def test_rejects_invalid_or_occupied_pins_and_untyped_values(self):
        config=Config(CONFIG)
        for patch in ({'intensity':True},{'count':0},{'count':1.2},{'intensity':101},{'channels':[0,0,0,256]},{'channels':[0,0,0]},{'type':'SK6812'},{'pin':2},{'source':'builtin','pin':12}):
            choice=config.lighting();choice.update(patch)
            with self.subTest(patch=patch),self.assertRaises(ValueError):config.plan(choice,capabilities(CAPS))
        choice=config.lighting();choice['pin']=4
        occupied=CONFIG.replace(b'IO4 = disabled disabled',b'IO4 = input disabled')
        with self.assertRaisesRegex(ValueError,'pin_unavailable'):Config(occupied).plan(choice,capabilities(CAPS))

    def test_duplicate_capability_pins_and_bool_ids_rejected(self):
        for data in (dict(CAPS,version=True),dict(CAPS,builtin_pin=True),dict(CAPS,pins=CAPS['pins'][:-1]+[CAPS['pins'][0]])):
            with self.assertRaises(ValueError):capabilities(data)
        self.assertNotIn('SECRET',json.dumps(capabilities(CAPS)))

    def test_commented_free_pin_is_added_without_rewriting_the_example(self):
        raw=CONFIG.replace(b'IO4 = disabled disabled',b';IO4 = disabled disabled')
        choice=Config(raw).lighting();choice.update(source='builtin',pin=4)
        after=Config(raw).plan(choice,capabilities(CAPS))
        self.assertIn(b';IO4 = disabled disabled 10 false false unused\r\n',after)
        self.assertIn(b'IO4 = built-in-led disabled 10 false false lighting\r\n',after)
        self.assertEqual(Config(after).lighting(),choice)


class LightingTransactions(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory();self.raw=CONFIG;self.calls=[];self.fail=None;self.changed=False
        owner=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def answer(self,blob,status=200,kind='application/json'):
                self.send_response(status);self.send_header('Content-Type',kind);self.send_header('Content-Length',str(len(blob)));self.end_headers();self.wfile.write(blob)
            def do_GET(self):
                owner.calls.append(('GET',self.path))
                if self.path=='/fileserver/config/config.ini':self.answer(owner.raw,kind='text/plain')
                elif self.path=='/lighting-capabilities':self.answer(json.dumps(CAPS).encode())
                elif self.path=='/camera_capabilities':self.answer(b'{"model":"OV2640","private":"SECRET"}')
                else:self.answer(b'SECRET',404)
            def do_POST(self):
                body=self.rfile.read(int(self.headers['Content-Length']));owner.calls.append(('POST',self.path))
                if self.path=='/config-save':
                    data=json.loads(body)
                    if owner.raw.decode()!=data['before']:self.answer(b'SECRET',409);return
                    owner.raw=data['after'].encode()
                    if owner.fail=='save':self.answer(b'{"saved":false}');return
                    self.answer(b'{"saved":true,"active":false,"restart_required":true}')
                elif self.path=='/apply-lighting':
                    if owner.raw!=body:self.answer(b'SECRET',409);return
                    if owner.fail=='apply':self.answer(b'SECRET',500);return
                    if owner.fail=='lost-response':self.answer(b'not JSON');return
                    if owner.changed:owner.raw+=b'# concurrently changed\n'
                    self.answer(b'{"saved":true,"active":true,"restart_required":false}')
                else:self.answer(b'SECRET',404)
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler);self.thread=threading.Thread(target=self.server.serve_forever);self.thread.start()
        self.camera=Camera(f'http://127.0.0.1:{self.server.server_port}',username='device',password='SECRET')
        self.camera.readiness=lambda:{'state':'ready'}
        self.client=CameraLighting(self.camera,self.directory.name);self.camera.lighting=self.client
    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join();self.directory.cleanup()
    def change(self):
        choice=Config(self.raw).lighting();choice['intensity']=80;return choice
    def test_load_is_passive_and_redacted(self):
        result=self.client.load()
        self.assertEqual(result['sensor'],'OV2640');self.assertEqual(result['lighting']['count'],19)
        self.assertEqual(result['revision'],digest(CONFIG));self.assertNotIn('SECRET',json.dumps(result))
        self.assertTrue(all(method=='GET' for method,_ in self.calls));self.assertFalse(self.client.needs_attention())
    def test_apply_verifies_saved_bytes_and_activation_without_capture_or_restart(self):
        result=self.client.apply(digest(CONFIG),self.change())
        self.assertTrue(result['active_verified']);self.assertTrue(result['changed']);self.assertFalse(self.client.needs_attention())
        self.assertEqual([p for m,p in self.calls if m=='POST'],['/config-save','/apply-lighting'])
        self.assertEqual(self.raw,CONFIG.replace(b'LEDIntensity = 25 ;',b'LEDIntensity = 80 ;'))
        self.assertFalse(self.client.path.exists())
    def test_noop_has_no_sd_write_or_activation(self):
        result=self.client.apply(digest(CONFIG),Config(CONFIG).lighting())
        self.assertFalse(result['changed']);self.assertFalse(result['active_verified'])
        self.assertTrue(all(method=='GET' for method,_ in self.calls));self.assertFalse(self.client.path.exists())
    def test_baseline_conflict_prevents_all_writes(self):
        self.raw+=b'# newer\n'
        with self.assertRaisesRegex(ValueError,'conflict'):self.client.apply(digest(CONFIG),self.change())
        self.assertTrue(all(m=='GET' for m,_ in self.calls));self.assertFalse(self.client.needs_attention())
    def test_response_loss_keeps_pending_gate_across_restart_and_does_not_retry(self):
        self.fail='lost-response'
        with self.assertRaisesRegex(ValueError,'response_invalid'):self.client.apply(digest(CONFIG),self.change())
        self.assertTrue(self.client.needs_attention())
        with self.assertRaisesRegex(ValueError,'unverified'):self.camera.require_capture()
        restarted=CameraLighting(self.camera,self.directory.name)
        self.assertTrue(restarted.needs_attention());self.assertNotIn('SECRET',restarted.path.read_text())
        self.assertEqual([p for m,p in self.calls if m=='POST'],['/config-save','/apply-lighting'])
    def test_explicit_recovery_applies_readback_without_rewriting_sd(self):
        self.fail='apply'
        with self.assertRaises(ValueError):self.client.apply(digest(CONFIG),self.change())
        self.fail=None;self.calls.clear();current=self.client.load()
        self.assertTrue(current['needs_activation'])
        result=self.client.apply(current['revision'],current['lighting'])
        self.assertTrue(result['active_verified']);self.assertEqual([p for m,p in self.calls if m=='POST'],['/apply-lighting'])
        self.camera.require_capture()
    def test_changed_readback_after_activation_is_not_claimed_success(self):
        self.changed=True
        with self.assertRaisesRegex(ValueError,'conflict'):self.client.apply(digest(CONFIG),self.change())
        self.assertTrue(self.client.needs_attention())
    def test_save_not_confirmed_never_activates_or_retries(self):
        self.fail='save'
        with self.assertRaisesRegex(ValueError,'save_unverified'):self.client.apply(digest(CONFIG),self.change())
        self.assertEqual([p for m,p in self.calls if m=='POST'],['/config-save']);self.assertTrue(self.client.needs_attention())
    def test_worker_load_and_apply_are_explicit_and_keep_reference_unchanged(self):
        references=[]
        class Setup:
            def add_reference(self,raw):references.append(raw)
        worker=CameraSetup(self.camera,Setup(),30,False,self.client)
        self.assertEqual(self.calls,[]);worker.start('lighting-load');self.assertEqual(self.calls,[]);worker.once()
        self.assertTrue(worker.status()['camera_settings_supported'])
        worker.start('lighting-apply',digest(CONFIG),self.change());worker.once()
        self.assertEqual(worker.status()['state'],'ready');self.assertEqual(references,[])
    def test_pending_lighting_blocks_setup_and_collector_capture(self):
        self.client._intent(CONFIG,CONFIG)
        self.camera.capture=lambda:self.fail('capture must not occur')
        worker=CameraSetup(self.camera,object(),30,False,self.client);worker.start('picture');worker.once()
        self.assertEqual(worker.status()['error'],'camera_lighting_unverified')
        collector=Collector(object(),self.camera,30);collector.once()
        self.assertEqual(collector.last_error,{'error':'camera_lighting_unverified'})
    def test_corrupt_pending_state_blocks_writes_and_capture(self):
        self.client.path.write_text('bad state')
        client=CameraLighting(self.camera,self.directory.name)
        with self.assertRaisesRegex(ValueError,'storage_unavailable'):client.apply(digest(CONFIG),self.change())
        with self.assertRaisesRegex(ValueError,'unverified'):client.require_capture()
        self.assertEqual(self.calls,[])
    def test_settings_serialization_does_not_wait_on_capture_lock(self):
        worker=CameraSetup(self.camera,object(),30,False,self.client)
        self.camera.operation_lock.acquire()
        try:
            worker.start('lighting-load');thread=threading.Thread(target=worker.once);thread.start();thread.join(1)
            self.assertFalse(thread.is_alive());self.assertEqual(worker.status()['error'],'camera_busy');self.assertEqual(self.calls,[])
        finally:self.camera.operation_lock.release()


if __name__=='__main__':unittest.main()
