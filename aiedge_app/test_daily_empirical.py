import copy
import unittest
from datetime import date, timezone
from decimal import Decimal
from unittest.mock import patch
from daily_constraints import Budget, WorkLimit, _tighten
from daily_empirical import validate, comparisons, evidence, refine
import test_daily_constraints as fixture

class DailyEmpiricalTests(unittest.TestCase):
    def setUp(self):
        self.f = fixture.DailyConstraintsTests()
        self.rows = [self.f.row(1,-1,[(100,100)]),self.f.row(2,1,[(100,100)]),
                     self.f.row(3,60,[(102,102),(107,107),(112,112)])]
        self.policy = dict(capacity_cfh=775, slow_allowance_ft3=6, pipeline_id='a'*64,format_id='b'*64,elapsed_start_event=2)
        self.doc = dict(self.f.document,dials=[dict(value_per_revolution=n) for n in (10000000,1000000,100000,10000,1000,5)])
        for r in self.rows:
            r['event_observation'].update(format_id='b'*64,source_sha256='c'*64)
            r['observation_support']={'pipeline_id':'a'*64,'reader_observed':[True]*6}
        self.base=dict(day='2026-11-07',lower='0.00',upper='12.00',before=self.rows[0]['event_observation'],after=self.rows[1]['event_observation'],through=self.rows[-1]['event_observation'],segment_id='s')
    def solve(self, values=None, policy=None):
        supplied=values or [Decimal(0)]*2
        mapping={1:supplied[0],2:supplied[0],3:supplied[-1]}
        with patch('daily_empirical.evidence',side_effect=lambda db,rows,p,b:[mapping[r['event_observation']['event_id']] for r in rows]):
            return refine(None,self.rows,self.f.day,timezone.utc,self.doc,self.base,self.policy if policy is None else policy)
    def test_default_disabled(self):self.assertEqual(self.solve(policy={}),self.base)
    def test_complete_policy(self):self.assertEqual(validate(self.policy),self.policy)
    def test_reject_incomplete(self):
        for k in self.policy:
            p=dict(self.policy);p.pop(k)
            if k!='elapsed_start_event':
                with self.assertRaises(ValueError):validate(p)
    def test_reject_unreviewed_allowance(self):
        for v in (True,5.9,'NaN','Infinity',101):
            with self.assertRaises((ValueError,ArithmeticError)):validate(dict(self.policy,slow_allowance_ft3=v))
    def test_identity_mandatory(self):
        for k in ('pipeline_id','format_id'):
            with self.assertRaises(ValueError):validate(dict(self.policy,**{k:'x'}))
    def test_elapsed_origin_integer(self):
        for v in (True,0,-1,1.1):
            with self.assertRaises(ValueError):validate(dict(self.policy,elapsed_start_event=v))
    def test_removes_extra_bands_and_preserves_unknowns(self):
        before=copy.deepcopy(self.rows);r=self.solve()
        self.assertTrue(r['empirical_constraints_applied']);self.assertEqual((r['lower'],r['upper']),('2.00','2.00'))
        self.assertEqual(self.rows,before);self.assertTrue(all(x['delta'] is None for x in self.rows))
    def test_elapsed_and_day_are_separate(self):
        r=self.solve();self.assertEqual(r['elapsed_range']['start']['event_id'],2)
        self.assertEqual(r['before']['event_id'],1);self.assertEqual(r['elapsed_range']['through'],self.base['through'])
    def test_missing_elapsed_origin_does_not_invent_one(self):
        r=self.solve(policy=dict(self.policy,elapsed_start_event=999))
        self.assertTrue(r['empirical_constraints_applied']);self.assertIsNone(r['elapsed_range'])
        self.assertEqual(r['elapsed_unavailable_reason'],'start_not_in_saved_window')
    def test_outward_and_no_false_accuracy(self):
        r=self.solve();self.assertFalse(r['accuracy_verified']);self.assertEqual(r['unconstrained_upper'],'12.00')
    def test_contradiction_returns_original_wider_range(self):
        r=self.solve([Decimal(100),Decimal(0)])
        # Out-of-scope comparisons are omitted, never invented. Force contradiction explicitly.
        with patch('daily_empirical.comparisons',return_value=[(1,3,Decimal(50),Decimal(51))]):r=self.solve()
        self.assertFalse(r['empirical_constraints_applied']);self.assertEqual(r['upper'],'12.00')
    def test_work_exhaustion_returns_baseline(self):
        with patch('daily_empirical.evidence',side_effect=WorkLimit):r=refine(None,self.rows,self.f.day,timezone.utc,self.doc,self.base,self.policy)
        self.assertEqual(r['empirical_fallback'],'work_limit');self.assertEqual(r['upper'],'12.00')
    def test_missing_evidence_returns_baseline(self):
        with patch('daily_empirical.evidence',side_effect=ValueError):r=refine(None,self.rows,self.f.day,timezone.utc,self.doc,self.base,self.policy)
        self.assertFalse(r['empirical_constraints_applied'])
    def test_one_hour_limit(self):
        self.rows[-1]['event_observation']['monotonic_us']+=3600000001
        self.assertFalse(any(e[1]==3 for e in comparisons(self.rows,[Decimal(0)]*3,Decimal(6),Budget())))
    def test_movement_scope(self):
        self.assertFalse(any(e[1]==3 for e in comparisons(self.rows,[Decimal(0),Decimal(0),Decimal(28)],Decimal(6),Budget())))
    def test_context_change_not_bridged_by_slow_allowance(self):
        self.rows[-1]['event_observation']['context_id']='new'
        self.assertFalse(any(e[1]==3 for e in comparisons(self.rows,[Decimal(0)]*3,Decimal(6),Budget())))
    def test_geometry_mismatch_falls_back(self):
        self.doc['dials'][-2]['value_per_revolution']=100
        self.assertFalse(self.solve()['empirical_constraints_applied'])
    def test_daily_budget_failure_retains_only_completed_elapsed(self):
        bounded=dict(self.base,lower='2.00',upper='2.00')
        with patch('daily_empirical._tighten',side_effect=[bounded,WorkLimit]):r=self.solve()
        self.assertFalse(r['empirical_constraints_applied']);self.assertEqual(r['upper'],'12.00')
        self.assertEqual(r['elapsed_range']['upper'],'2.00')
    def test_capacity_is_only_an_upper_bound_not_assumed_flow(self):
        self.rows[-1]['event_observation']['monotonic_us']=112000000
        self.rows[-1]['event_observation']['captured_at']='2026-11-07T00:00:12+00:00'
        r=self.solve(policy=dict(self.policy,slow_allowance_ft3=100))
        self.assertEqual((r['lower'],r['upper']),('2.00','2.00'))
    def test_saved_evidence_identity_and_source(self):
        def get(db,event,sha,pipeline,context,flags):
            row=next(r for r in self.rows if r['event_observation']['event_id']==event)
            return {'result':{'state':'estimated','event_observation':copy.deepcopy(row['event_observation']),'dial_positions':[{'position':1}]*6}}
        with patch('event_observation_read.read_batch',side_effect=lambda db,sources,pipeline:[get(db,s['event_id'],s['source_sha256'],pipeline,s['context_id'],{}) for s in sources]):
            self.assertEqual(evidence(None,self.rows,self.policy,Budget()),[Decimal(100)]*3)
            self.rows[0]['observation_support']['pipeline_id']='d'*64
            with self.assertRaises(ValueError):evidence(None,self.rows,self.policy,Budget())
    def test_saved_mask_must_match_ledger_mask(self):
        r=self.rows[0];r['observation_support']['reader_observed'][0]=False
        raw=dict(state='estimated',event_observation=r['event_observation'],dial_positions=[{'position':1}]*6)
        with patch('event_observation_read.read_batch',return_value=[{'result':raw}]):
            with self.assertRaises(ValueError):evidence(None,[r],self.policy,Budget())
    def test_unobserved_dial_not_borrowed(self):
        r=self.rows[0];r['observation_support']['reader_observed'][-2]=False
        with patch('event_observation_read.read_batch',return_value=[{'result':{'state':'estimated','event_observation':r['event_observation']}}]):
            with self.assertRaises(ValueError):evidence(None,[r],self.policy,Budget())

