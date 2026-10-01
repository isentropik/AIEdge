"""Local data protection and stopped-app restore; no Supervisor simulation."""
import hashlib, shutil, sqlite3, tempfile, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from capture import Store, Collector, MIN_FREE_BYTES, MAX_IMAGE
from recognition import Recognition
from setup_store import Setup
from test_capture import JPEG, headers
from test_setup import Candidate, DESIGN, reference

class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)/'data'
        self.store=Store(self.root)
    def tearDown(self):self.temp.cleanup()
    def disk(self,free):return patch('capture.shutil.disk_usage',return_value=SimpleNamespace(free=free))
    def test_low_space_prevents_camera_request_and_recovers(self):
        camera=Mock(origin='fixture');camera.readiness.return_value={'state':'ready'};camera.capture.return_value=(JPEG,headers())
        collector=Collector(self.store,camera,30)
        with self.disk(MIN_FREE_BYTES):
            collector.once();camera.capture.assert_not_called()
            self.assertEqual(collector.last_error['error'],'storage_low_space')
            self.assertEqual(self.store.status()['storage']['state'],'low_space')
            self.assertEqual(self.store.status()['captures'],0)
        with self.disk(MIN_FREE_BYTES+MAX_IMAGE):collector.once()
        self.assertIsNone(collector.last_error)
        self.assertEqual(self.store.status()['captures'],1)
    def test_space_is_rechecked_after_download_without_overwriting_history(self):
        self.store.add('fixture',JPEG,headers())
        prior=self.store.recent()
        with self.disk(MIN_FREE_BYTES):
            with self.assertRaisesRegex(ValueError,'storage_low_space'):
                other=b'\xff\xd8new\xff\xd9'
                self.store.add('fixture',other,headers('2',other))
        self.assertEqual(self.store.recent(),prior)
        self.assertEqual(list((self.root/'images').iterdir()),[self.root/'images'/(hashlib.sha256(JPEG).hexdigest()+'.jpg')])
    def test_duplicate_image_needs_only_metadata_space(self):
        self.store.add('fixture',JPEG,headers())
        with self.disk(MIN_FREE_BYTES):self.assertTrue(self.store.add('fixture',JPEG,headers('2')))
        self.assertEqual(self.store.status()['unique_images'],1)
    def test_unknown_space_does_not_capture(self):
        camera=Mock(origin='fixture');collector=Collector(self.store,camera,30)
        with patch('capture.shutil.disk_usage',side_effect=OSError('unmounted')):
            collector.once();camera.capture.assert_not_called()
            self.assertEqual(collector.last_error['error'],'storage_unavailable')
    def test_failure_to_write_error_does_not_terminate_worker(self):
        collector=Collector(self.store,Mock(origin='fixture'),30)
        with self.disk(0),patch.object(self.store,'fail',side_effect=sqlite3.OperationalError('disk full')):
            collector.once()
        self.assertEqual(collector.last_error['error'],'storage_low_space')
    def test_recognition_worker_recovers_after_database_write_failure(self):
        worker=Recognition(self.store)
        waits=[]
        def wait(delay):
            waits.append((delay,worker.last_error))
            if len(waits)==2:worker.stop.set()
        with patch.object(worker,'once',side_effect=[sqlite3.OperationalError('disk full'),False]) as once,patch.object(worker.stop,'wait',side_effect=wait):
            worker.run()
        self.assertEqual(once.call_count,2)
        self.assertEqual(waits,[(5,'recognition_storage_unavailable'),(1,None)])
    def test_http_storage_failure_is_bounded_and_recovers(self):
        import json,threading,urllib.request,urllib.error
        from http.server import ThreadingHTTPServer
        from service import handler
        server=ThreadingHTTPServer(('127.0.0.1',0),handler(self.store,False,None))
        thread=threading.Thread(target=server.serve_forever);thread.start()
        origin='http://127.0.0.1:'+str(server.server_port)
        try:
            with patch.object(self.store,'status',side_effect=sqlite3.OperationalError('private database path')):
                with self.assertRaises(urllib.error.HTTPError) as raised:urllib.request.urlopen(origin+'/api/status',timeout=2)
                with raised.exception as response:
                    self.assertEqual(response.code,503)
                    self.assertEqual(json.load(response),{'error':'Local storage is unavailable. Saved readings have not been replaced.','code':'storage_unavailable'})
                # The UI shell remains available while a data request fails.
                with urllib.request.urlopen(origin+'/',timeout=2) as response:self.assertEqual(response.status,200)
            with urllib.request.urlopen(origin+'/api/status',timeout=2) as response:self.assertEqual(json.load(response)['captures'],0)
        finally:server.shutdown();thread.join();server.server_close()
    def test_stopped_app_copy_restores_images_results_and_calibration(self):
        class FixtureReader(Candidate):
            def read_jpeg(self,blob):
                return {'state':'estimated','physical_value':None,'dial_positions':[{'position':2.5}]}
        worker=Recognition(self.store)
        setup=Setup(self.root,FixtureReader,worker)
        ref=setup.add_reference(reference());saved=setup.save(ref,DESIGN,None)
        self.store.add('fixture',JPEG,headers());self.store.add('fixture',JPEG,headers('2'))
        worker.once();result=worker.latest()
        # All connections are closed and no workers run while this directory is copied.
        restored=Path(self.temp.name)/'restored';shutil.copytree(self.root,restored)
        original={str(p.relative_to(self.root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in self.root.rglob('*') if p.is_file()}
        copied={str(p.relative_to(restored)):hashlib.sha256(p.read_bytes()).hexdigest() for p in restored.rglob('*') if p.is_file()}
        self.assertEqual(copied,original)
        store=Store(restored);recognition=Recognition(store)
        loaded=Setup(restored,FixtureReader,recognition)
        self.assertEqual(loaded.status(),saved);self.assertEqual(loaded.reference(ref),reference())
        self.assertEqual(store.recent(),self.store.recent());self.assertEqual(recognition.latest(),result)
        self.assertFalse(recognition.once());self.assertFalse(result['training_allowed'])
        self.assertEqual(store.image(result['source_sha256']),JPEG)
        with store.connect() as db:self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0],'ok')

if __name__=='__main__':unittest.main()
