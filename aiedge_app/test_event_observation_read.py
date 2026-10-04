"""Read-only historical event fixtures; fake reader and invented JPEG envelopes."""
import copy,json,hashlib,unittest
import test_event_recognition as fixtures
from event_recognition import EventRecognition
from event_observation_read import read_event
from event_selection import encoded,digest

class HistoricalEventReadTests(unittest.TestCase):
    def setUp(self):self.fixture=fixtures.EventRecognitionTests();self.fixture.setUp();self.f=self.fixture;self.store=self.f.store
    def tearDown(self):self.fixture.tearDown()
    def snapshot(self):
        with self.store.connect() as db:dump='\n'.join(db.iterdump())
        return hashlib.sha256(dump.encode()).hexdigest(),hashlib.sha256((self.store.root/'captures.sqlite3').read_bytes()).hexdigest()
    def read(self,event,source,context=None):return read_event(self.store,event,source,fixtures.PIPELINE,context or self.f.worker.observation_context)
    def setup_two_masks(self):
        e1,s,_=self.f.complete(1000000,True);self.f.feedback(e1,s,'anchored');e2,s,_=self.f.complete(3000000,True);return e1,e2,s
    def test_same_sha_different_masks_explicit_event_and_readonly(self):
        e1,e2,s=self.setup_two_masks();before=self.snapshot();calls=copy.deepcopy(self.f.reader.calls)
        first,second=self.read(e1,s),self.read(e2,s)
        self.assertEqual(first['result']['event_observation']['event_id'],e1);self.assertEqual(second['result']['event_observation']['event_id'],e2);self.assertNotIn('observation_support',first['result']);self.assertEqual(second['result']['observation_support']['observed'],[False,True,True]);self.assertIsNone(first['processed_at']);self.assertEqual(self.snapshot(),before);self.assertEqual(self.f.reader.calls,calls)
    def test_historical_context_survives_new_policy_and_profile_pipeline(self):
        e1,e2,s=self.setup_two_masks();old_context=self.f.worker.observation_context
        new=EventRecognition(self.store,self.f.reader,fixtures.DOC,{**fixtures.CONFIG,'full_refresh_seconds':30},fixtures.CAPS)
        self.assertNotEqual(new.observation_context,old_context);self.assertEqual(new.stored_event(e2,s,fixtures.PIPELINE,old_context)['result']['state'],'estimated');self.assertEqual(new.stored_event(e2,s,fixtures.PIPELINE)['result']['state'],'pending')
        self.assertEqual(self.read(e1,s,old_context)['result']['state'],'estimated')
        alternate=fixtures.FakeReader();alternate.pipeline_id='b'*64;doc=copy.deepcopy(fixtures.DOC);doc['pipeline_id']=alternate.pipeline_id
        different=EventRecognition(self.store,alternate,doc,fixtures.CONFIG,fixtures.CAPS)
        self.assertEqual(different.stored_event(e2,s,fixtures.PIPELINE,old_context)['result']['state'],'estimated');self.assertEqual(alternate.calls,[])
    def test_pending_unbound_no_legacy_fallback(self):
        e,s=self.f.capture(1000000)
        with self.store.connect() as db:db.execute('INSERT INTO inference VALUES(?,?,?,?)',(s,fixtures.PIPELINE,'fake',encoded({'state':'estimated','physical_value':999})))
        before=self.snapshot();self.assertEqual(self.read(e,s)['result']['state'],'pending');self.assertEqual(self.snapshot(),before);self.assertEqual(self.f.reader.calls,[])
    def test_saved_request_no_completion_pending_without_processing(self):
        e,s,_=self.f.complete(1000000)
        with self.store.connect() as db:db.execute('DELETE FROM event_recognition_bindings')
        before=self.snapshot();self.assertEqual(self.read(e,s)['result']['state'],'pending');self.assertEqual(self.snapshot(),before)
    def test_invalid_identity_context_and_acquisition_fail_closed(self):
        e,s,_=self.f.complete(1000000)
        for event,source,pipeline,context in [(True,s,fixtures.PIPELINE,self.f.worker.observation_context),(e,'0'*64,fixtures.PIPELINE,self.f.worker.observation_context),(e,s,'b'*64,self.f.worker.observation_context),(e,s,fixtures.PIPELINE,'0'*64)]:
            self.assertEqual(read_event(self.store,event,source,pipeline,context)['result']['state'],'unavailable')
        with self.store.connect() as db:db.execute("UPDATE capture_clocks SET monotonic_us=monotonic_us+1")
        self.assertEqual(self.read(e,s)['result']['state'],'unavailable')
    def test_request_cache_completion_and_context_tamper(self):
        e,s,_=self.f.complete(1000000)
        mutations=[("UPDATE event_recognition_requests SET request='{}'",()),("UPDATE event_recognition_cache SET result='{}'",()),("UPDATE event_recognition_bindings SET mask_sha='BAD'",()),("UPDATE event_selection_contexts SET format_id=?",('0'*64,))]
        with self.store.connect() as db:
            originals={name:list(db.execute('SELECT * FROM '+name)) for name in ['event_recognition_requests','event_recognition_cache','event_recognition_bindings','event_selection_contexts']}
        for query,args in mutations:
            with self.store.connect() as db:
                for name,rows in originals.items():
                    db.execute('DELETE FROM '+name)
                    for row in rows:db.execute('INSERT INTO '+name+' VALUES('+','.join('?'*len(row))+')',row)
                db.execute(query,args)
            before=self.snapshot();self.assertEqual(self.read(e,s)['result']['state'],'unavailable');self.assertEqual(self.snapshot(),before)
    def test_malformed_duplicate_oversized_and_boolean_schema_requests(self):
        e,s,_=self.f.complete(1000000);original=self.f.request(e)
        values=['{"schema_version":1,"schema_version":1}',encoded({**original,'schema_version':True}),' '*32769,'null']
        for value in values:
            with self.store.connect() as db:db.execute('UPDATE event_recognition_requests SET request=?,request_sha=?',(value,digest({**original,'schema_version':True}) if 'true' in value else '0'*64))
            self.assertEqual(self.read(e,s)['result']['state'],'unavailable')
    def test_partial_rejection_attempt_is_historical_not_observed(self):
        e,s,_=self.f.complete(1000000);self.f.feedback(e,s,'anchored');self.f.reader.reject=True;e,s,_=self.f.complete(3000000);r=self.read(e,s)['result'];self.assertEqual(r['state'],'rejected');self.assertIn('observation_attempt',r);self.assertNotIn('observation_support',r)
    def test_old_decisions_not_recomputed_with_current_policy(self):
        e1,e2,s=self.setup_two_masks()
        from unittest.mock import patch
        with patch('event_recognition.recommend',side_effect=RuntimeError('must not apply new policy')):
            self.assertEqual(self.read(e2,s)['result']['state'],'estimated')
    def test_integer_mask_cannot_equal_boolean_cache_mask(self):
        e,s,_=self.f.complete(1000000)
        with self.store.connect() as db:db.execute("UPDATE event_recognition_cache SET mask='[1,1,1]'")
        self.assertEqual(self.read(e,s)['result']['state'],'unavailable')
        with self.assertRaisesRegex(ValueError,'cache_mask'):self.f.worker.accounting_result(e,s,fixtures.PIPELINE)

if __name__=='__main__':unittest.main()
