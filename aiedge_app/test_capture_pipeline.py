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
    def test_bounded_trial_saved_jpeg_native_inference_and_consumed_restart(self):
        from capture_trial import CaptureTrial
        from contextlib import contextmanager
        from datetime import datetime,timedelta,timezone
        from reading_format import FormatStore
        from service import capture_trial_context
        from types import SimpleNamespace
        blob=Path(os.environ['AIEDGE_JPEG_FIXTURE']).read_bytes();digest=hashlib.sha256(blob).hexdigest()
        class Clock:
            value=1000
            def __call__(self):return self.value
            def wait(self,seconds):self.value+=seconds
        clock=Clock()
        class ReplayCamera:
            origin='local-protected-replay';calls=0
            @contextmanager
            def operation(self):yield
            def require_capture(self):pass
            def readiness(self,deadline=None):return {'state':'ready'}
            def capture(self,*,deadline=None):
                self.calls+=1
                return blob,{'X-AIEdge-Frame-Id':'trial-replay-'+str(self.calls),
                    'X-AIEdge-Captured-At':(datetime(2026,1,1,tzinfo=timezone.utc)+timedelta(seconds=self.calls*30)).isoformat(),
                    'X-AIEdge-SHA256':digest,'X-AIEdge-Clock-Id':'simulated-replay',
                    'X-AIEdge-Capture-Monotonic-Us':str(self.calls*30_000_000)}
        document=json.loads(Path(os.environ['AIEDGE_CALIBRATION_FIXTURE']).read_text(encoding='utf-8'))
        reader=Reader(os.environ['AIEDGE_NATIVE_LIBRARY'],os.environ['AIEDGE_MODELS_FIXTURE'],document)
        with tempfile.TemporaryDirectory() as folder:
            store=Store(folder);camera=ReplayCamera();worker=Recognition(store,reader)
            self.assertEqual(worker.latest()['state'],'waiting_for_image')
            formats=FormatStore(folder,worker)
            scales=(10000000,1000000,100000,10000,1000,5)
            self.assertEqual(len(reader.dials),len(scales))
            formats.save(dict(version=1,pipeline_id=reader.pipeline_id,unit='ft3',dials=[
                dict(index=i,value_per_revolution=value,position_error=.1) for i,value in enumerate(scales)]),None)
            setup=SimpleNamespace(status=lambda:{'revision':reader.profile})
            context=lambda:capture_trial_context(setup,worker,formats)
            before=context();self.assertEqual(before['pipeline_id'],reader.pipeline_id)
            trial=CaptureTrial(store,camera,lambda:True,context=context,clock=clock,wait=clock.wait)
            trial.recover();request_id='e'*32;trial.start(request_id);trial.once()
            self.assertEqual(trial.status()['state'],'completed');self.assertEqual(camera.calls,3)
            self.assertEqual(store.status()['unique_images'],1);self.assertEqual(store.status()['captures'],3)
            self.assertEqual(worker.latest()['state'],'pending');self.assertEqual(context(),before)
            self.assertTrue(worker.once());self.assertFalse(worker.once());self.assertEqual(context(),before)
            inferred=worker.latest();self.assertEqual(inferred['state'],'estimated',inferred)
            self.assertEqual(len(inferred['dial_positions']),len(reader.dials));self.assertFalse(inferred['accuracy_verified'])
            self.assertFalse(inferred['training_allowed']);self.assertEqual(store.image(digest),blob)
            with store.connect() as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM inference').fetchone()[0],1)
                self.assertEqual(db.execute('SELECT SUM(training_allowed) FROM frames').fetchone()[0],0)
            restarted=CaptureTrial(Store(folder),camera,lambda:True);restarted.recover()
            self.assertEqual(restarted.start(request_id)['state'],'completed');self.assertFalse(restarted.once())
            self.assertEqual(camera.calls,3);self.assertFalse(Recognition(Store(folder),reader).once())

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
