"""Passive readiness and scheduled admission using a real loopback HTTP server."""
import contextlib,json,tempfile,threading,unittest
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from unittest.mock import patch
from capture import Camera,Collector,Store
from camera_status import validate
from test_capture import JPEG,headers

READY={'protocol_version':1,'mode':'remote-camera','state':'ready',
       'camera_available':True,'settings_ready':True,'clock_synchronized':True,
       'capture_path':'/api/v1/capture','capture_method':'POST',
       'capture_clock_metadata':True,'image_sha256':True}

@contextlib.contextmanager
def fixture():
    class Handler(BaseHTTPRequestHandler):
        payload=READY.copy();body=None;status=200;extra=[];auth=None
        gets=0;posts=0;frame=0
        def log_message(self,*args):pass
        def do_GET(self):
            type(self).gets+=1
            assert self.path=='/api/v1/camera'
            type(self).auth=self.headers.get('Authorization')
            blob=self.body if self.body is not None else json.dumps(self.payload).encode()
            self.send_response(self.status)
            self.send_header('Content-Type','application/json')
            self.send_header('Content-Length',str(len(blob)))
            for k,v in self.extra:self.send_header(k,v)
            self.end_headers();self.wfile.write(blob)
        def do_POST(self):
            type(self).posts+=1;type(self).frame+=1
            assert self.path=='/api/v1/capture'
            self.rfile.read(int(self.headers['Content-Length']))
            self.send_response(200);self.send_header('Content-Type','image/jpeg')
            self.send_header('Content-Length',str(len(JPEG)))
            for k,v in headers(str(self.frame)).items():self.send_header(k,v)
            self.end_headers();self.wfile.write(JPEG)
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=lambda:server.serve_forever(poll_interval=.01));thread.start()
    try:yield Camera(f'http://127.0.0.1:{server.server_port}'),Handler
    finally:server.shutdown();thread.join();server.server_close()

class CameraStatusTests(unittest.TestCase):
    def test_passive_check_authenticates_without_capture_or_echoing_extra_fields(self):
        with fixture() as (camera,device):
            device.payload['private']='PRIVATE-CREDENTIAL'
            camera.token='fixture-token'
            self.assertEqual(camera.readiness(),READY)
            self.assertEqual(device.auth,'Bearer fixture-token')
            self.assertEqual((device.gets,device.posts),(1,0))
    def test_strict_protocol_and_ready_consistency(self):
        for key,value in [('protocol_version',True),('protocol_version',2),
                          ('capture_method','GET'),('capture_path','/other'),
                          ('image_sha256',False),('settings_ready',False),
                          ('clock_synchronized',False),('camera_available',None),
                          ('mode',[]),('state',{})]:
            with self.subTest(key=key,value=value),self.assertRaises(ValueError):
                validate(READY|{key:value})
    def test_malformed_duplicate_or_ambiguous_response_does_not_capture(self):
        with fixture() as (camera,device):
            for body,extra in [(b'not json',[]),(b'{"state":"ready","state":"busy"}',[]),
                               (json.dumps(READY).encode(),[('Content-Length','1')]),
                               (json.dumps(READY).encode(),[('Content-Type','text/plain')]),
                               (json.dumps(READY).encode(),[('Transfer-Encoding','chunked')])]:
                device.body,device.extra=body,extra
                with self.subTest(body=body,extra=extra),self.assertRaises(ValueError):camera.readiness()
            self.assertEqual(device.posts,0)
    def test_errors_are_sanitized_without_immediate_retries(self):
        with fixture() as (camera,device):
            device.body=b'PRIVATE-CREDENTIAL'
            for status,code in [(401,'camera_authentication_failed'),(404,'camera_api_unavailable'),(500,'camera_http_error')]:
                device.status=status
                with self.subTest(status=status),self.assertRaisesRegex(ValueError,'^'+code+'$'):camera.readiness()
            self.assertEqual((device.gets,device.posts),(3,0))
    def test_collector_waits_for_readiness_then_resumes_on_next_cycle(self):
        with fixture() as (camera,device),tempfile.TemporaryDirectory() as directory:
            store=Store(directory);collector=Collector(store,camera,30)
            for state,code,changes in [
                ('busy','camera_busy',{'camera_available':None}),
                ('settings_unavailable','camera_settings_unavailable',{'settings_ready':False}),
                ('startup_recovery','camera_startup_recovery',{'settings_ready':False}),
                ('clock_unsynchronized','camera_clock_unsynchronized',{'clock_synchronized':False}),
                ('camera_unavailable','camera_unavailable',{'camera_available':False}),
                ('demo_mode','camera_demo_mode',{})]:
                device.payload=READY|{'state':state}|changes
                collector.once()
                self.assertEqual(collector.last_error['error'],code)
                self.assertEqual(collector.camera_state['state'],state)
                self.assertEqual((device.posts,store.status()['captures']),(0,0))
            device.payload=READY.copy();collector.once()
            self.assertIsNone(collector.last_error)
            self.assertEqual(collector.camera_state['state'],'ready')
            self.assertEqual((device.gets,device.posts,store.status()['captures']),(7,1,1))
            self.assertFalse(store.status()['training_allowed'])
    def test_connection_failure_is_visible_and_does_not_capture(self):
        with fixture() as (camera,device),tempfile.TemporaryDirectory() as directory:
            collector=Collector(Store(directory),camera,30)
            with patch.object(camera,'readiness',side_effect=ValueError('camera_connection_failed')):
                collector.once()
            self.assertEqual(collector.camera_state['state'],'unavailable')
            self.assertEqual(collector.last_error['error'],'camera_connection_failed')
            self.assertEqual((device.gets,device.posts),(0,0))

if __name__=='__main__':unittest.main()
