"""Synthetic SQLite startup and accounting guards; no camera or native inference."""
import copy,datetime,hashlib,json,tempfile,unittest
from unittest.mock import patch
from capture import Store
from event_recognition import EventRecognition
import consumption
from reading_format import FormatStore

PIPELINE='a'*64
DOC={'version':1,'pipeline_id':PIPELINE,'unit':'ft3','dials':[{'index':i,'value_per_revolution':p,'position_error':.01} for i,p in enumerate([10000,1000,5])]}
CONFIG={'normal_interval_seconds':10,'urgent_interval_seconds':2,'full_refresh_seconds':20,'phase_probe_budget':.2,'uncertainty_probe_width':.4}
CAPS={'minimum_interval_seconds':1,'partial_recognition':True}

class FakeReader:
    def __init__(self,pipeline=PIPELINE):self.pipeline_id=pipeline;self.dials=[{'name':str(i)} for i in range(3)];self.calls=[]
    def read_jpeg(self,blob,observed=None):
        self.calls.append(hashlib.sha256(blob).hexdigest())
        mask=[True]*3 if observed is None else list(observed)
        result={'state':'estimated','pipeline_id':self.pipeline_id,'source_sha256':self.calls[-1],
                'training_allowed':False,'accuracy_verified':False,
                'dial_positions':[{'state':'estimated' if flag else 'unavailable','position':1. if flag else None} for flag in mask]}
        if observed is not None:result['observation_support']={'schema_version':1,'source_sha256':self.calls[-1],'pipeline_id':self.pipeline_id,'observed':mask}
        return result

class FakeTracker:
    def close(self):pass
class FakeNative:
    identity='synthetic-native-only'
    def __init__(self,*args):self.calls=[]
    def tracker(self,document):self.calls.append(copy.deepcopy(document));return FakeTracker()

class FutureContextFloorTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='aiedge-future-context-')
        self.addCleanup(self.temp.cleanup)
        self.store=Store(self.temp.name);self.reader=FakeReader();self.n=0
    def worker(self,reader=None,document=None,config=None):
        return EventRecognition(self.store,reader or self.reader,document or DOC,config or CONFIG,CAPS)
    def capture(self):
        self.n+=1;blob=b'\xff\xd8'+str(self.n).encode()+b'\xff\xd9';digest=hashlib.sha256(blob).hexdigest()
        stamp=(datetime.datetime(2026,10,3,tzinfo=datetime.timezone.utc)+datetime.timedelta(seconds=self.n)).isoformat()
        self.store.add('synthetic-only',blob,{'X-AIEdge-Frame-Id':str(self.n),'X-AIEdge-Captured-At':stamp,'X-AIEdge-SHA256':digest,'X-AIEdge-Clock-Id':'synthetic-boot','X-AIEdge-Capture-Monotonic-Us':str(self.n*1000000)})
        with self.store.connect() as db:event=db.execute('SELECT MAX(event_id) FROM capture_events').fetchone()[0]
        return event,digest
    def snapshot(self,tables):
        with self.store.connect() as db:return {t:list(db.execute('SELECT * FROM '+t+' ORDER BY rowid')) for t in tables}
    def consumer(self,worker):
        formats=FormatStore(self.temp.name,worker);formats.save(DOC,formats.status()['revision'])
        with patch.object(consumption,'AccountingNative',FakeNative):c=consumption.Consumption(self.store,worker,formats,'synthetic-not-a-library')
        self.addCleanup(c._drop);return c
    def old_segment(self,c):
        with self.store.connect() as db:
            db.execute('INSERT INTO consumption_segments VALUES(?,?,?,?,?,?)',('old-segment',c.formats.active[1],'old-engine',1,'first_capture',json.dumps(DOC)))
            db.execute('INSERT INTO consumption_active VALUES(1,?)',('old-segment',))
    def test_empty_store_floor_is_one_and_no_inference(self):
        w=self.worker();self.assertEqual(w.observation_first_event,1);self.assertFalse(w.once());self.assertEqual(self.reader.calls,[])
    def test_new_context_starts_after_all_existing_events(self):
        for _ in range(3):self.capture()
        w=self.worker();self.assertEqual(w.observation_first_event,4);self.assertFalse(w.once());self.assertEqual(self.reader.calls,[])
        with self.store.connect() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM event_recognition_requests').fetchone()[0],0)
    def test_pending_floor_restart_before_first_future_capture(self):
        self.capture();w=self.worker();context=w.observation_context
        w=self.worker();self.assertEqual(w.observation_context,context);self.assertEqual(w.observation_first_event,2);self.assertFalse(w.once())
        e,d=self.capture();self.assertTrue(w.once());self.assertEqual(self.reader.calls,[d]);self.assertEqual(w.event_result(e,d,PIPELINE)['state'],'estimated')
    def test_empty_pending_floor_restart(self):
        w=self.worker();again=self.worker();self.assertEqual(again.observation_first_event,1);self.assertEqual(again.observation_context,w.observation_context);self.assertFalse(again.once())
    def test_new_pipeline_preserves_old_terminal_and_context_rows(self):
        old=self.worker();e,d=self.capture();self.assertTrue(old.once())
        tables=['event_selection_contexts','event_recognition_requests','event_recognition_cache','event_recognition_bindings']
        before=self.snapshot(tables);reader=FakeReader('b'*64);document={**DOC,'pipeline_id':reader.pipeline_id};new=self.worker(reader,document)
        self.assertEqual(new.observation_first_event,2);self.assertFalse(new.once());self.assertEqual(reader.calls,[])
        later,source=self.capture();self.assertTrue(new.once());self.assertEqual(reader.calls,[source])
        after=self.snapshot(tables)
        for t,rows in before.items():
            for row in rows:self.assertIn(row,after[t])
    def test_completed_existing_context_restart_reuses_saved_terminal(self):
        w=self.worker();e,d=self.capture();self.assertTrue(w.once());saved=w.event_result(e,d,PIPELINE)
        before=self.snapshot(['event_recognition_requests','event_recognition_cache','event_recognition_bindings']);calls=list(self.reader.calls)
        again=self.worker();self.assertEqual(again.observation_first_event,1);self.assertFalse(again.once());self.assertEqual(again.event_result(e,d,PIPELINE),saved);self.assertEqual(self.reader.calls,calls);self.assertEqual(self.snapshot(before),before)
    def test_existing_context_retains_authorized_pending_recovery(self):
        w=self.worker();e,d=self.capture();again=self.worker();self.assertEqual(again.observation_first_event,1);self.assertTrue(again.once());self.assertEqual(self.reader.calls,[d])
    def test_cache_commit_recovery_does_not_repeat_inference(self):
        w=self.worker();e,d=self.capture();original=w._request;count=[0]
        def fail_final(db,event):
            count[0]+=1
            if count[0]==2:raise RuntimeError('synthetic_after_cache_commit')
            return original(db,event)
        with patch.object(w,'_request',side_effect=fail_final):
            with self.assertRaisesRegex(RuntimeError,'synthetic_after_cache_commit'):w.once()
        calls=list(self.reader.calls);again=self.worker();self.assertTrue(again.once());self.assertEqual(self.reader.calls,calls)
    def test_far_future_saved_floor_rejects(self):
        self.capture();w=self.worker()
        with self.store.connect() as db:db.execute('UPDATE event_selection_contexts SET first_event=3 WHERE context=?',(w.observation_context,))
        with self.assertRaisesRegex(ValueError,'event_context_saved_invalid'):self.worker()
    def test_zero_saved_floor_rejects(self):
        w=self.worker()
        with self.store.connect() as db:db.execute('UPDATE event_selection_contexts SET first_event=0 WHERE context=?',(w.observation_context,))
        with self.assertRaisesRegex(ValueError,'event_context_saved_invalid'):self.worker()
    def test_consumer_waits_without_creating_or_moving_old_segment(self):
        self.capture();w=self.worker();c=self.consumer(w);self.old_segment(c)
        tables=['consumption_segments','consumption_active','consumption_records','consumption_segment_links'];before=self.snapshot(tables)
        self.assertFalse(c.once());self.assertIsNone(c.segment);self.assertEqual(c.native.calls,[]);self.assertEqual(c.status()['reason'],'consumption_waiting_for_context_first_capture');self.assertEqual(self.snapshot(tables),before)
        again=self.worker();other=self.consumer(again);self.assertFalse(other.once());self.assertEqual(self.snapshot(tables),before)
    def test_consumer_new_segment_begins_only_at_actual_future_event(self):
        self.capture();w=self.worker();c=self.consumer(w);self.old_segment(c);self.assertFalse(c.once())
        event,digest=self.capture();self.assertFalse(c.once())
        self.assertEqual(c.segment['first_event'],event);self.assertEqual(c.segment['prior_segment_id'],'old-segment');self.assertEqual(c.segment['unresolved_gap']['reason'],'interpretation_changed');self.assertIsNone(c.segment['unresolved_gap']['delta'])
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM consumption_records').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM consumption_segments WHERE segment_id=?',('old-segment',)).fetchone()[0],1)
        self.assertEqual(self.reader.calls,[])
    def test_consumer_empty_store_does_not_create_empty_segment(self):
        w=self.worker();c=self.consumer(w);self.assertFalse(c.once())
        with self.store.connect() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM consumption_segments').fetchone()[0],0)
    def test_consumer_corrupt_floor_does_not_mutate_segments(self):
        self.capture();w=self.worker();c=self.consumer(w);self.old_segment(c);before=self.snapshot(['consumption_segments','consumption_active']);w.observation_first_event=3
        with self.assertRaisesRegex(ValueError,'invalid_consumption_observation_floor'):c.once()
        self.assertEqual(self.snapshot(before),before)


if __name__=='__main__':unittest.main()
