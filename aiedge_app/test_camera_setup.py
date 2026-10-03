import hashlib, io, json, tempfile, threading, time, unittest, urllib.request
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer
from types import SimpleNamespace
from PIL import Image
from camera_setup import CameraSetup
from capture import Store
from service import handler


def photo():
    stream=io.BytesIO();Image.new('RGB',(640,480),'white').save(stream,format='JPEG')
    blob=stream.getvalue()
    headers={'X-AIEdge-Frame-Id':'setup-photo',
             'X-AIEdge-Captured-At':datetime.now(timezone.utc).isoformat(),
             'X-AIEdge-SHA256':hashlib.sha256(blob).hexdigest(),
             'X-AIEdge-Clock-Id':'device-clock','X-AIEdge-Capture-Monotonic-Us':'12345'}
    return blob,headers


class CameraSetupTests(unittest.TestCase):
    def setUp(self):
        self.calls=[];self.references=[]
        self.blob,self.headers=photo()
        self.camera=SimpleNamespace(origin='http://camera.local',
            readiness=self.readiness,capture=self.capture)
        self.setup=SimpleNamespace(add_reference=self.add_reference)
        self.worker=CameraSetup(self.camera,self.setup,30,False)
    def readiness(self):self.calls.append('status');return {'state':'ready'}
    def capture(self):self.calls.append('capture');return self.blob,self.headers
    def add_reference(self,blob):self.references.append(blob);return hashlib.sha256(blob).hexdigest()

    def test_idle_and_check_never_capture_or_change_reference(self):
        self.assertEqual(self.calls,[]);self.assertFalse(self.worker.once())
        self.worker.start('check');self.assertEqual(self.calls,[])
        self.worker.once();self.assertEqual(self.calls,['status']);self.assertEqual(self.references,[])
        self.assertEqual(self.worker.status()['state'],'ready')

    def test_picture_keeps_real_hash_and_time_but_is_not_a_capture_event(self):
        with tempfile.TemporaryDirectory() as directory:
            store=Store(directory)
            self.worker.start('picture');self.worker.once();status=self.worker.status()
            self.assertEqual(status['reference_sha256'],hashlib.sha256(self.blob).hexdigest())
            self.assertEqual(status['image_sha256'],self.headers['X-AIEdge-SHA256'])
            self.assertEqual(status['captured_at'],self.headers['X-AIEdge-Captured-At'])
            self.assertEqual(self.references,[self.blob])
            self.assertEqual(store.status()['captures'],0)
            self.assertEqual(self.calls,['status','capture'])

    def test_unready_camera_never_requests_picture(self):
        self.camera.readiness=lambda:{'state':'busy'}
        self.worker.start('picture');self.worker.once()
        self.assertEqual(self.worker.status()['error'],'camera_not_ready')
        self.assertEqual(self.references,[]);self.assertEqual(self.calls,[])

    def test_invalid_hash_clock_or_image_keeps_reference(self):
        for field,value in [('X-AIEdge-SHA256','0'*64),('X-AIEdge-Capture-Monotonic-Us',None),('X-AIEdge-Captured-At','yesterday')]:
            with self.subTest(field=field):
                original=dict(self.headers)
                if value is None:self.headers.pop(field)
                else:self.headers[field]=value
                self.worker.start('picture');self.worker.once()
                self.assertEqual(self.worker.status()['state'],'error')
                self.assertEqual(self.references,[]);self.headers=original

    def test_failed_reference_write_is_not_reported_as_success(self):
        def fail(blob):raise OSError('PRIVATE-storage-path')
        self.setup.add_reference=fail
        self.worker.start('picture');self.worker.once()
        self.assertEqual(self.worker.status()['error'],'camera_setup_failed')
        self.assertNotIn('PRIVATE',json.dumps(self.worker.status()))
        self.assertNotIn('reference_sha256',self.worker.status())

    def test_only_one_job_and_no_retry_after_ambiguous_result(self):
        def fail():raise TimeoutError('PRIVATE-device-secret')
        self.camera.capture=fail
        self.worker.start('picture')
        with self.assertRaisesRegex(ValueError,'camera_setup_busy'):self.worker.start('picture')
        self.worker.once();self.assertFalse(self.worker.once())
        self.assertEqual(self.calls,['status']);self.assertEqual(self.references,[])
        self.assertEqual(self.worker.status()['state'],'error')

    def test_stopping_or_unconfigured_refuses_jobs(self):
        empty=CameraSetup(None,None,30,False)
        with self.assertRaisesRegex(ValueError,'camera_not_configured'):empty.start('check')
        self.worker.stop.set()
        with self.assertRaisesRegex(ValueError,'camera_setup_stopping'):self.worker.start('picture')
        self.assertEqual(self.calls,[])

    def test_blocked_camera_keeps_http_available_and_requires_setup_token(self):
        release=threading.Event();entered=threading.Event()
        def blocked():entered.set();release.wait(5);return {'state':'ready'}
        self.camera.readiness=blocked
        with tempfile.TemporaryDirectory() as directory:
            server=ThreadingHTTPServer(('127.0.0.1',0),handler(Store(directory),False,None,setup=self.setup,camera_setup=self.worker))
            thread=threading.Thread(target=server.serve_forever);thread.start()
            self.setup.status=lambda:{'revision':None,'calibration':None}
            url=f'http://127.0.0.1:{server.server_port}'
            worker=threading.Thread(target=self.worker.run);worker.start()
            try:
                with urllib.request.urlopen(url+'/api/setup') as response:token=json.load(response)['token']
                request=urllib.request.Request(url+'/api/camera-setup',data=b'{"action":"picture"}',headers={'Content-Type':'application/json'},method='POST')
                with self.assertRaises(urllib.error.HTTPError) as error:urllib.request.urlopen(request)
                self.assertEqual(error.exception.code,403);error.exception.close()
                request.add_header('X-AIEdge-Setup',token)
                start=time.monotonic()
                with urllib.request.urlopen(request,timeout=1) as response:self.assertEqual(json.load(response)['state'],'queued')
                self.assertLess(time.monotonic()-start,1)
                self.assertTrue(entered.wait(2))
                with urllib.request.urlopen(url+'/api/camera-setup',timeout=1) as response:self.assertEqual(json.load(response)['state'],'working')
                with urllib.request.urlopen(url+'/',timeout=1) as response:self.assertIn(b'Setup',response.read())
                self.assertEqual(self.references,[])
            finally:
                self.worker.stop.set();release.set();worker.join(5)
                server.shutdown();server.server_close();thread.join()
            self.assertFalse(worker.is_alive())

