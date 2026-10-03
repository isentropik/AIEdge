"""Late/restarted observers recover immutable trial evidence without camera I/O."""
import copy,hashlib,json,sqlite3,tempfile,threading,unittest,urllib.error,urllib.request
from http.server import ThreadingHTTPServer
from capture import Store,validate
from recognition import Recognition
from capture_trial import CaptureTrial
from service import handler
from trial_results import build
from test_capture import headers

ID='a'*32
PIPE='b'*64

class Reader:
    pipeline_id=PIPE
    def __init__(self):self.calls=0
    def read_jpeg(self,raw):
        self.calls+=1
        return {'state':'estimated','dial_positions':[{'name':'dial','state':'estimated','position':2.5}],
                'physical_value':None,'model_hashes':{'main':'c'*64}}

class ResultsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.store=Store(self.temp.name)
        self.reader=Reader();self.worker=Recognition(self.store,self.reader)
        self.trial=CaptureTrial(self.store,None,lambda:False)
        self.trial.recover()
    def tearDown(self):self.temp.cleanup()
    def save_trial(self, *, count=3,duplicate=False,state='completed'):
        frames=[]
        for number in range(count):
            raw=b'\xff\xd8'+(b'same' if duplicate else str(number).encode())+b'\xff\xd9'
            h=headers(str(number+1),raw)
            self.store.add('fixture',raw,h)
            frame,stamp,digest=validate(raw,h)
            frames.append(dict(frame_id=frame,captured_at=stamp,
                sha256=hashlib.sha256(raw).hexdigest(),clock_id='clock',monotonic_us=number*30_000_000,added=True))
        value=dict(request_id=ID,max_attempts=3,duration_seconds=90,interval_seconds=30,job='d'*32,
            state=state,started_at='2026-10-03T00:00:00+00:00',finished_at='2026-10-03T00:01:01+00:00'
            if state in ('completed','failed','interrupted','cancelled','expired') else None,
            attempts=count,saved_frames=count,unique_images=len({f['sha256'] for f in frames}),
            duplicate_images=count-len({f['sha256'] for f in frames}),missed_slots=0,frames=frames,
            error='trial_interrupted' if state=='interrupted' else None,in_flight=False,
            counts_complete=state!='interrupted',capture_outcome_uncertain=state=='interrupted',
            context=dict(pipeline_id=PIPE,calibration_revision='e'*64,format_revision='f'*64),
            training_allowed=False,accuracy_verified=False)
        with self.store.connect() as db:
            db.execute('INSERT INTO capture_trials VALUES(?,?)',(ID,json.dumps(value)))
        return value
    def process(self):
        while self.worker.once():pass
    def rows(self):
        with self.store.connect() as db:
            return {name:db.execute('SELECT * FROM '+name).fetchall()
                    for name in ('frames','capture_events','inference','capture_trials')}
    def test_late_observer_recovers_all_three_after_latest_has_moved(self):
        trial=self.save_trial();self.process()
        extra=b'\xff\xd8newer\xff\xd9';self.store.add('fixture',extra,headers('later',extra));self.process()
        before=self.rows();calls=self.reader.calls
        result=build(self.trial,self.worker,ID)
        self.assertEqual(result['state'],'complete');self.assertTrue(result['processing_complete'])
        self.assertEqual(result['processing'],dict(estimated=3,rejected=0,pending=0,unavailable=0))
        self.assertEqual([v['result']['source_sha256'] for v in result['frames']],[f['sha256'] for f in trial['frames']])
        self.assertNotIn(self.worker.latest()['source_sha256'],[v['frame']['sha256'] for v in result['frames']])
        self.assertEqual(before,self.rows());self.assertEqual(calls,self.reader.calls)
        self.assertFalse(result['training_allowed']);self.assertFalse(result['accuracy_verified'])
    def test_restart_and_changed_reader_keep_original_pipeline(self):
        self.save_trial();self.process();before=self.rows()
        reader=Reader();reader.pipeline_id='0'*64
        worker=Recognition(Store(self.temp.name),reader)
        trial=CaptureTrial(worker.store,None,lambda:False);trial.recover()
        result=build(trial,worker,ID)
        self.assertEqual(result['processing']['estimated'],3);self.assertEqual(reader.calls,0)
        self.assertTrue(all(v['result']['pipeline_id']==PIPE for v in result['frames']))
        self.assertEqual(before,self.rows())
    def test_duplicates_keep_three_frames_but_one_inference(self):
        self.save_trial(duplicate=True);self.process();result=build(self.trial,self.worker,ID)
        self.assertEqual(len(result['frames']),3);self.assertEqual(result['unique_images'],1)
        self.assertEqual(result['processing']['estimated'],1);self.assertEqual(self.reader.calls,1)
        self.assertEqual(len({v['frame']['frame_id'] for v in result['frames']}),3)
    def test_pending_read_never_runs_model(self):
        self.save_trial();before=self.rows();result=build(self.trial,self.worker,ID)
        self.assertEqual(result['state'],'pending');self.assertFalse(result['processing_complete'])
        self.assertEqual(result['processing']['pending'],3);self.assertEqual(self.reader.calls,0)
        self.assertTrue(all(v['processed_at'] is None for v in result['frames']))
        self.assertEqual(before,self.rows())
    def test_rejection_is_retained_not_retried_or_counted_as_estimate(self):
        self.save_trial(count=1)
        def reject(raw):raise ValueError('alignment_rejected')
        self.reader.read_jpeg=reject;self.process();before=self.rows()
        result=build(self.trial,self.worker,ID)
        self.assertEqual(result['state'],'complete');self.assertEqual(result['processing']['rejected'],1)
        self.assertEqual(result['frames'][0]['result']['error'],'alignment_rejected')
        self.assertEqual(before,self.rows())
    def test_damaged_or_oversized_result_is_explicit_and_not_rewritten(self):
        self.save_trial(count=1);self.process()
        with self.store.connect() as db:original=db.execute('SELECT result FROM inference').fetchone()[0]
        for encoded in ('{broken',json.dumps(dict(json.loads(original),source_sha256='0'*64)),
                        json.dumps(dict(json.loads(original),training_allowed=True)),
                        json.dumps(dict(json.loads(original),padding='x'*262144))):
            with self.subTest(encoded=encoded[:40]):
                with self.store.connect() as db:db.execute('UPDATE inference SET result=?',(encoded,))
                before=self.rows();result=build(self.trial,self.worker,ID)
                self.assertEqual(result['state'],'unavailable');self.assertEqual(result['processing']['unavailable'],1)
                self.assertFalse(result['processing_complete']);self.assertEqual(before,self.rows())
    def test_processed_timestamp_corruption_is_not_claimed_verified(self):
        self.save_trial(count=1);self.process()
        with self.store.connect() as db:db.execute('UPDATE inference SET processed_at=?',('not-a-time',))
        before=self.rows();result=build(self.trial,self.worker,ID)
        self.assertEqual(result['state'],'unavailable');self.assertEqual(before,self.rows())
    def test_journal_frame_substitution_cannot_borrow_another_result(self):
        snapshot=self.save_trial();self.process();snapshot['frames'][1]['frame_id']='different-frame'
        with self.store.connect() as db:db.execute('UPDATE capture_trials SET document=?',(json.dumps(snapshot),))
        before=self.rows();result=build(self.trial,self.worker,ID)
        self.assertEqual(result['state'],'unavailable');self.assertEqual(result['processing']['unavailable'],1)
        self.assertEqual(result['frames'][1]['result']['error'],'trial_frame_missing');self.assertEqual(before,self.rows())
    def test_empty_active_trial_is_pending(self):
        self.save_trial(count=0,state='queued');result=build(self.trial,self.worker,ID)
        self.assertEqual(result['state'],'pending');self.assertFalse(result['processing_complete'])
    def test_interrupted_trial_keeps_uncertain_capture_separate_from_processing(self):
        self.save_trial(count=1,state='interrupted');self.process();result=build(self.trial,self.worker,ID)
        self.assertTrue(result['processing_complete']);self.assertTrue(result['capture_outcome_uncertain'])
        self.assertFalse(result['counts_complete']);self.assertEqual(result['trial_state'],'interrupted')
    def test_unknown_trial_and_unavailable_reader_do_not_use_latest(self):
        self.save_trial();self.process()
        self.assertEqual(build(self.trial,self.worker,'0'*32)['state'],'not_found')
        self.assertEqual(build(self.trial,None,ID)['error'],'trial_reader_unavailable')
    def test_http_is_bounded_read_only_and_validates_exact_query(self):
        self.save_trial();self.process();before=self.rows()
        server=ThreadingHTTPServer(('127.0.0.1',0),handler(self.store,False,None,self.worker,trial=self.trial))
        thread=threading.Thread(target=server.serve_forever);thread.start()
        origin='http://127.0.0.1:'+str(server.server_port)
        try:
            for query in ('','?request_id=','?request_id=bad','?request_id='+ID+'&request_id='+ID,
                          '?request_id='+ID+'&pipeline='+'0'*64):
                with self.subTest(query=query),self.assertRaises(urllib.error.HTTPError) as caught:
                    urllib.request.urlopen(origin+'/api/capture-trial/results'+query)
                self.assertEqual(caught.exception.code,400)
            with urllib.request.urlopen(origin+'/api/capture-trial/results?request_id='+ID) as response:
                self.assertEqual(response.headers['Cache-Control'],'no-store');result=json.load(response)
            self.assertEqual(result['processing']['estimated'],3);self.assertEqual(before,self.rows())
            self.assertEqual(self.reader.calls,3)
        finally:server.shutdown();thread.join();server.server_close()

if __name__=='__main__':unittest.main()
