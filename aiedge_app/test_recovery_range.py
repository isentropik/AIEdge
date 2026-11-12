import copy
import unittest
from unittest.mock import patch
from datetime import timezone
from decimal import Decimal
from recovery_range import RecoveryRange
from daily_constraints import WorkLimit
import test_daily_empirical as fixtures

class RecoveryTests(unittest.TestCase):
    def setUp(self):
        f=fixtures.DailyEmpiricalTests();f.setUp();self.f=f
        self.rows=f.rows[1:];self.engine=RecoveryRange()
        self.contexts={r['event_observation']['context_id']:('a'*64,'b'*64,1) for r in self.rows}
        self.before=copy.deepcopy(self.rows)
    def run_range(self):
        f=self.f
        with patch('recovery_range.daily_records',side_effect=lambda db,a,b,s:[r for r in self.rows if a<=r['event_observation']['event_id']<=b]), patch('daily_empirical.evidence',side_effect=lambda db,rs,p,b:[Decimal(0)]*len(rs)):
            return self.engine.calculate(None,f.f.day,timezone.utc,f.doc,dict(f.base,through=self.rows[-1]['event_observation']),f.policy,self.contexts)
    def test_saved_unknown_gap_is_not_rewritten(self):
        result,reason=self.run_range();self.assertIsNone(reason)
        self.assertEqual((result['lower'],result['upper']),('2.00','2.00'))
        self.assertEqual(self.rows,self.before);self.assertIsNone(self.rows[-1]['delta'])
    def test_missing_origin_withholds(self):
        self.f.policy['elapsed_start_event']=99
        self.assertEqual(self.run_range(),(None,'unavailable'))
    def test_context_mismatch_withholds(self):
        self.contexts={k:('x'*64,'b'*64,1) for k in self.contexts}
        self.assertEqual(self.run_range(),(None,'unavailable'))
    def test_timeout_has_no_partial_published_range(self):
        with patch('recovery_range.interval_edges',side_effect=WorkLimit):
            self.assertEqual(self.run_range(),(None,'rebuilding_saved_history'))
        self.assertIsNotNone(self.run_range()[0])
    def test_clock_change_withholds(self):
        self.rows[-1]['event_observation']['clock_id']='changed'
        self.assertEqual(self.run_range(),(None,'unavailable'))
    def test_unknown_turn_remains_a_range(self):
        self.rows[-1]['event_observation']['monotonic_us']+=60000000
        self.rows[-1]['event_observation']['captured_at']='2026-11-07T00:02:00+00:00'
        self.f.policy['slow_allowance_ft3']=100
        result,_=self.run_range();self.assertGreater(Decimal(result['upper']),Decimal(result['lower']))
    def test_accumulation_beyond_old_window_restart_and_append(self):
        f=self.f
        # 40,000 events: strictly more than the old 32,768-event window.
        self.rows=[f.f.row(i,i,[(100+Decimal(i)/100,100+Decimal(i)/100)]) for i in range(2,40003)]
        for row in self.rows:
            row['event_observation']['format_id']='b'*64
        self.contexts={self.rows[0]['event_observation']['context_id']:('a'*64,'b'*64,1)}
        # No empirical tightening required for these exact known-use readings.
        with patch('recovery_range.interval_edges',return_value=[(2,3,Decimal(0),Decimal(100))]):
            result,reason=self.run_range()
            while reason=='rebuilding_saved_history':result,reason=self.run_range()
            self.assertIsNone(reason);self.assertEqual(result['lower'],'400.00');self.assertEqual(result['upper'],'400.00')
            self.assertEqual(self.run_range()[0],result)
            old=self.engine;self.engine=RecoveryRange()
            again,reason=self.run_range()
            while reason=='rebuilding_saved_history':again,reason=self.run_range()
            self.assertEqual(again,result)
            self.rows=self.rows[:-100];short,_=self.run_range()
            self.assertEqual(short['upper'],'399.00')

    def test_policy_change_invalidates_prefix(self):
        self.run_range();old=self.engine.key
        self.f.policy['capacity_cfh']=776
        self.assertIsNotNone(self.run_range()[0]);self.assertNotEqual(self.engine.key,old)
    def test_endpoint_digest_not_borrowed(self):
        with patch('recovery_range._tighten',side_effect=ValueError('contradictory evidence')):
            self.assertEqual(self.run_range(),(None,'unavailable'))
        self.assertIsNone(self.engine.checkpoint)
    def test_bounded_checkpoint_skips_no_unbounded_rows(self):
        f=self.f
        self.rows=[f.f.row(i,i*10,[(100+i,100+i)]) for i in range(2,8)]
        for r in self.rows:r['event_observation']['format_id']='b'*64
        self.rows[2]['absolute']={}
        self.contexts={'c':('a'*64,'b'*64,1)}
        with patch('recovery_range.CHUNK_EVENTS',2), patch('recovery_range.interval_edges',return_value=[(2,3,Decimal(0),Decimal(100))]):
            result,_=self.run_range()
        self.assertEqual((result['lower'],result['upper']),('5.00','5.00'))
        self.assertEqual(result['start']['event_id'],2)
    def test_segment_inheritance_is_explicit(self):
        from unittest.mock import Mock
        self.run_range();self.engine.segment='old'
        db=Mock();db.execute.return_value.fetchone.return_value=None
        f=self.f
        # No inherited prefix: old cache must be dropped before origin reload.
        with patch('recovery_range.daily_records',side_effect=ValueError('origin read')):
            result,reason=self.engine.calculate(db,f.f.day,timezone.utc,f.doc,f.base,f.policy,self.contexts)
        self.assertEqual((result,reason),(None,'unavailable'))
        self.assertIsNone(self.engine.checkpoint)
    def test_mqtt_uses_recovery_and_short_rebuild_retry(self):
        from test_daily_publication import DailyPublicationTests
        f=DailyPublicationTests();f.setUp()
        try:
            f.publisher.evidence_policy=dict(self.f.policy)
            with patch('daily_empirical.refine',side_effect=lambda db,rows,day,zone,doc,result,policy,**kw:result), patch.object(f.publisher.recovery,'calculate',return_value=(None,'rebuilding_saved_history')) as calc:
                f.publish();self.assertEqual(f.payloads()[-1]['elapsed_unavailable_reason'],'rebuilding_saved_history')
                self.assertEqual(f.publisher.next_refresh,f.clock+30);self.assertEqual(calc.call_count,1)
            f.clock+=31
            elapsed=dict(start={'event_id':2},through=f.result['through'],lower='1.00',upper='6.00')
            with patch('daily_empirical.refine',side_effect=lambda db,rows,day,zone,doc,result,policy,**kw:result), patch.object(f.publisher.recovery,'calculate',return_value=(elapsed,None)):
                f.publish();self.assertEqual(f.payloads()[-1]['elapsed_range'],elapsed)
                self.assertEqual(f.publisher.next_refresh,f.clock+300)
        finally:f.doCleanups()