class ImageSetupTests(unittest.TestCase):
    # Use the same HTTP/camera fixture; these tests exercise app routing and the
    # worker's reference boundary rather than creating reading evidence.
    readiness=CameraSetupTests.readiness
    capture=CameraSetupTests.capture
    add_reference=CameraSetupTests.add_reference
    def setUp(self):
        CameraSetupTests.setUp(self)
        self.image_calls=[]
        self.image=SimpleNamespace(needs_attention=lambda:False,requires_reference=lambda:True,
            load=lambda:{'revision':'a'*64,'controls':{'exposure':600}},
            apply=lambda revision,controls:self.image_apply(revision,controls),
            reference_taken=lambda reference,headers:self.image_calls.append(('reference',reference)))
        self.worker.image_controls=self.image
    def image_apply(self,revision,controls):
        self.image_calls.append(('apply',revision,controls))
        return {'revision':'b'*64,'active_verified':True,'requires_reference':True}
    def test_image_jobs_are_explicit_and_do_not_take_photos(self):
        self.worker.start('image-load');self.worker.once()
        self.assertTrue(self.worker.status()['image_settings_supported']);self.assertEqual(self.calls,[])
        self.worker.start('image-apply','a'*64,controls={'exposure':700});self.worker.once()
        self.assertEqual(self.image_calls,[('apply','a'*64,{'exposure':700})])
        self.assertEqual(self.references,[]);self.assertEqual(self.calls,[])
    def test_reference_photo_uses_orientation_gate_and_preserves_hash(self):
        gates=[]
        self.camera.require_capture=lambda reference=False:gates.append(reference)
        self.camera.reference_capture=self.capture
        self.worker.start('picture');self.worker.once()
        self.assertEqual(gates,[True]);self.assertEqual(self.calls,['status','capture'])
        self.assertEqual(self.image_calls,[('reference',hashlib.sha256(self.blob).hexdigest())])
        self.assertTrue(self.worker.status()['image_requires_reference'])
    def test_http_image_apply_requires_token_and_exact_payload(self):
        with tempfile.TemporaryDirectory() as directory:
            self.setup.status=lambda:{'revision':None,'calibration':None}
            server=ThreadingHTTPServer(('127.0.0.1',0),handler(Store(directory),False,None,setup=self.setup,camera_setup=self.worker))
            thread=threading.Thread(target=server.serve_forever);thread.start()
            origin=f'http://127.0.0.1:{server.server_port}'
            def post(data,token=None):
                headers={'Content-Type':'application/json'}
                if token:headers['X-AIEdge-Setup']=token
                request=urllib.request.Request(origin+'/api/camera-setup',data=json.dumps(data).encode(),headers=headers,method='POST')
                try:
                    with urllib.request.urlopen(request) as response:return response.status,json.load(response)
                except urllib.error.HTTPError as error:
                    code=error.code;error.close();return code,None
            try:
                with urllib.request.urlopen(origin+'/api/setup') as response:token=json.load(response)['token']
                data={'action':'image-apply','revision':'a'*64,'controls':{'exposure':700}}
                self.assertEqual(post(data)[0],403)
                self.assertEqual(post(dict(data,lighting={}),token)[0],400)
                self.assertEqual(post({'action':'image-apply','revision':'a'*64},token)[0],400)
                self.assertEqual(post(data,token)[0],200);self.worker.once()
                self.assertEqual(self.image_calls,[('apply','a'*64,{'exposure':700})]);self.assertEqual(self.calls,[])
            finally:
                server.shutdown();server.server_close();thread.join()
    def test_orientation_receipt_is_exact_and_invalid_receipts_preserve_reference(self):
        from email.message import Message
        for value in ('0','1','2','3'):
            self.headers['X-AIEdge-Image-Orientation']=value
            self.worker.start('picture');self.worker.once()
            self.assertEqual(self.worker.status()['image_orientation'],int(value))
        self.references.clear()
        for value in ('4','-1','00',1):
            self.headers['X-AIEdge-Image-Orientation']=value
            self.worker.start('picture');self.worker.once()
            self.assertEqual(self.worker.status()['error'],'camera_image_orientation_unverified')
            self.assertNotIn('image_orientation',self.worker.status())
        duplicate=Message()
        for key,value in photo()[1].items():duplicate[key]=value
        duplicate['X-AIEdge-Image-Orientation']='0';duplicate['X-AIEdge-Image-Orientation']='0'
        self.headers=duplicate;self.worker.start('picture');self.worker.once()
        self.assertEqual(self.worker.status()['error'],'camera_image_orientation_unverified');self.assertEqual(self.references,[])

if __name__=='__main__':unittest.main()
