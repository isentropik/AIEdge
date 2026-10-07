"""Actual accounting + synthetic reader/SQLite; no decoder, image or model calls."""
import copy,hashlib,importlib.util,json,os,sqlite3,tempfile,unittest
from contextlib import contextmanager
from datetime import datetime,timedelta,timezone
from unittest.mock import patch
from pathlib import Path
from capture import Store
from consumption import Consumption
from event_recognition import EventRecognition
from event_selection import digest,encoded
from event_observation_read import read_event
from reading_format import FormatStore
from recognition import Recognition
from selector_observation import build
from wheel_capture_policy import recommend

PIPE='a'*64
LIBRARY=os.environ.get('AIEDGE_ACCOUNTING_LIBRARY')
PERIODS=[10000,1000,5]
DOC={'version':1,'pipeline_id':PIPE,'unit':'ft3','dials':[
    {'index':i,'value_per_revolution':p,'position_error':.01} for i,p in enumerate(PERIODS)]}
CONFIG={'normal_interval_seconds':30.,'urgent_interval_seconds':30.,'full_refresh_seconds':60.,
        'phase_probe_budget':.1,'uncertainty_probe_width':.3}
CAPS={'minimum_interval_seconds':1.,'partial_recognition':True}

class InventedReader:
    pipeline_id=PIPE
    def __init__(self):self.dials=[{'name':str(i)} for i in range(3)];self.calls=[];self.reject=False
    def read_jpeg(self,blob,observed=None):
        # Despite the method name these are our invented text bytes, not an image.
        quantity=float(blob[2:-2].decode().split(':')[1]);mask=[True]*3 if observed is None else list(observed)
        self.calls.append(mask)
        result={'state':'rejected' if self.reject else 'estimated','pipeline_id':PIPE,
                'source_sha256':hashlib.sha256(blob).hexdigest(),'training_allowed':False,'accuracy_verified':False,
                'dial_positions':[] if self.reject else [{'name':str(i),'state':'estimated','position':quantity%p/p*10}
                    if flag else {'name':str(i),'state':'unavailable','position':None} for i,(p,flag) in enumerate(zip(PERIODS,mask))]}
        if observed is not None:
            key='observation_attempt' if self.reject else 'observation_support'
            field='requested_observed' if self.reject else 'observed'
            result[key]={'schema_version':1,'source_sha256':result['source_sha256'],'pipeline_id':PIPE,field:mask}
        return result

