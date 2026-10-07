"""Synthetic SQLite only: no capture, image decoding, models, native or network."""
import ast
import contextlib
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import event_observation_read as reader
import trial_results
import wheel_capture_policy

PARENT=Path(__file__).resolve().parent/'test_fixtures/event_observation_read_dev29.py'
spec=importlib.util.spec_from_file_location('frozen_original_event_getter',PARENT)
original=importlib.util.module_from_spec(spec);spec.loader.exec_module(original)
PIPE='a'*64;CONTEXT='b'*64;FORMAT='c'*64
SOURCE=hashlib.sha256(b'TEST_ONLY synthetic shared image identity; not image bytes').hexdigest()
REQUEST_ID='d'*32

def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False)
def digest(value):return hashlib.sha256(canonical(value).encode()).hexdigest()
def strip(value):return {k:v for k,v in value.items() if k not in ('decision','decision_evidence')}

class Store:
    def __init__(self,root):self.root=root
    @contextlib.contextmanager
    def connect(self):
        db=sqlite3.connect(Path(self.root)/'captures.sqlite3')
        try:yield db;db.commit()
        finally:db.close()

class Fixture:
    def __init__(self,root):
        self.store=Store(root);self.requests={};self.frames={};self.results={}
        with self.store.connect() as db:
            db.executescript('''
            CREATE TABLE frames(camera TEXT,frame_id TEXT,sha256 TEXT,captured_at TEXT,PRIMARY KEY(camera,frame_id));
            CREATE TABLE capture_events(event_id INTEGER PRIMARY KEY,camera TEXT,frame_id TEXT);
            CREATE TABLE capture_clocks(camera TEXT,frame_id TEXT,clock_id TEXT,monotonic_us INTEGER);
            CREATE TABLE event_selection_contexts(context TEXT PRIMARY KEY,pipeline TEXT,format_id TEXT,first_event INTEGER);
            CREATE TABLE event_recognition_requests(event_id INTEGER,pipeline TEXT,context TEXT,request TEXT,request_sha TEXT,PRIMARY KEY(event_id,pipeline,context));
            CREATE TABLE event_recognition_bindings(event_id INTEGER,pipeline TEXT,context TEXT,source_sha TEXT,mask_sha TEXT,result_sha TEXT,request_sha TEXT,PRIMARY KEY(event_id,pipeline,context));
            CREATE TABLE event_recognition_cache(source_sha TEXT,pipeline TEXT,mask_sha TEXT,mask TEXT,result TEXT,result_sha TEXT,PRIMARY KEY(source_sha,pipeline,mask_sha));
            ''')
            db.execute('INSERT INTO event_selection_contexts VALUES(?,?,?,?)',(CONTEXT,PIPE,FORMAT,1))
    def add(self,event=1,mask=None,reason='first',state='estimated',request=True,complete=True):
        mask=list(mask if mask is not None else [True]*6)
        frame=dict(frame_id='synthetic_'+str(event),captured_at='2026-10-06T00:00:%02dZ'%event,
                   sha256=SOURCE,clock_id='test-only-clock',monotonic_us=event*30000000,
                   added=True,event_id=event,camera='TEST_ONLY_CAMERA')
        acquisition={k:frame[k] for k in ('event_id','camera','frame_id','captured_at','clock_id','monotonic_us')}
        acquisition['source_sha256']=SOURCE
        value=dict(schema_version=1,event=acquisition,pipeline_id=PIPE,context_id=CONTEXT,format_id=FORMAT,
                   reader_observed=mask,recommendation=dict(requested_mode='FULL' if all(mask) else 'LAST_TWO',
                   reasons=[reason] if reason else [],requested_interval_seconds=30.0,supported_interval_seconds=30.0),
                   timing=dict(state='unavailable',reason='capture_clock_anchor_missing',elapsed_seconds=None)
                   if event==1 else dict(state='continuous',reason=None,elapsed_seconds=30.0),
                   deadline_missed=False,flags={'first':event==1},full_reason=[reason] if reason else [],
                   configuration={'historical_policy':'TEST_ONLY_OLD'},capabilities={'partial_supported':True},
                   feedback={'secret_private_feedback':'TEST_ONLY_DO_NOT_EXPORT'},last_full_event=None if event==1 else 1)
        result=dict(state=state,source_sha256=SOURCE,pipeline_id=PIPE,training_allowed=False,accuracy_verified=False,
                    dial_positions=[dict(state='estimated',position=float(i)) if flag else dict(state='unavailable',position=None)
                                    for i,flag in enumerate(mask)] if state=='estimated' else [])
        if not all(mask):
            if state=='estimated':result['observation_support']=dict(schema_version=1,source_sha256=SOURCE,pipeline_id=PIPE,observed=mask)
            else:result['observation_attempt']=dict(schema_version=1,source_sha256=SOURCE,pipeline_id=PIPE,requested_observed=mask)
        if state=='rejected':result['error']='TEST_ONLY_VALID_REJECTION'
        self.frames[event]=frame;self.requests[event]=value;self.results[event]=result
        with self.store.connect() as db:
            db.execute('INSERT INTO frames VALUES(?,?,?,?)',(frame['camera'],frame['frame_id'],SOURCE,frame['captured_at']))
            db.execute('INSERT INTO capture_events VALUES(?,?,?)',(event,frame['camera'],frame['frame_id']))
            db.execute('INSERT INTO capture_clocks VALUES(?,?,?,?)',(frame['camera'],frame['frame_id'],frame['clock_id'],frame['monotonic_us']))
            if request:db.execute('INSERT INTO event_recognition_requests VALUES(?,?,?,?,?)',(event,PIPE,CONTEXT,canonical(value),digest(value)))
            if complete:
                db.execute('INSERT OR REPLACE INTO event_recognition_cache VALUES(?,?,?,?,?,?)',(SOURCE,PIPE,digest(mask),canonical(mask),canonical(result),digest(result)))
                db.execute('INSERT INTO event_recognition_bindings VALUES(?,?,?,?,?,?,?)',(event,PIPE,CONTEXT,SOURCE,digest(mask),digest(result),digest(value)))
        return frame
    def rewrite_request(self,event,change,bind=True):
        value=self.requests[event];change(value)
        with self.store.connect() as db:
            db.execute('UPDATE event_recognition_requests SET request=?,request_sha=? WHERE event_id=?',(canonical(value),digest(value),event))
            if bind:db.execute('UPDATE event_recognition_bindings SET request_sha=? WHERE event_id=?',(digest(value),event))
    def rewrite_result(self,event,change):
        result=self.results[event];change(result);mask=self.requests[event]['reader_observed']
        with self.store.connect() as db:
            db.execute('UPDATE event_recognition_cache SET result=?,result_sha=? WHERE mask_sha=?',(canonical(result),digest(result),digest(mask)))
            db.execute('UPDATE event_recognition_bindings SET result_sha=? WHERE mask_sha=?',(digest(result),digest(mask)))
    def read(self,event=1):return reader.read_event(self.store,event,SOURCE,PIPE,CONTEXT)
    def journal(self,context=True):
        frames=[copy.deepcopy(v) for v in self.frames.values()]
        if not context:
            for frame in frames:frame.pop('event_id');frame.pop('camera')
        return dict(request_id=REQUEST_ID,max_attempts=3,duration_seconds=90,interval_seconds=30,job='e'*32,state='completed',
                    started_at='2026-10-06T00:00:00Z',finished_at='2026-10-06T00:01:30Z',attempts=len(frames),
                    saved_frames=len(frames),unique_images=1,duplicate_images=len(frames)-1,missed_slots=0,frames=frames,
                    error=None,in_flight=False,counts_complete=True,capture_outcome_uncertain=False,
                    context={'pipeline_id':PIPE,**({'observation_context':CONTEXT} if context else {})},training_allowed=False,accuracy_verified=False)
    def trial(self,context=True):
        snapshot=self.journal(context)
        return type('SyntheticTrial',(),{'status':lambda ignored,request_id:copy.deepcopy(snapshot)})()

