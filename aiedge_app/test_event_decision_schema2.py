"""Synthetic schema1/schema2 history and coordinator integration boundaries."""
import copy,json,sqlite3,tempfile,unittest
from pathlib import Path
import event_observation_read as reader
from test_event_decision_observability import Fixture,SOURCE,PIPE,CONTEXT,digest,strip
import trial_results

class DecisionSchema2Tests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.f=Fixture(self.temp.name)
    def tearDown(self):self.temp.cleanup()
    def schema2(self,event=1,certificate=None):
        def update(request):
            request.update(schema_version=2,observation_eligibility={'certificate':certificate,'certificate_sha256':digest(certificate)})
        self.f.rewrite_request(event,update)
    def test_schema2_initial_full_none_prior_certificate_keeps_result(self):
        self.f.add();before=strip(self.f.read());self.schema2();after=self.f.read()
        expected=copy.deepcopy(before);expected['result']['event_observation']['request_sha256']=digest(self.f.requests[1])
        self.assertEqual(strip(after),expected);self.assertEqual(after['decision']['requested_mode'],'FULL')
        self.assertEqual(after['decision_evidence']['state'],'complete')
    def test_schema2_observation_only_reason_does_not_export_certificate_or_scalar(self):
        self.f.add(mask=[False]*4+[True]*2,reason='observation_only_unbounded_accounting')
        self.schema2(certificate={'TEST_ONLY_PRIVATE':'not public','accounting_uncertain':True,'relaxation_eligible':True,'continuity_certified':False,'physical_scalar':None})
        value=self.f.read();self.assertEqual(value['decision']['reasons'],['observation_only_unbounded_accounting'])
        self.assertEqual(value['decision']['reader_observed'],[False]*4+[True]*2)
        self.assertNotIn('observation_eligibility',value['decision']);self.assertNotIn('physical_scalar',value['decision'])
        self.assertNotIn('TEST_ONLY_PRIVATE',json.dumps(value))
    def test_schema2_new_full_reasons_are_typed_saved_evidence(self):
        self.f.add();self.schema2()
        for reason in ('fine_observation_uncertain','full_refresh_uncertain'):
            with self.subTest(reason=reason):
                self.f.rewrite_request(1,lambda r:r.update(full_reason=[reason],recommendation={**r['recommendation'],'reasons':[reason]}))
                value=self.f.read();self.assertEqual(value['decision']['full_reason'],[reason]);self.assertEqual(value['decision']['requested_mode'],'FULL')
    def test_five_argument_internal_getter_preserves_result_and_no_sqlite_write(self):
        self.f.add();self.schema2();path=Path(self.temp.name)/'captures.sqlite3';before=path.read_bytes()
        db=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)
        try:
            db.execute('BEGIN');value=reader._read(db,1,SOURCE,PIPE,CONTEXT)
        finally:db.close()
        self.assertEqual(value,self.f.read());self.assertEqual(path.read_bytes(),before)
    def test_schema2_certificate_hash_mismatch_fails_closed(self):
        self.f.add();self.schema2()
        self.f.rewrite_request(1,lambda r:r['observation_eligibility'].update(certificate_sha256='f'*64))
        value=self.f.read();self.assertEqual(value['result']['state'],'unavailable');self.assertNotIn('decision',value)
        self.assertFalse(value['decision_evidence']['completion_valid'])
    def test_schema2_unknown_public_reason_suppresses_only_summary(self):
        self.f.add();self.schema2();self.f.rewrite_request(1,lambda r:r.update(full_reason=['PRIVATE_FUTURE_REASON']))
        value=self.f.read();self.assertEqual(value['result']['state'],'estimated');self.assertNotIn('decision',value)
        self.assertTrue(value['decision_evidence']['completion_valid']);self.assertNotIn('PRIVATE_FUTURE_REASON',json.dumps(value))
    def test_mixed_historical_versions_keep_trial_counts_and_per_event_masks(self):
        self.f.add();self.f.add(2,mask=[False]*4+[True]*2,reason='observation_only_unbounded_accounting');self.schema2(2)
        recognition=type('SyntheticRecognition',(),{'store':self.f.store})()
        value=trial_results.build(self.f.trial(),recognition,'d'*32)
        self.assertTrue(value['processing_complete']);self.assertEqual(value['processing']['estimated'],1)
        self.assertEqual([f['decision']['requested_mode'] for f in value['frames']],['FULL','LAST_TWO'])
        self.assertEqual([f['result']['event_observation']['event_id'] for f in value['frames']],[1,2])
        self.assertEqual(value['frames'][1]['result']['dial_positions'][0]['state'],'unavailable')

if __name__=='__main__':unittest.main()
