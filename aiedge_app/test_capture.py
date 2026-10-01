import base64,hashlib,json,tempfile,threading,unittest,urllib.request
from email.message import Message
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from capture import Store,Camera,Collector,now
from service import handler

JPEG=b'\xff\xd8test-envelope\xff\xd9' # Transport envelope only; decoder validation is a separate pipeline stage.
def headers(frame='1',blob=JPEG):
    h=Message();h['X-AIEdge-Frame-Id']=frame;h['X-AIEdge-Captured-At']='2026-01-01T00:00:00Z';h['X-AIEdge-SHA256']=hashlib.sha256(blob).hexdigest();return h
class Tests(unittest.TestCase):
    def setUp(self):self.temp=tempfile.TemporaryDirectory();self.store=Store(self.temp.name)
    def tearDown(self):self.temp.cleanup()
    def test_dedup_and_restart(self):
        self.assertTrue(self.store.add('camera',JPEG,headers()))
        self.assertFalse(self.store.add('camera',JPEG,headers()))
        self.assertTrue(self.store.add('camera',JPEG,headers('2')))
        status=Store(self.temp.name).status();self.assertEqual((status['captures'],status['unique_images'],status['duplicate_images']),(2,1,1))
        self.assertFalse(status['training_allowed']);self.assertNotEqual(status['latest']['captured_at'],status['latest']['received_at'])
    def test_conflict_never_overwrites(self):
        self.store.add('camera',JPEG,headers());other=b'\xff\xd8different\xff\xd9'
        with self.assertRaisesRegex(ValueError,'conflict'):self.store.add('camera',other,headers(blob=other))
        self.assertEqual(self.store.status()['captures'],1)
    def test_invalid_metadata_never_saved(self):
        for key,value in [('X-AIEdge-SHA256','0'*64),('X-AIEdge-Frame-Id','../x'),('X-AIEdge-Captured-At','2026-01-01'),('X-AIEdge-Captured-At','2099-01-01T00:00:00Z')]:
            h=headers();h.replace_header(key,value)
            with self.assertRaises(ValueError):self.store.add('camera',JPEG,h)
        self.assertEqual(self.store.status()['captures'],0)
    def test_duplicate_provenance_headers_are_rejected_without_persistence(self):
        for name in ('X-AIEdge-Frame-Id','X-AIEdge-Captured-At','X-AIEdge-SHA256'):
            for duplicate in (headers()[name],'contradictory'):
                candidate=headers();candidate[name]=duplicate
                with self.subTest(header=name,identical=duplicate==headers()[name]):
                    with self.assertRaisesRegex(ValueError,'duplicate_camera_header'):self.store.add('camera',JPEG,candidate)
        self.assertEqual(self.store.status()['captures'],0)
        self.assertEqual(list((Path(self.temp.name)/'images').iterdir()),[])
    def test_malformed_metadata_remains_a_controlled_rejection(self):
        for name in ('X-AIEdge-Frame-Id','X-AIEdge-Captured-At','X-AIEdge-SHA256'):
            for value in (None,False,42):
                candidate=dict(headers().items());candidate[name]=value
                with self.subTest(header=name,value=value),self.assertRaises(ValueError):self.store.add('camera',JPEG,candidate)
        candidate=headers();candidate.replace_header('X-AIEdge-Captured-At','2'*65)
        with self.assertRaisesRegex(ValueError,'invalid_capture_time'):self.store.add('camera',JPEG,candidate)
        self.assertEqual(self.store.status()['captures'],0)
    def test_ambiguous_http_framing_is_rejected_before_reading_the_body(self):
        from unittest.mock import patch
        class Response:
            status=200;closed=False
            def __init__(self):
                self.headers=Message();self.headers['Content-Type']='image/jpeg';self.headers['Content-Length']=str(len(JPEG))
            def __enter__(self):return self
            def __exit__(self,*args):self.closed=True
            def read1(self,*args):raise AssertionError('Malformed framing body must not be read')
        cases=[('Content-Type','image/jpeg'),('Content-Length',str(len(JPEG))),('Transfer-Encoding','chunked')]
        camera=Camera('http://127.0.0.1')
        for name,value in cases:
            response=Response();response.headers[name]=value
            with self.subTest(header=name),patch.object(camera.opener,'open',return_value=response),self.assertRaises(ValueError):camera.capture()
            self.assertTrue(response.closed)
        for value in ('+5','05','5, 5','5.0','999999999'):
            response=Response();response.headers.replace_header('Content-Length',value)
            with self.subTest(length=value),patch.object(camera.opener,'open',return_value=response),self.assertRaises(ValueError):camera.capture()
            self.assertTrue(response.closed)
    def test_corrupt_disk_rejected(self):
        self.store.add('camera',JPEG,headers());next((Path(self.temp.name)/'images').glob('*.jpg')).write_bytes(b'broken')
        with self.assertRaisesRegex(ValueError,'corrupt'):self.store.add('camera',JPEG,headers('2'))
    def test_oversized_saved_image_is_rejected_and_preserved(self):
        from capture import MAX_IMAGE
        self.store.add('camera',JPEG,headers())
        path=next((Path(self.temp.name)/'images').glob('*.jpg'))
        with path.open('wb') as stream:stream.seek(MAX_IMAGE);stream.write(b'x')
        digest=headers()['X-AIEdge-SHA256']
        with self.assertRaisesRegex(ValueError,'stored_image_corrupt'):self.store.image(digest)
        with self.assertRaisesRegex(ValueError,'stored_image_corrupt'):self.store.add('camera',JPEG,headers('2'))
        self.assertEqual(path.stat().st_size,MAX_IMAGE+1)
        self.assertEqual(self.store.status()['captures'],1)
    def test_same_frame_duplicate_checks_saved_image_integrity(self):
        self.store.add('camera',JPEG,headers())
        path=next((Path(self.temp.name)/'images').glob('*.jpg'))
        path.write_bytes(b'broken')
        with self.assertRaisesRegex(ValueError,'stored_image_corrupt'):
            self.store.add('camera',JPEG,headers())
        path.unlink()
        with self.assertRaisesRegex(ValueError,'stored_image_missing'):
            self.store.add('camera',JPEG,headers())
        self.assertEqual(self.store.status()['captures'],1)
    def test_separate_store_instances_serialize_duplicate_admission(self):
        from concurrent.futures import ThreadPoolExecutor
        stores=[Store(self.temp.name) for _ in range(8)]
        barrier=threading.Barrier(len(stores))
        def add(store):
            barrier.wait(timeout=5)
            return store.add('camera',JPEG,headers())
        with ThreadPoolExecutor(max_workers=8) as pool:
            results=list(pool.map(add,stores))
        self.assertEqual(sum(results),1)
        self.assertEqual(self.store.status()['captures'],1)
        self.assertEqual(len(list((Path(self.temp.name)/'images').glob('*.jpg'))),1)
        self.assertEqual(list((Path(self.temp.name)/'images').glob('*.tmp')),[])
    def test_failed_image_commit_does_not_create_a_frame_record(self):
        from unittest.mock import patch
        with patch('capture.os.replace',side_effect=OSError('disk full')):
            with self.assertRaises(OSError):self.store.add('camera',JPEG,headers())
        self.assertEqual(self.store.status()['captures'],0)
        self.assertEqual(list((Path(self.temp.name)/'images').iterdir()),[])
        self.assertTrue(self.store.add('camera',JPEG,headers()))
    def test_fixture_camera_and_no_redirect(self):
        class Fixture(BaseHTTPRequestHandler):
            mode='ok';calls=0
            def log_message(self,*args):pass
            def do_GET(self):
                from test_camera_status import READY
                body=json.dumps(READY).encode()
                self.send_response(200);self.send_header('Content-Type','application/json')
                self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
            def do_POST(self):
                Fixture.calls+=1
                self.rfile.read(int(self.headers.get("Content-Length","0")))
                if Fixture.mode=='redirect':self.send_response(302);self.send_header('Location','http://127.0.0.1:1/secret');self.end_headers();return
                self.send_response(200);self.send_header('Content-Type','image/jpeg');self.send_header('Content-Length',str(len(JPEG)))
                for k,v in headers().items():self.send_header(k,v)
                self.end_headers();self.wfile.write(JPEG)
        server=ThreadingHTTPServer(('127.0.0.1',0),Fixture);thread=threading.Thread(target=server.serve_forever);thread.start()
        try:
            collector=Collector(self.store,Camera('http://127.0.0.1:'+str(server.server_port),'test-token'),30);collector.once()
            self.assertEqual(self.store.status()['captures'],1,self.store.status())
            Fixture.mode='redirect';collector.once();self.assertEqual(Fixture.calls,2)
            self.assertEqual(self.store.status()['last_error']['error'],'camera_redirect_rejected')
        finally:server.shutdown();thread.join();server.server_close()
    def test_http_failures_are_classified_without_leaking_response_text(self):
        class Fixture(BaseHTTPRequestHandler):
            status=503;body=b'Camera clock is not synchronized';calls=0
            def log_message(self,*args):pass
            def do_POST(self):
                Fixture.calls+=1;self.rfile.read(int(self.headers['Content-Length']))
                self.send_response(Fixture.status);self.send_header('Content-Length',str(len(Fixture.body)))
                self.end_headers();self.wfile.write(Fixture.body)
        server=ThreadingHTTPServer(('127.0.0.1',0),Fixture)
        thread=threading.Thread(target=server.serve_forever);thread.start()
        camera=Camera('http://127.0.0.1:'+str(server.server_port),token='fixture-token')
        cases=[(401,b'private details','camera_authentication_failed'),
               (404,b'old firmware page','camera_api_unavailable'),
               (409,b'private details','camera_busy'),
               (503,b'Camera clock is not synchronized','camera_clock_unsynchronized'),
               (503,b'Camera busy; retry shortly','camera_busy'),
               (503,b'Illumination failed','camera_lighting_failed'),
               (503,b'private details','camera_unavailable'),
               (503,b'private details'*100,'camera_unavailable'),
               (500,b'private details','camera_http_error')]
        try:
            for code,body,expected in cases:
                Fixture.status,Fixture.body=code,body
                with self.subTest(code=code,expected=expected):
                    with self.assertRaisesRegex(ValueError,'^'+expected+'$'):camera.capture()
            self.assertEqual(Fixture.calls,len(cases)) # No immediate capture retries.
            self.assertEqual(self.store.status()['captures'],0)
        finally:server.shutdown();thread.join();server.server_close()
    def test_network_errors_are_classified_without_arbitrary_details(self):
        import socket,ssl,urllib.error
        from unittest.mock import patch
        camera=Camera('http://127.0.0.1')
        for cause,expected in [(TimeoutError('private'),'camera_timeout'),
              (socket.gaierror('private'),'camera_name_unresolved'),
              (ssl.SSLCertVerificationError('private'),'camera_certificate_invalid'),
              (ConnectionRefusedError('private'),'camera_connection_failed')]:
            with self.subTest(expected=expected),patch.object(camera.opener,'open',side_effect=urllib.error.URLError(cause)):
                with self.assertRaisesRegex(ValueError,'^'+expected+'$'):camera.capture()
    def test_camera_authentication_and_redirect_boundary(self):
        seen=[];leaked=[]
        class Destination(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):leaked.append(self.headers.get('Authorization'));self.send_response(500);self.end_headers()
            do_GET=do_POST
        target=ThreadingHTTPServer(('127.0.0.1',0),Destination)
        class Source(BaseHTTPRequestHandler):
            redirect=False
            def log_message(self,*args):pass
            def do_POST(self):
                seen.append((self.path,self.headers.get('Authorization'),self.rfile.read(int(self.headers['Content-Length']))))
                if Source.redirect:
                    self.send_response(307);self.send_header('Location',f'http://127.0.0.1:{target.server_port}/leak');self.end_headers();return
                self.send_response(200);self.send_header('Content-Type','image/jpeg');self.send_header('Content-Length',str(len(JPEG)))
                for k,v in headers().items():self.send_header(k,v)
                self.end_headers();self.wfile.write(JPEG)
        source=ThreadingHTTPServer(('127.0.0.1',0),Source)
        threads=[threading.Thread(target=s.serve_forever) for s in (target,source)]
        for t in threads:t.start()
        origin=f'http://127.0.0.1:{source.server_port}'
        try:
            basic=Camera(origin,username='admin',password='fixture-password')
            basic.capture();Camera(origin,token='fixture-token').capture();Camera(origin).capture()
            self.assertEqual([x[1] for x in seen],['Basic '+base64.b64encode(b'admin:fixture-password').decode(),'Bearer fixture-token',None])
            self.assertTrue(all(x[0]=='/api/v1/capture' and x[2]==b'{}' for x in seen))
            Source.redirect=True
            with self.assertRaisesRegex(ValueError,'camera_redirect_rejected'):basic.capture()
            self.assertEqual(leaked,[])
        finally:
            for s in (source,target):s.shutdown();s.server_close()
            for t in threads:t.join()
    def test_ambiguous_or_malformed_credentials_rejected(self):
        for options in ({'token':'x','username':'admin','password':'x'},{'username':'admin'},{'password':'x'},{'username':'a:b','password':'x'},{'username':'admin','password':'x\nInjected: x'},{'token':'x\rInjected: x'}):
            with self.subTest(options=list(options)):
                with self.assertRaises(ValueError):Camera('http://127.0.0.1',**options)
    def test_image_access(self):
        self.store.add('camera',JPEG,headers())
        self.assertEqual(self.store.image(hashlib.sha256(JPEG).hexdigest()),JPEG)
        with self.assertRaises(ValueError):self.store.image('../captures.sqlite3')
        with self.assertRaises(FileNotFoundError):self.store.image('0'*64)
        self.assertEqual(len(self.store.recent()),1)
    def test_status_and_ingress_boundary(self):
        for ingress,expected in [(False,200),(True,403)]:
            server=ThreadingHTTPServer(('127.0.0.1',0),handler(self.store,ingress,None));thread=threading.Thread(target=server.serve_forever);thread.start()
            try:
                try:r=urllib.request.urlopen('http://127.0.0.1:'+str(server.server_port)+'/api/status');code=r.status;r.close()
                except urllib.error.HTTPError as e:code=e.code;e.close()
                self.assertEqual(code,expected)
            finally:server.shutdown();thread.join();server.server_close()
if __name__=='__main__':unittest.main()
