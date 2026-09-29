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
    def test_corrupt_disk_rejected(self):
        self.store.add('camera',JPEG,headers());next((Path(self.temp.name)/'images').glob('*.jpg')).write_bytes(b'broken')
        with self.assertRaisesRegex(ValueError,'corrupt'):self.store.add('camera',JPEG,headers('2'))
    def test_fixture_camera_and_no_redirect(self):
        class Fixture(BaseHTTPRequestHandler):
            mode='ok';calls=0
            def log_message(self,*args):pass
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
