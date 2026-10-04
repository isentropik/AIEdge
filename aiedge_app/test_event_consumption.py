"""Synthetic event→selection→native accounting→publication integration."""
import copy,hashlib,json,os,sqlite3,tempfile,unittest
from contextlib import contextmanager
from datetime import datetime,timedelta,timezone
from pathlib import Path
from unittest.mock import patch
from capture import Store
from consumption import Consumption
from event_recognition import EventRecognition
from reading_format import FormatStore,validate
from native import Native
from service import publication_state

PIPELINE='a'*64
LIBRARY=os.environ.get('AIEDGE_ACCOUNTING_LIBRARY')
READING=os.environ.get('AIEDGE_READING_LIBRARY')

class SyntheticReader:
    pipeline_id=PIPELINE
    def __init__(self,periods):
        self.periods=periods;self.dials=[{'name':str(i)} for i in range(len(periods))];self.calls=[];self.native=Native(READING)
    def read_jpeg(self,blob,observed=None):
        quantity=float(blob[2:-2].decode());mask=[True]*len(self.periods) if observed is None else list(observed)
        self.calls.append((hashlib.sha256(blob).hexdigest(),mask))
        result={'state':'estimated','pipeline_id':self.pipeline_id,'source_sha256':hashlib.sha256(blob).hexdigest(),
                'training_allowed':False,'accuracy_verified':False,
                'dial_positions':[{'state':'estimated','position':quantity%p/p*10} if flag else {'state':'unavailable','position':None} for p,flag in zip(self.periods,mask)]}
        if observed is not None:result['observation_support']={'schema_version':1,'pipeline_id':self.pipeline_id,'source_sha256':result['source_sha256'],'observed':mask}
        return result