class DecisionTests(unittest.TestCase):
    def setUp(self):
        scratch=Path(__file__).resolve().parents[1]/'.synthetic-temp';scratch.mkdir(exist_ok=True)
        self.tmp=tempfile.TemporaryDirectory(prefix='TEST_ONLY_event_decision_',dir=scratch);self.addCleanup(self.tmp.cleanup)
        self.f=Fixture(self.tmp.name)
    def assert_original(self,event=1):
        actual=self.f.read(event);old=original.read_event(self.f.store,event,SOURCE,PIPE,CONTEXT)
        self.assertEqual(strip(actual),old);return actual
    def assert_unavailable(self,value,valid=False):
        self.assertNotIn('decision',value);self.assertEqual(value['decision_evidence']['state'],'unavailable')
        self.assertIs(value['decision_evidence']['completion_valid'],valid)
    def test_full_completed_public_projection_and_original_payload(self):
        self.f.add();value=self.assert_original();d=value['decision']
        self.assertEqual(set(d),{'schema_version','reader_observed','requested_mode','reasons','full_reason','timing','deadline_missed','request_sha256','result_state','requested_interval_seconds','supported_interval_seconds'})
        self.assertEqual(d['reader_observed'],[True]*6);self.assertEqual(d['requested_mode'],'FULL')
        self.assertEqual(d['full_reason'],['first']);self.assertEqual(d['request_sha256'],digest(self.f.requests[1]))
        self.assertNotIn('TEST_ONLY_DO_NOT_EXPORT',canonical(value));self.assertEqual(value['decision_evidence'],dict(state='complete',request_exists=True,completion_exists=True,completion_valid=True))
    def test_partial_completed_mask_support_and_original_payload(self):
        self.f.add(mask=[False]*4+[True]*2,reason=None);value=self.assert_original()
        self.assertEqual(value['decision']['requested_mode'],'LAST_TWO');self.assertEqual(value['decision']['reader_observed'],[False]*4+[True]*2)
    def test_duplicate_source_distinct_full_and_partial_events(self):
        self.f.add();self.f.add(2,mask=[False]*4+[True]*2,reason=None)
        a=self.assert_original(1);b=self.assert_original(2)
        self.assertNotEqual(a['decision']['reader_observed'],b['decision']['reader_observed'])
        self.assertNotEqual(a['decision']['request_sha256'],b['decision']['request_sha256'])
        self.assertEqual(b['result']['event_observation']['event_id'],2)
    def test_duplicate_source_same_mask_keeps_event_reasons_and_timing(self):
        self.f.add();self.f.add(2,reason='periodic_full');a=self.assert_original(1);b=self.assert_original(2)
        self.assertEqual(a['decision']['full_reason'],['first']);self.assertEqual(b['decision']['full_reason'],['periodic_full'])
        self.assertNotEqual(a['decision']['request_sha256'],b['decision']['request_sha256'])
        self.assertNotEqual(a['decision']['timing'],b['decision']['timing'])
    def test_changed_current_policy_never_reexecutes_historical_decision(self):
        self.f.add();before=self.f.read()
        with patch.object(wheel_capture_policy,'recommend',side_effect=AssertionError('NO POLICY REEXECUTION')):
            unrelated_current_policy={'normal_interval_seconds':999.0,'partial_supported':False}
            self.assertEqual(self.f.read(),before);self.assertEqual(unrelated_current_policy['normal_interval_seconds'],999.0)
    def test_summary_and_result_use_one_read_transaction_despite_concurrent_writer(self):
        self.f.add()
        with self.f.store.connect() as db:db.execute('PRAGMA journal_mode=WAL')
        before=digest(self.f.requests[1]);project=reader._public_decision
        def intervening_write(request,request_sha,state):
            self.f.rewrite_request(1,lambda r:r.update(full_reason=['gap']))
            return project(request,request_sha,state)
        with patch.object(reader,'_public_decision',side_effect=intervening_write):value=self.f.read()
        self.assertEqual(value['decision']['request_sha256'],before)
        self.assertEqual(value['result']['event_observation']['request_sha256'],before)
        self.assertEqual(value['decision']['full_reason'],['first'])
        self.assertEqual(self.f.read()['decision']['full_reason'],['gap'])
    def test_integrated_context_contains_getter_and_selector_and_is_new(self):
        here=Path(__file__).resolve().parent
        body=ast.parse((here/'event_recognition.py').read_text())
        deps=next(ast.literal_eval(node.value) for node in ast.walk(body) if isinstance(node,ast.Assign)
                  and any(isinstance(t,ast.Name) and t.id=='deps' for t in node.targets))
        self.assertIn('event_observation_read.py',deps)
        self.assertIn('selector_observation.py',deps)
        old=json.loads((here/'test_fixtures/dev29-context-source-sha256.json').read_text())
        new={name:hashlib.sha256((here/name).read_bytes()).hexdigest() for name in deps}
        self.assertNotEqual(old,new)
        self.assertNotEqual(old['event_observation_read.py'],new['event_observation_read.py'])
        self.assertNotEqual(digest({'sources':old}),digest({'sources':new}))
    def test_no_request_pending_even_with_cache_and_binding(self):
        self.f.add(request=False);value=self.assert_original();self.assertNotIn('decision',value)
        self.assertEqual(value['decision_evidence'],dict(state='pending',request_exists=False,completion_exists=None,completion_valid=False))
    def test_request_without_completion_pending_even_with_reusable_cache(self):
        self.f.add();self.f.add(2,complete=False);value=self.assert_original(2);self.assertNotIn('decision',value)
        self.assertEqual(value['decision_evidence'],dict(state='pending',request_exists=True,completion_exists=False,completion_valid=False))
    def test_rejected_full_completion_is_evidence_not_success(self):
        self.f.add(state='rejected');value=self.assert_original();self.assertEqual(value['decision']['result_state'],'rejected')
        self.assertFalse(value['result']['accuracy_verified']);self.assertEqual(value['result']['dial_positions'],[])
    def test_rejected_partial_completion_requires_attempt_binding(self):
        self.f.add(mask=[False]*4+[True]*2,state='rejected',reason=None);value=self.assert_original()
        self.assertEqual(value['decision']['result_state'],'rejected');self.assertEqual(value['decision']['reader_observed'],[False]*4+[True]*2)
        self.f.rewrite_result(1,lambda r:r['observation_attempt'].update(requested_observed=[True]*6))
        self.assert_unavailable(self.assert_original())
    def test_completion_request_binding_tamper_hides_decision(self):
        self.f.add();self.f.rewrite_request(1,lambda r:r.update(full_reason=['gap']),bind=False)
        value=self.assert_original();self.assert_unavailable(value)
        self.assertIs(value['decision_evidence']['request_exists'],True);self.assertIs(value['decision_evidence']['completion_exists'],True)
    def test_completion_mask_binding_tamper_hides_decision(self):
        self.f.add()
        with self.f.store.connect() as db:db.execute('UPDATE event_recognition_bindings SET mask_sha=?',('f'*64,))
        self.assert_unavailable(self.assert_original())
    def test_cache_result_hash_tamper_hides_decision(self):
        self.f.add()
        with self.f.store.connect() as db:db.execute('UPDATE event_recognition_cache SET result_sha=?',('f'*64,))
        self.assert_unavailable(self.assert_original())
    def test_cache_missing_hides_decision_with_presence_evidence(self):
        self.f.add()
        with self.f.store.connect() as db:db.execute('DELETE FROM event_recognition_cache')
        value=self.assert_original();self.assert_unavailable(value);self.assertIs(value['decision_evidence']['completion_exists'],True)
    def test_unobserved_stale_position_invalidates_result_and_decision(self):
        self.f.add(mask=[False]*4+[True]*2,reason=None)
        self.f.rewrite_result(1,lambda r:r['dial_positions'][0].update(position=5.0))
        self.assert_unavailable(self.assert_original())
    def test_acquisition_binding_tamper_hides_decision(self):
        self.f.add();self.f.rewrite_request(1,lambda r:r['event'].update(monotonic_us=31))
        value=self.assert_original();self.assert_unavailable(value);self.assertIsNone(value['decision_evidence']['completion_exists'])
    def test_context_binding_tamper_hides_decision(self):
        self.f.add();self.f.rewrite_request(1,lambda r:r.update(context_id='f'*64))
        self.assert_unavailable(self.assert_original())
    def test_unsupported_request_schema_hides_decision(self):
        self.f.add();self.f.rewrite_request(1,lambda r:r.update(schema_version=2))
        self.assert_unavailable(self.assert_original())
    def test_malformed_or_unsupported_reasons_preserve_completed_result(self):
        self.f.add()
        for reasons in ([42],['private secret text'],['first']*33,{'reason':'first'},['UNKNOWN_FUTURE_REASON']):
            with self.subTest(reasons=reasons):
                self.f.rewrite_request(1,lambda r:r['recommendation'].update(reasons=reasons))
                value=self.assert_original();self.assertEqual(value['result']['state'],'estimated');self.assert_unavailable(value,valid=True)
    def test_malformed_full_reason_preserves_completed_result(self):
        self.f.add();self.f.rewrite_request(1,lambda r:r.update(full_reason=[False]))
        value=self.assert_original();self.assertEqual(value['result']['state'],'estimated');self.assert_unavailable(value,valid=True)
    def test_timing_and_interval_types_bounded_public_summary(self):
        self.f.add()
        changes=[lambda r:r['timing'].update(elapsed_seconds=0,state='continuous',reason=None),
                 lambda r:r['timing'].update(reason='PRIVATE_CONTENT'),lambda r:r['timing'].update(extra=True),
                 lambda r:r['recommendation'].update(requested_interval_seconds=True),
                 lambda r:r['recommendation'].update(supported_interval_seconds=1.0)]
        saved=copy.deepcopy(self.f.requests[1])
        for change in changes:
            with self.subTest(change=change):
                self.f.requests[1]=copy.deepcopy(saved);self.f.rewrite_request(1,change)
                value=self.assert_original();self.assert_unavailable(value,valid=True)
    def test_mode_or_mask_invalid_never_emits_decision(self):
        self.f.add();self.f.rewrite_request(1,lambda r:r['recommendation'].update(requested_mode='AUTO'))
        self.assert_unavailable(self.assert_original())
    def test_unknown_identity_and_missing_storage_are_not_false_absence(self):
        value=reader.read_event(self.f.store,False,SOURCE,PIPE,CONTEXT);self.assert_unavailable(value)
        self.assertIsNone(value['decision_evidence']['request_exists']);self.assertIsNone(value['decision_evidence']['completion_exists'])
        value=reader.read_event(Store(Path(self.tmp.name)/'missing'),1,SOURCE,PIPE,CONTEXT)
        self.assert_unavailable(value);self.assertIsNone(value['decision_evidence']['request_exists'])
    def test_all_getters_leave_sqlite_bytes_and_inventory_unchanged(self):
        self.f.add();path=Path(self.tmp.name)/'captures.sqlite3';before=path.read_bytes();files=set(Path(self.tmp.name).iterdir())
        for _ in range(3):self.assert_original()
        self.assertEqual(path.read_bytes(),before);self.assertEqual(set(Path(self.tmp.name).iterdir()),files)
    def test_trial_context_sidecars_only_and_duplicate_counts_unchanged(self):
        self.f.add();self.f.add(2,mask=[False]*4+[True]*2,reason=None)
        recognition=type('SyntheticRecognition',(),{'store':self.f.store,'stored':lambda *args:(_ for _ in ()).throw(AssertionError('NO LEGACY FALLBACK'))})()
        value=trial_results.build(self.f.trial(),recognition,REQUEST_ID)
        with patch.object(reader,'read_event',original.read_event):old=trial_results.build(self.f.trial(),recognition,REQUEST_ID)
        clean=copy.deepcopy(value);clean['frames']=[strip(frame) for frame in clean['frames']]
        self.assertEqual(clean,old);self.assertEqual(value['processing'],dict(estimated=1,rejected=0,pending=0,unavailable=0))
        self.assertTrue(value['processing_complete']);self.assertEqual([v['decision']['requested_mode'] for v in value['frames']],['FULL','LAST_TWO'])
    def test_trial_rejected_complete_and_pending_states_unchanged(self):
        self.f.add(state='rejected');recognition=type('SyntheticRecognition',(),{'store':self.f.store})()
        value=trial_results.build(self.f.trial(),recognition,REQUEST_ID)
        self.assertTrue(value['processing_complete']);self.assertEqual(value['processing']['rejected'],1)
        with self.f.store.connect() as db:db.execute('DELETE FROM event_recognition_bindings')
        value=trial_results.build(self.f.trial(),recognition,REQUEST_ID)
        self.assertFalse(value['processing_complete']);self.assertEqual(value['state'],'pending');self.assertNotIn('decision',value['frames'][0])
    def test_legacy_full_trial_payload_exactly_unchanged_no_sidecars(self):
        self.f.add();self.f.add(2)
        saved=dict(processed_at='2026-10-06T00:01:00Z',result=self.f.results[1]);calls=[]
        recognition=type('SyntheticRecognition',(),{'store':self.f.store,'stored':lambda ignored,sha,pipeline:(calls.append((sha,pipeline)) or copy.deepcopy(saved))})()
        value=trial_results.build(self.f.trial(context=False),recognition,REQUEST_ID)
        self.assertEqual(len(calls),1);self.assertTrue(value['processing_complete'])
        for frame in value['frames']:
            self.assertEqual(set(frame),{'frame','processed_at','result'});self.assertEqual(strip(frame),dict(frame=frame['frame'],**saved))

if __name__=='__main__':unittest.main(verbosity=2)
