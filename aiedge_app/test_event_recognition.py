"""Fake reader, invented capture bytes/clocks and SQLite, never real inference."""
import copy,hashlib,json,tempfile,unittest
from datetime import datetime,timedelta,timezone
from unittest.mock import patch
from capture import Store
from event_recognition import EventRecognition
from event_selection import encoded,digest

PIPELINE='a'*64
DOC={'version':1,'pipeline_id':PIPELINE,'unit':'ft3','dials':[{'index':i,'value_per_revolution':p,'position_error':.01} for i,p in enumerate([10000,1000,5])]}
CONFIG={'normal_interval_seconds':10,'urgent_interval_seconds':2,'full_refresh_seconds':20,'phase_probe_budget':.2,'uncertainty_probe_width':.4}
CAPS={'minimum_interval_seconds':1,'partial_recognition':True}
class FakeReader:
    def __init__(self):self.pipeline_id=PIPELINE;self.dials=[{'name':str(i)} for i in range(3)];self.calls=[];self.reject=False;self.wrong_support=False
    def read_jpeg(self,blob,observed=None):
        self.calls.append(None if observed is None else list(observed));mask=[True]*3 if observed is None else observed;source=hashlib.sha256(blob).hexdigest()
        result={'state':'rejected' if self.reject else 'estimated','pipeline_id':PIPELINE,'source_sha256':source,'training_allowed':False,'accuracy_verified':False,
                'dial_positions':[{'name':str(i),'state':'estimated' if flag else 'unavailable','position':1.0 if flag else None} for i,flag in enumerate(mask)]}
        if observed is not None:
            identity={'schema_version':1,'source_sha256':source,'pipeline_id':PIPELINE}
            if self.reject:result['observation_attempt']={**identity,'requested_observed':mask}
            else:result['observation_support']={**identity,'observed':[True]*3 if self.wrong_support else mask}
        return result

class EventRecognitionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.store=Store(self.temp.name);self.reader=FakeReader();self.worker=EventRecognition(self.store,self.reader,DOC,CONFIG,CAPS);self.n=0
    def tearDown(self):self.temp.cleanup()
    def capture(self,tick,repeat=False,clock='boot-a',camera='camera'):
        self.n+=1;blob=b'\xff\xd8'+(b'same' if repeat else str(self.n).encode())+b'\xff\xd9';source=hashlib.sha256(blob).hexdigest();stamp=(datetime(2026,10,3,tzinfo=timezone.utc)+timedelta(microseconds=tick)).isoformat()
        self.store.add(camera,blob,{'X-AIEdge-Frame-Id':str(self.n),'X-AIEdge-Captured-At':stamp,'X-AIEdge-SHA256':source,'X-AIEdge-Clock-Id':clock,'X-AIEdge-Capture-Monotonic-Us':str(tick)})
        with self.store.connect() as db:event=db.execute('SELECT MAX(event_id) FROM capture_events').fetchone()[0]
        return event,source
    def complete(self,tick,repeat=False,**kw):
        event,source=self.capture(tick,repeat,**kw);self.assertTrue(self.worker.once());return event,source,self.worker.event_result(event,source,PIPELINE)
    def feedback(self,event,source,state='estimated'):
        result=self.worker.event_result(event,source,PIPELINE);obs=result['event_observation'];segment='synthetic-segment'
        with self.store.connect() as db:
            previous=db.execute('SELECT result FROM consumption_records WHERE segment_id=? ORDER BY event_id LIMIT 1',('synthetic-segment',)).fetchone() if db.execute("SELECT 1 FROM sqlite_master WHERE name='consumption_records'").fetchone() else None
        anchor=json.loads(previous[0]).get('anchor_captured_at') if previous else obs['captured_at']
        value={'anchor_captured_at':anchor,'event_id':event,'source_sha256':source,'state':state,'format_id':self.worker.format_id,'segment_id':segment,'observation_context':self.worker.observation_context,'event_observation':obs}
        # Explicit manual fixture witness; this fake reader test does not prove
        # native acceptance. Actual native producer tests are separate.
        observed=result.get('observation_support',{}).get('observed',[True]*len(DOC['dials']))
        accepted=state in ('anchored','estimated','within_noise','bounded','ambiguous') and result['state']=='estimated'
        has_anchor=state=='anchored' or (previous is not None and json.loads(previous[0]).get('state')=='anchored')
        value.update(observation_accepted=accepted,observation_current_through_us=obs['monotonic_us'] if accepted else None,
                     observation_inference_sha256=digest(result) if accepted else None,
                     observation_full_anchor_event_id=1 if accepted and has_anchor else None,observation_latest_full_event_id=None,
                     observation_support={'schema_version':1,'source_sha256':source,'pipeline_id':PIPELINE,
                                          'reader_observed':observed,'document_observed':observed,'partial':not all(observed)})
        if state=='anchored':value['value']=0
        with self.store.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS consumption_segments(segment_id TEXT PRIMARY KEY,format_id TEXT,engine_id TEXT,first_event INTEGER,gap_reason TEXT,document TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS consumption_active(singleton INTEGER PRIMARY KEY,segment_id TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS consumption_records(segment_id TEXT,event_id INTEGER,result TEXT,PRIMARY KEY(segment_id,event_id))')
            db.execute('CREATE TABLE IF NOT EXISTS consumption_accepted_full_observations(segment_id TEXT,event_id INTEGER,result_sha256 TEXT,PRIMARY KEY(segment_id,event_id))')
            latest=db.execute('SELECT MAX(event_id) FROM consumption_accepted_full_observations WHERE segment_id=?',(segment,)).fetchone()[0]
            if accepted and all(observed):latest=event
            if accepted and has_anchor:value['observation_latest_full_event_id']=latest
            db.execute('INSERT OR IGNORE INTO consumption_segments VALUES(?,?,?,?,?,?)',(segment,self.worker.format_id,'synthetic-engine',1,'first_capture',encoded(DOC)))
            db.execute('INSERT OR REPLACE INTO consumption_active VALUES(1,?)',(segment,))
            db.execute('INSERT INTO consumption_records VALUES(?,?,?)',(segment,event,encoded(value)))
            if accepted and all(observed):db.execute('INSERT INTO consumption_accepted_full_observations VALUES(?,?,?)',(segment,event,digest(value)))
    def request(self,event):
        with self.store.connect() as db:return self.worker._request(db,event)
    def test_oldest_first_and_feedback_holds_next_request(self):
        e1,s1=self.capture(1000000);e2,s2=self.capture(3000000);self.assertTrue(self.worker.once());self.assertEqual(self.reader.calls,[None]);self.assertFalse(self.worker.once());self.assertIsNone(self.worker.accounting_result(e2,s2,PIPELINE));self.assertEqual(self.worker.latest()['state'],'pending');self.feedback(e1,s1,'anchored');self.assertTrue(self.worker.once());self.assertEqual(self.reader.calls,[None,[False,True,True]])
    def test_duplicate_jpeg_full_partial_periodic_full_distinct_cache_binding(self):
        e,s,x=self.complete(1000000,True);self.feedback(e,s,'anchored')
        e,s,x=self.complete(3000000,True);self.feedback(e,s)
        e,s,x=self.complete(13000000,True);self.feedback(e,s);self.assertEqual(self.reader.calls,[None,[False,True,True]])
        e,s,x=self.complete(23000000,True);self.assertTrue(all(self.request(e)['reader_observed']));self.assertIn('periodic_full',self.request(e)['recommendation']['reasons'])
        # Same FULL source/pipeline cache exists fromfirst: no needless reinference,
        # but partial cache could never satisfy thisFULL request.
        self.assertEqual(self.reader.calls,[None,[False,True,True]])
        with self.store.connect() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM event_recognition_cache').fetchone()[0],2);self.assertEqual(db.execute('SELECT COUNT(*) FROM event_recognition_bindings').fetchone()[0],4);self.assertEqual(db.execute('SELECT COUNT(*) FROM inference').fetchone()[0],0)
        self.assertEqual(x['event_observation']['event_id'],e)
    def test_partial_first_for_new_sha_then_periodic_full_requires_upper_call(self):
        e,s,_=self.complete(1000000);self.feedback(e,s,'anchored');e,s,_=self.complete(3000000,True);self.feedback(e,s);e,s,_=self.complete(13000000,True);self.feedback(e,s);e,s,_=self.complete(23000000,True);self.assertEqual(self.reader.calls,[None,[False,True,True],None])
    def test_getter_while_recognition_lock_held_does_not_deadlock(self):
        e,s,_=self.complete(1000000)
        with self.worker.lock:self.assertIsNotNone(self.worker.accounting_result(e,s,PIPELINE))
    def test_restart_adopts_request_after_cache_commit_then_next_new_full(self):
        e,s=self.capture(1000000);original=self.worker._request;count=[0]
        def fail_final(db,event):
            count[0]+=1
            if count[0]==2:raise RuntimeError('synthetic crash after cache commit')
            return original(db,event)
        with patch.object(self.worker,'_request',side_effect=fail_final):
            with self.assertRaises(RuntimeError):self.worker.once()
        req=self.request(e);calls=len(self.reader.calls);self.worker=EventRecognition(self.store,self.reader,DOC,CONFIG,CAPS);self.assertTrue(self.worker.once());self.assertEqual(self.request(e),req);self.assertEqual(len(self.reader.calls),calls);self.feedback(e,s,'anchored');e,s,_=self.complete(3000000);self.assertTrue(all(self.request(e)['reader_observed']));self.assertIn('restart',self.request(e)['recommendation']['reasons'])
    def test_clock_camera_and_missed_deadline_force_full(self):
        e,s,_=self.complete(1000000);self.feedback(e,s,'anchored');e,s,_=self.complete(12000000);self.assertIn('backpressure',self.request(e)['recommendation']['reasons']);self.feedback(e,s);e,s,_=self.complete(1000000,clock='boot-b');self.assertIn('gap',self.request(e)['recommendation']['reasons']);self.feedback(e,s);e,s,_=self.complete(3000000,clock='boot-b',camera='other');self.assertIn('gap',self.request(e)['recommendation']['reasons'])
    def test_previous_ambiguous_accounting_and_rejection_force_full(self):
        e,s,_=self.complete(1000000);self.feedback(e,s,'anchored');e,s,_=self.complete(3000000);self.feedback(e,s,'ambiguous');self.reader.reject=True;e,s,x=self.complete(13000000);self.assertTrue(all(self.request(e)['reader_observed']));self.assertEqual(x['state'],'rejected');self.feedback(e,s,'unavailable');self.reader.reject=False;e,s,_=self.complete(23000000);self.assertIn('quality_uncertain',self.request(e)['recommendation']['reasons'])
    def test_rejected_partial_has_attempt_not_support(self):
        e,s,_=self.complete(1000000);self.feedback(e,s,'anchored');self.reader.reject=True;e,s,x=self.complete(3000000);self.assertEqual(x['state'],'rejected');self.assertNotIn('observation_support',x);self.assertEqual(x['observation_attempt']['requested_observed'],[False,True,True])
    def test_tampered_request_cache_or_binding_fails_closed(self):
        e,s,_=self.complete(1000000)
        with self.store.connect() as db:
            row=db.execute('SELECT result FROM event_recognition_cache').fetchone()[0];db.execute("UPDATE event_recognition_cache SET result='{}'")
        with self.assertRaises(ValueError):self.worker.accounting_result(e,s,PIPELINE)
        with self.store.connect() as db:db.execute('UPDATE event_recognition_cache SET result=?',(row,));db.execute("UPDATE event_recognition_bindings SET request_sha='BAD'")
        with self.assertRaises(ValueError):self.worker.accounting_result(e,s,PIPELINE)
        with self.store.connect() as db:db.execute("UPDATE event_recognition_requests SET request='{}'")
        with self.assertRaises(ValueError):self.worker.accounting_result(e,s,PIPELINE)
    def test_context_floor_and_reconfiguration_refusal(self):
        e,s,_=self.complete(1000000);self.feedback(e,s,'anchored');self.capture(3000000);config={**CONFIG,'full_refresh_seconds':30};new=EventRecognition(self.store,self.reader,DOC,config,CAPS);self.assertNotEqual(new.observation_context,self.worker.observation_context);self.assertEqual(new.observation_first_event,2);self.assertTrue(new.once());self.assertEqual(self.reader.calls[-1],None)
        bad=FakeReader();bad.pipeline_id='b'*64
        with self.assertRaises(ValueError):new.activate(bad,lambda:None)
    def test_durable_feedback_digest_and_binding_drift_reject(self):
        e,s,_=self.complete(1000000);self.feedback(e,s,'anchored');e2,s2,_=self.complete(3000000)
        with self.store.connect() as db:db.execute("UPDATE consumption_records SET result='{}' WHERE event_id=1")
        with self.assertRaises(ValueError):self.worker.accounting_result(e2,s2,PIPELINE)
    def test_invalid_mask_cache_success_not_completed(self):
        e,s,_=self.complete(1000000);self.feedback(e,s,'anchored');self.reader.wrong_support=True;e,s=self.capture(3000000)
        with self.assertRaises(ValueError):self.worker.once()
        self.assertIsNone(self.worker.accounting_result(e,s,PIPELINE))

    def test_observed_speed_probe_is_optional_not_rate_bound(self):
        e,s,_=self.complete(1000000);self.feedback(e,s,'anchored')
        original=self.reader.read_jpeg
        def moved(blob,observed=None):
            r=original(blob,observed);r['dial_positions'][-1]['position']=3.0;return r
        with patch.object(self.reader,'read_jpeg',side_effect=moved):e,s,_=self.complete(3000000)
        self.feedback(e,s);e,s,_=self.complete(13000000);request=self.request(e)
        self.assertEqual(request['flags']['observed_phase_speed'],1.0);self.assertIn('observed_motion_probe',request['recommendation']['reasons']);self.assertFalse(request['recommendation']['continuity_certified']);self.assertIsNone(request['recommendation']['physical_scalar']);self.assertEqual(request['flags']['phase_interval_width'],.02)
    def test_malformed_saved_request_types_and_latest_fail_closed(self):
        e,s,_=self.complete(1000000);original=self.request(e)
        for mutate in [lambda r:r.update(schema_version=True),lambda r:r.update(event=None),lambda r:r.pop('flags'),lambda r:r.update(feedback=True)]:
            r=copy.deepcopy(original);mutate(r)
            with self.store.connect() as db:db.execute('UPDATE event_recognition_requests SET request=?,request_sha=?',(encoded(r),digest(r)))
            with self.assertRaises(ValueError):self.worker.accounting_result(e,s,PIPELINE)
            self.assertEqual(self.worker.latest()['state'],'unavailable')
    def test_wrong_reader_pipeline_not_silently_rebound(self):
        self.capture(1000000);original=self.reader.read_jpeg
        def wrong(blob,observed=None):
            r=original(blob,observed);r['pipeline_id']='b'*64;return r
        with patch.object(self.reader,'read_jpeg',side_effect=wrong),self.assertRaisesRegex(ValueError,'reader_identity'):self.worker.once()
        with self.store.connect() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM event_recognition_bindings').fetchone()[0],0);self.assertEqual(db.execute('SELECT COUNT(*) FROM event_recognition_cache').fetchone()[0],0)
    def test_context_floor_tamper_rejects(self):
        self.capture(1000000)
        with self.store.connect() as db:db.execute('UPDATE event_selection_contexts SET first_event=999')
        with self.assertRaisesRegex(ValueError,'context_saved_invalid'):EventRecognition(self.store,self.reader,DOC,CONFIG,CAPS)
    def test_no_genuine_durable_full_anchor_forces_full(self):
        e,s,_=self.complete(1000000);self.feedback(e,s,'estimated')
        e,s,_=self.complete(3000000);self.assertTrue(all(self.request(e)['reader_observed']));self.assertIn('first',self.request(e)['recommendation']['reasons'])
    def test_feedback_schema_errors_propagate_and_run_blocks_bad_data(self):
        e,s,_=self.complete(1000000);self.feedback(e,s,'anchored');self.capture(3000000)
        with self.store.connect() as db:db.execute('ALTER TABLE consumption_records RENAME COLUMN result TO bad_result')
        import sqlite3
        with self.assertRaises(sqlite3.OperationalError):self.worker.once()
        def invalid():self.worker.stop.set();raise ValueError('synthetic corruption')
        with patch.object(self.worker,'once',side_effect=invalid):self.worker.run()
        self.assertEqual(self.worker.last_error,'event_recognition_saved_state_invalid')

if __name__=='__main__':unittest.main()