@unittest.skipUnless(LIBRARY and READING,'host native libraries required')
class EventConsumptionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.store=Store(self.temp.name);self.reader=SyntheticReader([10000,1000,5]);self.counter=0
        self.start=datetime.now(timezone.utc)-timedelta(seconds=30)
        self.document={'version':1,'pipeline_id':PIPELINE,'unit':'ft3','maximum_rate_per_second':.5,
                       'dials':[{'index':i,'value_per_revolution':p,'position_error':.01} for i,p in enumerate(self.reader.periods)]}
        self.config={'normal_interval_seconds':1,'urgent_interval_seconds':1,'full_refresh_seconds':3,'phase_probe_budget':.25,'uncertainty_probe_width':.3}
        self.capabilities={'minimum_interval_seconds':.05,'partial_recognition':True}
        self.recognition=EventRecognition(self.store,self.reader,self.document,self.config,self.capabilities)
        self.formats=FormatStore(self.temp.name,self.recognition);self.saved=self.formats.save(self.document,None)
        self.worker=Consumption(self.store,self.recognition,self.formats,LIBRARY)
    def tearDown(self):self.worker._drop();self.temp.cleanup()
    def event(self,quantity,tick=None,clock='test-a',camera='fixture'):
        self.counter+=1;tick=self.counter*1000000 if tick is None else tick
        blob=b'\xff\xd8'+str(quantity).encode()+b'\xff\xd9';digest=hashlib.sha256(blob).hexdigest()
        stamp=(self.start+timedelta(microseconds=tick)).isoformat()
        self.store.add(camera,blob,{'X-AIEdge-Frame-Id':str(self.counter),'X-AIEdge-Captured-At':stamp,'X-AIEdge-SHA256':digest,'X-AIEdge-Clock-Id':clock,'X-AIEdge-Capture-Monotonic-Us':str(tick)})
        with self.store.connect() as db:event=db.execute('SELECT MAX(event_id) FROM capture_events').fetchone()[0]
        return event,digest
    def consume(self):self.assertTrue(self.worker.once());return self.worker.status()
    def recognize_consume(self,quantity,**kwargs):
        event,digest=self.event(quantity,**kwargs);self.assertTrue(self.recognition.once());return self.consume()
    def records(self):
        with self.store.connect() as db:return list(db.execute('SELECT segment_id,event_id,result FROM consumption_records ORDER BY event_id,segment_id'))
    def restart_consumption(self):
        self.worker._drop();self.worker=Consumption(self.store,self.recognition,self.formats,LIBRARY)
        while self.worker.once():pass
        return self.worker.status()
    def test_duplicate_partial_then_full_has_separate_cache_and_every_event_is_accounted(self):
        self.assertEqual(self.recognize_consume(100.0)['state'],'anchored')
        second=self.recognize_consume(100.1);self.assertEqual(second['observation_support']['reader_observed'],[False,True,True]);self.assertAlmostEqual(second['value'],.1);self.assertIsNone(second['absolute']['value'])
        third=self.recognize_consume(100.1);self.assertNotEqual(second['event_id'],third['event_id']);self.assertEqual(len(self.reader.calls),2)
        fourth=self.recognize_consume(100.1);self.assertEqual(fourth['observation_support']['reader_observed'],[True]*3);self.assertEqual(len(self.reader.calls),3)
        self.assertEqual(self.reader.calls[-1][0],self.reader.calls[-2][0]);self.assertEqual(self.reader.calls[-1][1],[True]*3)
        self.assertEqual(len(self.records()),4);self.assertEqual(self.store.status()['unique_images'],2);self.assertEqual(self.restart_consumption(),fourth)
    def test_selection_waits_for_durable_feedback_and_consumption_never_uses_legacy_fallback(self):
        event,digest=self.event(100.0)
        legacy=self.reader.read_jpeg(self.store.image(digest))
        with self.store.connect() as db:db.execute('INSERT INTO inference VALUES(?,?,?,?)',(digest,PIPELINE,self.start.isoformat(),json.dumps(legacy)))
        self.assertFalse(self.worker.once());self.assertEqual(self.worker.status()['state'],'pending')
        self.assertTrue(self.recognition.once());self.event(100.1);self.assertFalse(self.recognition.once())
        self.consume();self.assertTrue(self.recognition.once());self.consume();self.assertEqual(len(self.records()),2)
        with self.store.connect() as db:self.assertEqual(json.loads(db.execute('SELECT result FROM inference').fetchone()[0]),legacy)
    def test_clock_reset_full_reanchors_preserving_unresolved_previous_segment(self):
        first=self.recognize_consume(100.0);before=self.records()
        second=self.recognize_consume(100.1,tick=1000000,clock='test-b')
        self.assertEqual(second['observation_support']['reader_observed'],[True]*3);self.assertEqual(second['state'],'anchored');self.assertNotEqual(first['segment_id'],second['segment_id']);self.assertEqual(second['prior_segment_id'],first['segment_id']);self.assertIsNone(second['unresolved_gap']['delta']);self.assertEqual(self.restart_consumption(),second)
        for row in before:self.assertIn(row,self.records())
    def test_bad_event_binding_cannot_advance_or_persist_accounting(self):
        self.recognize_consume(100.0);event,digest=self.event(100.1);self.assertTrue(self.recognition.once());before=self.records()
        getter=self.recognition.accounting_result
        def changed(*args):
            value=json.loads(getter(*args));value['event_observation']['event_id']+=1;return json.dumps(value)
        with patch.object(self.recognition,'accounting_result',side_effect=changed),self.assertRaisesRegex(ValueError,'consumption_event_binding_invalid'):self.worker.once()
        self.assertEqual(self.records(),before);state=self.consume();self.assertAlmostEqual(state['value'],.1);self.assertEqual(state['event_id'],event)
    def test_storage_failure_replays_native_state_from_durable_records_without_rerunning_inference(self):
        self.recognize_consume(100.0);self.event(100.1);self.assertTrue(self.recognition.once());connect=self.store.connect
        class Proxy:
            def __init__(self,db):self.db=db
            def execute(self,sql,*args):
                if sql.startswith('INSERT INTO consumption_records'):raise sqlite3.OperationalError('synthetic interrupted commit')
                return self.db.execute(sql,*args)
        @contextmanager
        def broken():
            with connect() as db:yield Proxy(db)
        with patch.object(self.store,'connect',side_effect=broken),self.assertRaises(sqlite3.OperationalError):self.worker.once()
        self.assertEqual(len(self.records()),1);calls=len(self.reader.calls);state=self.restart_consumption();self.assertAlmostEqual(state['value'],.1);self.assertEqual(len(self.records()),2);self.assertEqual(len(self.reader.calls),calls)
    def test_event_rejection_is_accounted_before_publication_and_never_replaced_by_prior_number(self):
        self.recognize_consume(100.0);event,digest=self.event(100.1)
        with patch.object(self.reader,'read_jpeg',side_effect=ValueError('synthetic obscured image')):self.assertTrue(self.recognition.once())
        before=publication_state(self.store,self.recognition,self.formats,self.worker);self.assertIsNone(before['reading'].get('value'))
        state=self.consume();self.assertEqual(state['state'],'unavailable');after=publication_state(self.store,self.recognition,self.formats,self.worker);self.assertEqual(after['_timing_event_id'],event);self.assertIsNone(after['reading'].get('value'));self.assertEqual(len(self.records()),2)
    def test_context_floor_aligns_consumer_when_captures_arrive_between_constructors(self):
        self.worker._drop()
        # A fresh policy context is created after one retained legacy event.
        first,digest=self.event(100.0);cfg=copy.deepcopy(self.config);cfg['full_refresh_seconds']=4
        self.recognition=EventRecognition(self.store,self.reader,self.document,cfg,self.capabilities);self.assertEqual(self.recognition.observation_first_event,first)
        self.event(100.1);self.formats=FormatStore(self.temp.name,self.recognition)
        self.worker=Consumption(self.store,self.recognition,self.formats,LIBRARY)
        self.assertTrue(self.recognition.once());state=self.consume();self.assertEqual(state['event_id'],first)
        self.assertTrue(self.recognition.once());self.consume()
    def test_format_change_is_withheld_before_creating_or_reinterpreting_a_segment(self):
        self.recognize_consume(100.0);before=self.records();segment=self.worker.segment['segment_id']
        changed=copy.deepcopy(self.document);changed['unit']='m3';self.formats.save(changed,self.saved['revision'])
        self.assertFalse(self.worker.once());self.assertEqual(self.worker.status()['reason'],'consumption_selection_format_changed');self.assertEqual(self.worker.segment['segment_id'],segment);self.assertEqual(self.records(),before)

if __name__=='__main__':unittest.main()
