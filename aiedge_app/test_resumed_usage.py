import copy
import json
import os
import unittest
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from decimal import Decimal
from unittest.mock import Mock, patch
from resumed_usage import ResumedPublisher
from daily_empirical import validate
from daily_constraints import WorkLimit
from published_usage import snapshot
import test_daily_empirical as fixtures


class ResumedTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.DailyEmpiricalTests();self.f.setUp()
        self.rows=self.f.rows[1:];self.original=copy.deepcopy(self.rows)
        self.policy=dict(self.f.policy,resumed_start_event=2)
        self.engine=ResumedPublisher(None,self.policy)
        self.obs=dict(self.rows[-1]['event_observation'],segment_id=self.f.base['segment_id'])
        self.db=Mock();self.db.execute.return_value=[(self.obs['context_id'],'a'*64,'b'*64,1)]
    def calculate(self):
        def rows(db,a,b,s):return [r for r in self.rows if a<=r['event_observation']['event_id']<=b]
        with patch('resumed_usage.daily_records',side_effect=rows),patch('recovery_range.daily_records',side_effect=rows),patch('daily_empirical.evidence',side_effect=lambda db,rs,p,b:[Decimal(0)]*len(rs)):
            return self.engine.calculate(self.db,self.f.doc,self.obs,ZoneInfo("UTC"))
    def test_short_period_without_midnight_or_hour(self):
        result,reason=self.calculate()
        self.assertIsNone(reason);self.assertEqual((result['lower'],result['upper']),('2.00','2.00'))
        self.assertEqual(result['start']['event_id'],2)
        self.assertEqual(result['through'],self.rows[-1]['event_observation'])
        self.assertTrue(result['unknown_gaps_preserved']);self.assertFalse(result['prior_gap_included'])
        self.assertEqual(self.rows,self.original);self.assertEqual(self.policy['elapsed_start_event'],self.f.policy['elapsed_start_event'])
    def test_one_reading_not_reported_as_zero(self):
        self.obs['event_id']=2
        with self.assertRaisesRegex(ValueError,'awaiting_two'):self.calculate()
    def test_missing_origin_withholds_without_moving_it(self):
        self.rows=self.rows[1:]
        self.assertEqual(self.calculate(),(None,'unavailable'))
    def test_changed_endpoint_digest_rejected(self):
        self.obs['source_sha256']='f'*64
        with self.assertRaisesRegex(ValueError,'endpoint_changed'):self.calculate()
    def test_clock_change_withholds(self):
        self.rows[-1]['event_observation']['clock_id']='other';self.obs['clock_id']='other'
        self.assertEqual(self.calculate(),(None,'unavailable'))
    def test_unknown_gap_remains_in_bounds(self):
        self.rows[-1]['event_observation']['monotonic_us']+=60000000
        self.rows[-1]['event_observation']['captured_at']='2026-11-07T00:02:00+00:00'
        self.obs=dict(self.rows[-1]['event_observation'],segment_id=self.f.base['segment_id'])
        self.engine.policy['slow_allowance_ft3']=100
        result,reason=self.calculate();self.assertIsNone(reason)
        self.assertGreater(Decimal(result['upper']),Decimal(result['lower']))
        self.assertIsNone(self.rows[-1]['delta'])
    def test_work_limit_withholds_then_recovers(self):
        with patch('recovery_range.interval_edges',side_effect=WorkLimit):self.assertEqual(self.calculate(),(None,'rebuilding_saved_history'))
        self.assertIsNotNone(self.calculate()[0])
    def test_restart_preserves_anchor_and_result(self):
        before=self.calculate();self.engine=ResumedPublisher(None,self.policy)
        self.assertEqual(self.calculate(),before)
    def test_invalid_anchor_option(self):
        for v in (True,0,-1,'2',2147483648):
            with self.subTest(v=v),self.assertRaises(ValueError):validate(dict(self.policy,resumed_start_event=v))
        self.assertEqual(validate(self.policy),self.policy)
    def test_publish_acknowledgement_and_failure(self):
        result,_=self.calculate();out=Mock(base='test',interval=10,config={'unique_id':'u','device':{}})
        store=Mock();store.connect.return_value.__enter__=Mock(return_value=self.db);store.connect.return_value.__exit__=Mock(return_value=False)
        self.engine.store=store
        with patch.dict(os.environ,TZ='UTC'),patch('resumed_usage.fresh_range',return_value=self.obs),patch.object(self.engine,'calculate',return_value=(result,None)):
            out._publish.side_effect=[None,ValueError('unconfirmed')]
            with self.assertRaises(ValueError):self.engine.publish(out,{'format':self.f.doc})
            self.assertIsNone(self.engine.last_good)
            out._publish.side_effect=None;self.engine.publish(out,{'format':self.f.doc})
            self.assertEqual(self.engine.last_good[0],result)
            self.assertEqual(json.loads(out._publish.call_args.args[1]),result)
    def test_failed_daily_and_hour_do_not_block_resumed_publisher(self):
        from mqtt_output import MqttOutput
        from contextlib import nullcontext
        out=Mock()
        out.performance.measure.return_value=nullcontext(Mock())
        out.output_mode='gas_consumption';out.connected.is_set.return_value=True
        out.daily.publish.side_effect=ValueError('midnight missing')
        out.daily.recent.publish.side_effect=ValueError('hour missing')
        MqttOutput.publish_snapshot(out,{'saved':'only'})
        out.daily.resumed.publish.assert_called_once_with(out,{'saved':'only'})
        self.assertIsNone(out.resumed_error)
    def test_stale_capture_clears_published_range(self):
        result,_=self.calculate();self.engine.last_good=(result,10)
        out=Mock(base='test',interval=10,config={'unique_id':'u','device':{}})
        with patch.dict(os.environ,TZ='UTC'),patch('resumed_usage.fresh_range',return_value=None):
            self.engine.publish(out,{'format':self.f.doc})
        self.assertIsNone(self.engine.last_good)
        self.assertEqual(out._publish.call_args.args,('test/resumed_range','{}'))
    def test_no_anchor_never_uses_old_elapsed_origin(self):
        self.engine.policy.pop('resumed_start_event')
        with self.assertRaisesRegex(ValueError,'awaiting_two'):self.calculate()
    def test_published_snapshot_independent_of_daily_and_hour(self):
        result,_=self.calculate();result['timezone']='UTC'
        pub=Mock(last_good=None,recent=Mock(last_good=None),resumed=Mock(last_good=(result,10)))
        wall=datetime.fromisoformat(result['through']['captured_at'])
        with patch.dict(os.environ,TZ='UTC'):
            self.assertEqual(snapshot(pub,now=11,wall=wall),{'resumed':result})
            self.assertEqual(snapshot(pub,now=671,wall=wall),{})

