"""Real JPEG/model pipeline behind a simulated camera, confined to temporary storage.
The fixture timestamp is simulated transport metadata, not the photograph's time.
"""
import hashlib,json,os,tempfile,threading,unittest
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from capture import Camera,Collector,Store,now
from reader import Reader
from recognition import Recognition

@unittest.skipUnless(all(os.environ.get(k) for k in ('AIEDGE_NATIVE_LIBRARY','AIEDGE_CALIBRATION_FIXTURE','AIEDGE_MODELS_FIXTURE','AIEDGE_JPEG_FIXTURE')),'real inference/transport fixtures not supplied')
class CapturePipelineTests(unittest.TestCase):
    def test_remote_transport_store_infer_restart(self):
        blob=Path(os.environ['AIEDGE_JPEG_FIXTURE']).read_bytes();digest=hashlib.sha256(blob).hexdigest()
        class Fixture(BaseHTTPRequestHandler):
            count=0;bad_hash=False
            def log_message(self,*args):pass
            def do_GET(self):
                from test_camera_status import READY
                body=json.dumps(READY).encode()
                self.send_response(200);self.send_header('Content-Type','application/json')
                self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
            def do_POST(self):
                self.rfile.read(int(self.headers.get('Content-Length','0')));Fixture.count+=1
                self.send_response(200);self.send_header('Content-Type','image/jpeg');self.send_header('Content-Length',str(len(blob)))
                self.send_header('X-AIEdge-Frame-Id','simulation-'+str(Fixture.count));self.send_header('X-AIEdge-Captured-At',now())
                self.send_header('X-AIEdge-SHA256','0'*64 if Fixture.bad_hash else digest);self.end_headers();self.wfile.write(blob)
        server=ThreadingHTTPServer(('127.0.0.1',0),Fixture);thread=threading.Thread(target=server.serve_forever);thread.start()
        try:
            document=json.loads(Path(os.environ['AIEDGE_CALIBRATION_FIXTURE']).read_text(encoding='utf-8'))
            reader=Reader(os.environ['AIEDGE_NATIVE_LIBRARY'],os.environ['AIEDGE_MODELS_FIXTURE'],document)
            with tempfile.TemporaryDirectory() as directory:
                store=Store(directory);collector=Collector(store,Camera(f'http://127.0.0.1:{server.server_port}'),30);worker=Recognition(store,reader)
                collector.once();self.assertEqual(store.status()['captures'],1);self.assertTrue(worker.once())
                result=worker.latest();self.assertEqual(result['state'],'estimated',result);self.assertEqual(len(result['dial_positions']),6)
                self.assertFalse(result['training_allowed']);self.assertFalse(result['accuracy_verified']);self.assertIsNone(result['physical_value'])
                collector.once();self.assertEqual(store.status()['captures'],2);self.assertEqual(store.status()['unique_images'],1);self.assertFalse(worker.once())
                restored=Recognition(Store(directory),reader);self.assertEqual(restored.latest(),result)
                Fixture.bad_hash=True;collector.once();self.assertEqual(store.status()['captures'],2);self.assertEqual(store.status()['last_error']['error'],'image_hash_mismatch')
                self.assertEqual(restored.latest(),result)
        finally:server.shutdown();thread.join();server.server_close()