@unittest.skipUnless(LIBRARY,'existing inventoried accounting DLL required')
class CandidateTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.store=Store(self.temp.name);self.reader=InventedReader()
        self.document=copy.deepcopy(DOC);self.config=copy.deepcopy(CONFIG);self.caps=copy.deepcopy(CAPS)
        self.recognition=EventRecognition(self.store,self.reader,self.document,self.config,self.caps)
        self.formats=FormatStore(self.temp.name,self.recognition);self.saved=self.formats.save(self.document,None)
        self.worker=Consumption(self.store,self.recognition,self.formats,LIBRARY);self.n=0
    def tearDown(self):self.worker._drop();self.temp.cleanup()
    def capture(self,quantity,seconds=None,clock='boot-a',tick=None,repeat=False):
        self.n+=1;seconds=(self.n-1)*30 if seconds is None else seconds
        tick=int((seconds+1)*1e6) if tick is None else tick
        # Invented nondecodable JPEG envelope for Store admission, never pixels.
        blob=b'\xff\xd8'+('synthetic:'+str(quantity)+('' if repeat else ':'+str(self.n))).encode()+b'\xff\xd9'
        source=hashlib.sha256(blob).hexdigest()
        stamp=(datetime(2026,1,1,tzinfo=timezone.utc)+timedelta(seconds=seconds)).isoformat()
        self.store.add('invented-camera',blob,{'X-AIEdge-Frame-Id':str(self.n),'X-AIEdge-Captured-At':stamp,'X-AIEdge-SHA256':source,
                                             'X-AIEdge-Clock-Id':clock,'X-AIEdge-Capture-Monotonic-Us':str(tick)})
        with self.store.connect() as db:event=db.execute('SELECT MAX(event_id) FROM capture_events').fetchone()[0]
        return event,source
    def step(self,quantity,**kw):
        event,source=self.capture(quantity,**kw);self.assertTrue(self.recognition.once());self.assertTrue(self.worker.once())
        return self.request(event),self.worker.status()
    def request(self,event):
        with self.store.connect() as db:return self.recognition._request(db,event)
    def record(self,event):
        with self.store.connect() as db:return json.loads(db.execute('SELECT result FROM consumption_records WHERE event_id=? ORDER BY rowid DESC LIMIT 1',(event,)).fetchone()[0])
    def update_record(self,event,mutate,reindex=False):
        with self.store.connect() as db:
            row=db.execute('SELECT segment_id,result FROM consumption_records WHERE event_id=? ORDER BY rowid DESC LIMIT 1',(event,)).fetchone()
            value=json.loads(row[1]);mutate(value)
            db.execute('UPDATE consumption_records SET result=? WHERE segment_id=? AND event_id=?',(encoded(value),row[0],event))
            if reindex:db.execute('UPDATE consumption_accepted_full_observations SET result_sha256=? WHERE segment_id=? AND event_id=?',(digest(value),row[0],event))
    def proof(self,event):
        with self.store.connect() as db:return build(self.recognition,db,event)
    def rewrite_request(self,event,mutate):
        with self.store.connect() as db:
            row=db.execute('SELECT request FROM event_recognition_requests WHERE event_id=? AND context=?',(event,self.recognition.observation_context)).fetchone()
            request=json.loads(row[0]);mutate(request)
            if 'observation_eligibility' in request:
                request['observation_eligibility']['certificate_sha256']=digest(request['observation_eligibility']['certificate'])
            db.execute('UPDATE event_recognition_requests SET request=?,request_sha=? WHERE event_id=? AND context=?',(encoded(request),digest(request),event,self.recognition.observation_context))
    def restart_consumption(self):
        self.worker._drop();self.worker=Consumption(self.store,self.recognition,self.formats,LIBRARY)
        while self.worker.once():pass
        return self.worker.status()
    def test_unbounded_high_flow_pair_alias_preserves_ambiguity_lower_bound_and_full_refresh(self):
        r1,a=self.step(123.4);r2,b=self.step(1123.4);r3,c=self.step(2123.4);r4,d=self.step(3123.4)
        self.assertEqual([r['recommendation']['requested_mode'] for r in (r1,r2,r3,r4)],['FULL','LAST_TWO','FULL','LAST_TWO'])
        self.assertIn('periodic_full',r3['full_reason']);self.assertEqual(r4['last_full_event'],3)
        self.assertEqual(r4['observation_eligibility']['certificate']['genuine_full_anchor']['event']['event_id'],1)
        for state in (b,c,d):
            self.assertEqual(state['state'],'ambiguous');self.assertIsNone(state['value']);self.assertIsNone(state['maximum']);self.assertTrue(state['upper_unbounded'])
            self.assertTrue(state['observation_accepted'])
        # Partial images supply no absolute reading. Preserve the original FULL
        # single-image reading if available; it is not relative usage continuity.
        for state in (b,d):self.assertIsNone(state['absolute']['value'])
        self.assertGreater(c['minimum'],1900);self.assertGreaterEqual(d['minimum'],c['minimum'])
        self.assertAlmostEqual(r4['flags']['observed_phase_speed'],0.)
        self.assertTrue(r4['flags']['accounting_uncertain']);self.assertFalse(r4['flags']['phase_ambiguous'])
        self.assertTrue(r4['recommendation']['uncertainty_retained']);self.assertFalse(r4['recommendation']['continuity_certified'])
        self.assertIsNone(r4['recommendation']['physical_scalar']);self.assertFalse(r4['recommendation']['alignment_bypass'])
        self.assertEqual(self.restart_consumption(),d)
    def test_bounded_result_keeps_full_even_healthy_phase(self):
        self.step(123.4);self.step(123.4)
        self.update_record(2,lambda v:v.update(state='bounded',upper_unbounded=False,maximum=1.,value=None))
        r,_=self.step(123.4,seconds=45)
        self.assertTrue(r['flags']['phase_ambiguous']);self.assertEqual(r['recommendation']['requested_mode'],'FULL')
    def test_declared_rate_never_uses_unbounded_relaxation(self):
        self.document['maximum_rate_per_second']=100.
        self.worker._drop();self.recognition=EventRecognition(self.store,self.reader,self.document,self.config,self.caps)
        self.formats=FormatStore(self.temp.name,self.recognition);self.saved=self.formats.save(self.document,self.saved['revision'])
        self.worker=Consumption(self.store,self.recognition,self.formats,LIBRARY)
        self.step(123.4);self.step(1123.4)
        p=self.proof(2);self.assertFalse(p['relaxation_eligible'])
    def test_missing_acceptance_witness_defaults_full(self):
        self.step(123.4);self.step(123.4)
        for field in ('observation_accepted','observation_current_through_us','observation_inference_sha256'):
            old=self.record(2);self.update_record(2,lambda v,f=field:v.pop(f,None))
            p=self.proof(2);self.assertFalse(p['fine_observation_eligible']);self.assertFalse(p['relaxation_eligible'])
            self.update_record(2,lambda v,o=old:(v.clear(),v.update(o)))
        self.update_record(2,lambda v:v.update(observation_accepted=False))
        r,_=self.step(123.4,seconds=45);self.assertEqual(r['recommendation']['requested_mode'],'FULL')
    def test_wrong_current_tick_stale_record_cannot_grant_eligibility(self):
        self.step(123.4);self.step(123.4)
        self.update_record(2,lambda v:v.update(observation_current_through_us=v['observation_current_through_us']-1))
        self.assertFalse(self.proof(2)['fine_observation_eligible'])
        r,_=self.step(123.4,seconds=45);self.assertEqual(r['recommendation']['requested_mode'],'FULL')
    def test_rejected_partial_persists_and_forces_next_full(self):
        self.step(123.4);self.reader.reject=True;r,state=self.step(123.4)
        self.assertEqual(r['reader_observed'],[False,True,True]);self.assertEqual(state['state'],'unavailable')
        self.assertFalse(state['observation_accepted']);self.assertIsNone(state['observation_inference_sha256'])
        self.reader.reject=False;r,nextstate=self.step(123.4,seconds=45)
        self.assertEqual(r['recommendation']['requested_mode'],'FULL');self.assertIn('quality_uncertain',r['full_reason'])
    def test_pending_feedback_holds_request_and_exposes_no_acceptance(self):
        e,s=self.capture(123.4);self.assertTrue(self.recognition.once());self.capture(123.4)
        self.assertFalse(self.recognition.once());self.assertFalse(self.worker.status().get('observation_accepted',False))
        self.assertTrue(self.worker.once());self.assertFalse(self.worker.status()['observation_accepted'])
        self.assertTrue(self.recognition.once());self.assertTrue(self.worker.once())
    def test_carry_near_wrap_conservative_full_without_scalar(self):
        self.step(999.999);r,state=self.step(1000.001)
        self.assertEqual(r['recommendation']['requested_mode'],'FULL');self.assertIn('fine_error_interval_wraps',r['observation_eligibility']['certificate']['reasons'])
        self.assertIsNone(state['value']);self.assertEqual(state['state'],'ambiguous')
    def test_no_genuine_full_anchor_and_bad_full_index_fail_closed(self):
        self.step(123.4);self.step(123.4)
        self.update_record(2,lambda v:v.update(observation_full_anchor_event_id=None,observation_latest_full_event_id=None))
        r,_=self.step(123.4,seconds=45);self.assertEqual(r['recommendation']['requested_mode'],'FULL');self.assertIn('first',r['full_reason'])
        with self.store.connect() as db:db.execute('UPDATE consumption_accepted_full_observations SET result_sha256=? WHERE event_id=1',('0'*64,))
        with self.assertRaisesRegex(ValueError,'full_index_binding'):self.proof(3)
    def test_clock_gap_separate_anchor_and_null_delta(self):
        r1,a=self.step(123.4);before=self.record(1)
        r2,b=self.step(1123.4,clock='boot-b',tick=1000000)
        self.assertIn('gap',r2['full_reason']);self.assertEqual(r2['reader_observed'],[True]*3)
        self.assertNotEqual(a['segment_id'],b['segment_id']);self.assertIsNone(b['unresolved_gap']['delta'])
        r3,c=self.step(1123.4,clock='boot-b',tick=31000000)
        self.assertEqual(r3['observation_eligibility']['certificate']['genuine_full_anchor']['event']['event_id'],2)
        self.assertEqual(self.record(1),before);self.assertEqual(self.restart_consumption(),c)
    def test_strict_deadline_and_unsupported_cadence_unchanged(self):
        self.step(123.4);r,_=self.step(123.4,seconds=30.000001)
        self.assertTrue(r['deadline_missed']);self.assertIn('backpressure',r['full_reason'])
        self.assertEqual(r['recommendation']['requested_mode'],'FULL')
        flags=dict(r['flags']);flags.update(first=False,gap=False,restart=False,quality_uncertain=False,phase_ambiguous=False,
                                          fine_observation_uncertain=False,full_refresh_uncertain=False,backpressure=False,
                                          full_age_seconds=0,observed_phase_speed=1.)
        recommendation=recommend(flags,{**self.caps,'minimum_interval_seconds':1.},self.config)
        self.assertIn('requested_cadence_not_supported',recommendation['reasons']);self.assertEqual(recommendation['requested_mode'],'FULL')
    def test_restart_keeps_completed_request_and_next_uncached_full(self):
        self.step(123.4);r2,b=self.step(123.4);calls=len(self.reader.calls)
        self.recognition=EventRecognition(self.store,self.reader,self.document,self.config,self.caps)
        self.worker.recognition=self.recognition
        self.assertEqual(self.request(2),r2);r3,c=self.step(123.4,seconds=45)
        self.assertIn('restart',r3['full_reason']);self.assertEqual(r3['recommendation']['requested_mode'],'FULL')
        self.assertGreaterEqual(len(self.reader.calls),calls)
    def test_forged_certificate_and_anchor_boolean_rehashed_still_rejected(self):
        self.step(123.4);self.step(123.4);self.step(123.4)
        with self.store.connect() as db:original=db.execute('SELECT request,request_sha FROM event_recognition_requests WHERE event_id=3').fetchone()
        for mutate in [lambda r:r['observation_eligibility']['certificate'].update(relaxation_eligible=False),
                       lambda r:r['observation_eligibility']['certificate']['pair'][0].update(position=9.5),
                       lambda r:r['feedback'].update(genuine_full_anchor=False),
                       lambda r:r.update(last_full_event=None)]:
            with self.store.connect() as db:db.execute('UPDATE event_recognition_requests SET request=?,request_sha=? WHERE event_id=3',original)
            self.rewrite_request(3,mutate)
            with self.assertRaises(ValueError):self.request(3)
    def test_forged_periodic_full_age_mask_and_flags_rehashed_rejected(self):
        self.step(123.4);self.step(123.4);self.step(123.4)
        def forged(r):
            r['flags']['full_age_seconds']=0;r['recommendation']=recommend(r['flags'],self.caps,self.config)
            r['reader_observed']=[False,True,True];r['full_reason']=r['recommendation']['reasons']
        self.rewrite_request(3,forged)
        with self.assertRaisesRegex(ValueError,'decision_rederived'):self.request(3)
    def test_cache_result_rehash_cannot_reuse_original_native_acceptance(self):
        self.step(123.4);self.step(123.4)
        with self.store.connect() as db:
            row=db.execute('SELECT source_sha,mask_sha,result_sha FROM event_recognition_bindings WHERE event_id=2').fetchone()
            cache=json.loads(db.execute('SELECT result FROM event_recognition_cache WHERE source_sha=? AND mask_sha=?',row[:2]).fetchone()[0])
            cache['dial_positions'][-1]['position']+=.01
            db.execute('UPDATE event_recognition_cache SET result=?,result_sha=? WHERE source_sha=? AND mask_sha=?',(encoded(cache),digest(cache),row[0],row[1]))
            db.execute('UPDATE event_recognition_bindings SET result_sha=? WHERE event_id=2',(digest(cache),))
        with self.assertRaisesRegex(ValueError,'inference_changed'):self.proof(2)
    def test_same_source_distinct_event_masks_and_proofs(self):
        r1,a=self.step(123.4,repeat=True);r2,b=self.step(123.4,repeat=True);r3,c=self.step(123.4,repeat=True)
        self.assertEqual(self.store.status()['unique_images'],1);self.assertEqual(self.store.status()['captures'],3)
        self.assertEqual(len(self.reader.calls),2);self.assertEqual(r1['reader_observed'],r3['reader_observed']);self.assertNotEqual(r2['reader_observed'],r3['reader_observed'])
        self.assertNotEqual(a['observation_inference_sha256'],c['observation_inference_sha256']);self.assertEqual(self.restart_consumption(),c)
    def test_new_context_engine_preserves_old_records_requests_and_null_gap(self):
        self.step(123.4);self.step(123.4);old_context=self.recognition.observation_context
        with self.store.connect() as db:before=list(db.execute('SELECT segment_id,event_id,result FROM consumption_records'));requests=list(db.execute('SELECT event_id,context,request FROM event_recognition_requests'))
        self.worker._drop();config={**self.config,'full_refresh_seconds':90.}
        self.recognition=EventRecognition(self.store,self.reader,self.document,config,self.caps)
        self.formats=FormatStore(self.temp.name,self.recognition);self.worker=Consumption(self.store,self.recognition,self.formats,LIBRARY)
        self.assertNotEqual(old_context,self.recognition.observation_context);self.assertEqual(self.recognition.observation_first_event,2)
        self.assertTrue(self.recognition.once());self.assertTrue(self.worker.once());state=self.worker.status()
        self.assertEqual(state['gap_reason'],'interpretation_changed');self.assertIsNone(state['unresolved_gap']['delta']);self.assertEqual(self.request(2)['reader_observed'],[True]*3)
        with self.store.connect() as db:
            after=list(db.execute('SELECT segment_id,event_id,result FROM consumption_records'));after_requests=list(db.execute('SELECT event_id,context,request FROM event_recognition_requests'))
        for row in before:self.assertIn(row,after)
        for row in requests:self.assertIn(row,after_requests)
    def test_schema1_historical_adapter_and_active_schema2_no_downgrade(self):
        self.step(123.4);original=self.request(1);old=copy.deepcopy(original);old['schema_version']=1;old.pop('observation_eligibility')
        legacy='d'*64;old['context_id']=legacy
        with self.store.connect() as db:
            db.execute('INSERT INTO event_selection_contexts VALUES (?,?,?,?)',(legacy,PIPE,self.recognition.format_id,1))
            db.execute('INSERT INTO event_recognition_requests VALUES (?,?,?,?,?)',(1,PIPE,legacy,encoded(old),digest(old)))
            binding=list(db.execute('SELECT source_sha,mask_sha,result_sha FROM event_recognition_bindings WHERE event_id=1').fetchone())
            db.execute('INSERT INTO event_recognition_bindings VALUES (?,?,?,?,?,?,?)',(1,PIPE,legacy,*binding,digest(old)))
        historical=read_event(self.store,1,original['event']['source_sha256'],PIPE,legacy)
        self.assertEqual(historical['result']['state'],'estimated');self.assertEqual(historical['result']['event_observation']['context_id'],legacy)
        self.assertEqual(set(historical),{'processed_at','result','decision','decision_evidence'})
        self.assertEqual(historical['decision']['schema_version'],1)
        self.assertEqual(historical['decision']['requested_mode'],'FULL')
        self.assertEqual(historical['decision']['reader_observed'],[True]*3)
        self.assertEqual(historical['decision']['request_sha256'],digest(old))
        self.assertTrue(historical['decision_evidence']['completion_valid'])
        self.rewrite_request(1,lambda r:(r.update(schema_version=1),r.pop('observation_eligibility')))
        with self.assertRaises(ValueError):self.request(1)
    def test_invalid_full_refresh_clock_and_forged_full_ids_fail_closed(self):
        self.step(123.4);self.step(123.4)
        for field,value in [('observation_latest_full_event_id',2),('observation_full_anchor_event_id',True)]:
            old=self.record(2);self.update_record(2,lambda v,f=field,x=value:v.update({f:x}))
            with self.assertRaises(ValueError):self.proof(2)
            self.update_record(2,lambda v,o=old:(v.clear(),v.update(o)))
    def test_oversized_and_duplicate_saved_evidence_fail_closed_before_decode(self):
        self.step(123.4);self.step(123.4)
        for table,column,condition,limit in [('consumption_records','result','event_id=2',65536),
                    ('consumption_segments','document','1=1',65536),
                    ('event_recognition_requests','request','event_id=2',32768)]:
            with self.store.connect() as db:original=db.execute('SELECT '+column+' FROM '+table+' WHERE '+condition).fetchone()[0]
            try:
                for text in (' '*(limit+1),'null','{"version":1,"version":1}'):
                    with self.store.connect() as db:db.execute('UPDATE '+table+' SET '+column+'=? WHERE '+condition,(text,))
                    with self.assertRaises(ValueError):self.proof(2)
            finally:
                with self.store.connect() as db:db.execute('UPDATE '+table+' SET '+column+'=? WHERE '+condition,(original,))
    def test_current_support_identity_and_boolean_type_tampering_fail_closed(self):
        self.step(123.4);self.step(123.4);old=self.record(2)
        for mutate in [lambda v:v.update(event_id=True),lambda v:v.update(source_sha256='0'*64),
                       lambda v:v['event_observation'].update(monotonic_us=True),
                       lambda v:v['observation_support']['reader_observed'].__setitem__(1,1),
                       lambda v:v['observation_support'].update(pipeline_id='0'*64)]:
            self.update_record(2,mutate)
            with self.assertRaises(ValueError):self.proof(2)
            self.update_record(2,lambda v:(v.clear(),v.update(copy.deepcopy(old))))
    def test_native_acceptance_available_current_and_through_tick_all_required(self):
        # Fault-inject native return metadata after a REAL native observation.
        # This checks witness production, not a new native engine behavior.
        for field,value in [('accepted',False),('available',False),('current',False),('through_us',0)]:
            fixture=CandidateTests();fixture.setUp()
            try:
                factory=fixture.worker.native.tracker
                class Proxy:
                    def __init__(self,tracker):self.tracker=tracker
                    def __getattr__(self,name):return getattr(self.tracker,name)
                    def observe(self,*args):
                        result=self.tracker.observe(*args);result[field]=value;return result
                with patch.object(fixture.worker.native,'tracker',side_effect=lambda doc:Proxy(factory(doc))):
                    fixture.step(123.4)
                state=fixture.worker.status();self.assertFalse(state['observation_accepted']);self.assertIsNone(state['observation_current_through_us'])
                self.assertIsNone(state['observation_inference_sha256']);self.assertFalse(fixture.proof(1)['fine_observation_eligible'])
                with fixture.store.connect() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM consumption_accepted_full_observations').fetchone()[0],0)
            finally:fixture.tearDown()
    def test_default_full_native_results_preserved_except_additive_metadata(self):
        # Read-only original producer import; same existing accounting DLL and
        # invented phases. No native reading/preparation/model/image calls.
        frozen=Path(__file__).with_name('test_fixtures')/'dev29_accounting'/'consumption.py'
        spec=importlib.util.spec_from_file_location('frozen_default_consumption',frozen);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        # Exact checked-in legacy body and seven fingerprint dependencies,
        # repository-portable; no source lookup or runtime path monkeypatch.
        produced=[]
        for producer in (module.Consumption,Consumption):
            with tempfile.TemporaryDirectory() as directory:
                store=Store(directory);reader=InventedReader();recognition=Recognition(store,reader);formats=FormatStore(directory,recognition)
                formats.save(DOC,None);worker=producer(store,recognition,formats,LIBRARY);rows=[]
                try:
                    for event,quantity in enumerate((123.4,1123.4,2123.4),1):
                        blob=b'\xff\xd8'+('synthetic:'+str(quantity)).encode()+b'\xff\xd9';source=hashlib.sha256(blob).hexdigest();seconds=(event-1)*30
                        stamp=(datetime(2026,1,1,tzinfo=timezone.utc)+timedelta(seconds=seconds)).isoformat()
                        store.add('invented-camera',blob,{'X-AIEdge-Frame-Id':str(event),'X-AIEdge-Captured-At':stamp,'X-AIEdge-SHA256':source,
                            'X-AIEdge-Clock-Id':'boot-a','X-AIEdge-Capture-Monotonic-Us':str(int((seconds+1)*1e6))})
                        self.assertTrue(recognition.once());self.assertTrue(worker.once());state=worker.status()
                        for key in list(state):
                            if key.startswith('observation_') and key!='observation_support' and key!='observation_context':state.pop(key)
                        state.pop('segment_id');rows.append(state)
                    produced.append(rows)
                finally:worker._drop()
        self.assertEqual(produced[0],produced[1])
    def test_index_queries_bounded_for_large_actual_history(self):
        self.step(123.4);self.step(123.4)
        def count(event):
            statements=[]
            with self.store.connect() as db:
                db.set_trace_callback(statements.append);proof=build(self.recognition,db,event);db.set_trace_callback(None)
                plan=list(db.execute('EXPLAIN QUERY PLAN SELECT event_id,result_sha256 FROM consumption_accepted_full_observations WHERE segment_id=? AND event_id<=? ORDER BY event_id DESC LIMIT 1',(proof['observation']['accounting_segment_id'],event)))
            return statements,plan
        early,_=count(2)
        for n in range(3,129):self.step(123.4)
        later,plan=count(128)
        self.assertLessEqual(len(later),len(early)+12);self.assertLess(len(later),50)
        self.assertTrue(any('INDEX' in row[3].upper() for row in plan))
        self.assertFalse(any('FROM consumption_records' in sql and 'event_id=' not in sql for sql in later))
    def test_record_and_index_atomic_failures_discard_native_then_reconstruct(self):
        self.step(123.4);self.step(123.4);event,source=self.capture(123.4);self.assertTrue(self.recognition.once())
        connect=self.store.connect
        for after_index in (False,True):
            class Proxy:
                def __init__(self,db):self.db=db
                def execute(self,sql,*args):
                    if sql.startswith('INSERT INTO consumption_accepted_full_observations'):
                        if after_index:self.db.execute(sql,*args)
                        raise sqlite3.OperationalError('synthetic index transaction interruption')
                    return self.db.execute(sql,*args)
            @contextmanager
            def broken():
                with connect() as db:yield Proxy(db)
            if self.worker.segment is None:
                # Reconstruct only the already durable events before retrying the
                # failed event with the fresh tracker, never reuse advanced state.
                self.assertTrue(self.worker.once());self.assertTrue(self.worker.once())
            with patch.object(self.store,'connect',side_effect=broken),self.assertRaises(sqlite3.OperationalError):self.worker.once()
            self.assertIsNone(self.worker.tracker);self.assertIsNone(self.worker.anchor);self.assertIsNone(self.worker.latest_accepted_full)
            self.assertEqual(self.worker.last_error,'consumption_commit_requires_reconstruction')
            with self.store.connect() as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM consumption_records WHERE event_id=?',(event,)).fetchone()[0],0)
                self.assertEqual(db.execute('SELECT COUNT(*) FROM consumption_accepted_full_observations WHERE event_id=?',(event,)).fetchone()[0],0)
            self.assertFalse(self.recognition.once())
        calls=len(self.reader.calls);state=self.restart_consumption()
        self.assertEqual(state['event_id'],event);self.assertTrue(state['observation_accepted']);self.assertEqual(len(self.reader.calls),calls)
        with self.store.connect() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM consumption_accepted_full_observations WHERE event_id=?',(event,)).fetchone()[0],1)

if __name__=='__main__':unittest.main()