class EmpiricalIntegrationTests(unittest.TestCase):
    def test_sqlite_saved_getter_is_read_only_and_rejects_tamper(self):
        import test_event_recognition as f
        from event_observation_read import _read
        original=f.FakeReader
        class SixReader(original):
            def __init__(self):
                super().__init__();self.dials=[{'name':str(i)} for i in range(6)]
            def read_jpeg(self, blob, observed=None):
                return super().read_jpeg(blob, [True]*6 if observed is None else observed)
        doc=dict(f.DOC,dials=[dict(index=i,value_per_revolution=v,position_error=.1) for i,v in enumerate((10000000,1000000,100000,10000,1000,5))])
        with patch.object(f,'FakeReader',SixReader),patch.object(f,'DOC',doc):
            fixture=f.EventRecognitionTests();fixture.setUp()
            try:
                event,sha,result=fixture.complete(1000000)
                row=dict(event_observation=result['event_observation'],observation_support=dict(pipeline_id=f.PIPELINE,reader_observed=[True]*6))
                policy=dict(capacity_cfh=775,slow_allowance_ft3=6,pipeline_id=f.PIPELINE,format_id=fixture.worker.format_id)
                with fixture.store.connect() as db:
                    before=list(db.iterdump());calls=list(fixture.reader.calls)
                    self.assertEqual(evidence(db,[row],policy,Budget()),[Decimal(100)])
                    self.assertEqual(list(db.iterdump()),before);self.assertEqual(fixture.reader.calls,calls)
                    db.execute("UPDATE event_recognition_cache SET result='{}'")
                    with self.assertRaises(ValueError):evidence(db,[row],policy,Budget())
            finally:fixture.tearDown()
    def test_database_failure_keeps_wider_value(self):
        import sqlite3
        f=DailyEmpiricalTests();f.setUp()
        with patch('daily_empirical.evidence',side_effect=sqlite3.OperationalError('locked')):
            result=refine(None,f.rows,f.f.day,timezone.utc,f.doc,f.base,f.policy)
        self.assertEqual(result['upper'],'12.00');self.assertFalse(result['empirical_constraints_applied'])
    def test_mqtt_publishes_bound_result_and_exact_source(self):
        import test_daily_publication as f
        from daily_mqtt import DailyPublisher
        fixture=f.DailyPublicationTests();fixture.setUp()
        p=DailyEmpiricalTests();p.setUp()
        try:
            fixture.publisher=DailyPublisher(fixture.store,p.policy)
            tighter=dict(fixture.result,lower='10.00',upper='10.20',empirical_constraints_applied=True)
            with patch('daily_empirical.refine',return_value=tighter):fixture.publish()
            payload=fixture.payloads()[-1]
            self.assertEqual(payload['label'],'10.00\u201310.20 ft\u00b3');self.assertEqual(payload['through'],fixture.result['through'])
            self.assertEqual(payload['segment_id'],fixture.result['segment_id'])
        finally:fixture.doCleanups()
    def test_mqtt_refuses_mismatched_refinement_endpoint(self):
        import test_daily_publication as f
        from daily_mqtt import DailyPublisher
        fixture=f.DailyPublicationTests();fixture.setUp()
        p=DailyEmpiricalTests();p.setUp()
        try:
            fixture.publisher=DailyPublisher(fixture.store,p.policy)
            wrong=copy.deepcopy(fixture.result);wrong['through']['event_id']+=1
            with patch('daily_empirical.refine',return_value=wrong):fixture.publish()
            self.assertEqual(fixture.payloads()[-1],{})
        finally:fixture.doCleanups()
    def test_options_default_disabled_and_reject_incomplete(self):
        from options import validate as options,InvalidOptions
        self.assertEqual(options({})['daily_evidence_policy'],{})
        with self.assertRaises(InvalidOptions):options({'daily_evidence_policy':{'capacity_cfh':775}})

if __name__=='__main__':unittest.main()
