import json,tempfile,unittest,threading,urllib.request
from http.server import ThreadingHTTPServer
from service import handler
from pathlib import Path
from capture import Store
from recognition import Recognition
from test_capture import JPEG,headers

class Reader:
    pipeline_id='test-v1'
    calls=0
    def read_jpeg(self,blob):
        self.calls+=1
        return {'state':'estimated','physical_value':None,'dial_positions':[{'position':2.5}]}

class Tests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.store=Store(self.temp.name);self.reader=Reader();self.worker=Recognition(self.store,self.reader)
    def tearDown(self):self.temp.cleanup()
    def test_restart_and_duplicate_image_processed_once(self):
        self.store.add('camera',JPEG,headers());self.store.add('camera',JPEG,headers('2'))
        self.assertTrue(self.worker.once());self.assertFalse(self.worker.once());self.assertEqual(self.reader.calls,1)
        restarted=Recognition(Store(self.temp.name),Reader());self.assertFalse(restarted.once())
        result=restarted.latest();self.assertEqual(result['state'],'estimated');self.assertFalse(result['accuracy_verified']);self.assertFalse(result['training_allowed'])
    def test_new_image_cannot_show_previous_result(self):
        self.store.add('camera',JPEG,headers());self.worker.once()
        other=b'\xff\xd8other\xff\xd9';self.store.add('camera',other,headers('2',other))
        self.assertEqual(self.worker.latest()['state'],'pending')
        self.assertNotIn('dial_positions',self.worker.latest())
    def test_pipeline_change_requires_new_result(self):
        self.store.add('camera',JPEG,headers());self.worker.once();self.reader.pipeline_id='test-v2'
        self.assertEqual(self.worker.latest()['state'],'pending');self.assertTrue(self.worker.once());self.assertEqual(self.reader.calls,2)
    def test_corruption_rejected_without_model_call(self):
        self.store.add('camera',JPEG,headers());next((Path(self.temp.name)/'images').glob('*.jpg')).write_bytes(b'bad')
        self.assertTrue(self.worker.once());self.assertEqual(self.worker.latest()['error'],'stored_image_corrupt');self.assertEqual(self.reader.calls,0)
        self.assertFalse(self.worker.once())
    def test_inference_failure_is_durable_and_keeps_raw(self):
        self.store.add('camera',JPEG,headers())
        def fail(blob):raise ValueError('alignment_rejected')
        self.reader.read_jpeg=fail;self.worker.once()
        self.assertEqual(self.worker.latest()['error'],'alignment_rejected');self.assertEqual(self.store.status()['captures'],1)
        self.assertFalse(self.worker.once())
    def test_damaged_result_is_preserved_and_not_shown_as_a_reading(self):
        self.store.add('camera',JPEG,headers());self.worker.once()
        original=self.worker.latest()
        cases=['{broken','null',json.dumps(dict(original,source_sha256='0'*64)),
               json.dumps(dict(original,processing_seconds=float('inf'))),
               json.dumps(dict(original,dial_positions='not a list')),
               json.dumps(dict(original,training_allowed=True)),
               json.dumps(dict(original,accuracy_verified=True)),
               json.dumps(dict(original,training_allowed=0)),
               json.dumps(dict(original,padding='x'*262144))]
        for encoded in cases:
            with self.subTest(encoded=encoded):
                with self.store.connect() as db:
                    db.execute('UPDATE inference SET result=?',(encoded,))
                result=self.worker.latest()
                self.assertEqual(result['state'],'unavailable')
                self.assertEqual(result['error'],'stored_result_invalid')
                self.assertFalse(self.worker.once())
                self.assertFalse(result['training_allowed'])
                with self.store.connect() as db:
                    self.assertEqual(db.execute('SELECT result FROM inference').fetchone()[0],encoded)
                self.assertEqual(self.store.image(original['source_sha256']),JPEG)
    def test_latest_capture_has_priority_then_history_drains_in_order(self):
        images=[]
        for number in range(1,8):
            blob=b'\xff\xd8'+str(number).encode()+b'\xff\xd9'
            self.store.add('camera',blob,headers(str(number),blob));images.append(blob)
        seen=[]
        def read(blob):
            seen.append(blob)
            return {'state':'estimated','dial_positions':[],'physical_value':None}
        self.reader.read_jpeg=read
        self.assertEqual(self.worker.latest()['state'],'pending')
        self.assertTrue(self.worker.once())
        self.assertEqual(seen,[images[-1]])
        self.assertEqual(self.worker.latest()['state'],'estimated')
        while self.worker.once():pass
        self.assertEqual(seen,[images[-1],*images[:-1]])
    def test_new_arrival_interrupts_history_priority_without_losing_history(self):
        seen=[]
        def read(blob):
            seen.append(blob)
            return {'state':'estimated','dial_positions':[],'physical_value':None}
        self.reader.read_jpeg=read
        for number in range(1,4):
            blob=b'\xff\xd8'+str(number).encode()+b'\xff\xd9'
            self.store.add('camera',blob,headers(str(number),blob))
        self.worker.once();self.worker.once()
        blob=b'\xff\xd8new\xff\xd9';self.store.add('camera',blob,headers('4',blob))
        self.assertEqual(self.worker.latest()['state'],'pending');self.worker.once()
        self.assertEqual(seen[-1],blob);self.assertEqual(self.worker.latest()['state'],'estimated')
        self.worker=Recognition(Store(self.temp.name),self.reader)
        while self.worker.once():pass
        self.assertEqual(seen,[b'\xff\xd83\xff\xd9',b'\xff\xd81\xff\xd9',blob,b'\xff\xd82\xff\xd9'])
    def test_api_reports_result_for_current_image(self):
        self.store.add('camera',JPEG,headers());self.worker.once()
        server=ThreadingHTTPServer(('127.0.0.1',0),handler(self.store,False,None,self.worker));thread=threading.Thread(target=server.serve_forever);thread.start()
        try:
            with urllib.request.urlopen('http://127.0.0.1:'+str(server.server_port)+'/api/status') as response:status=json.load(response)
            self.assertEqual(status['recognition']['source_sha256'],status['latest']['sha256'])
            self.assertEqual(status['recognition']['state'],'estimated')
            self.assertIsNone(status['recognition']['physical_value'])
        finally:server.shutdown();thread.join();server.server_close()
if __name__=='__main__':unittest.main()
