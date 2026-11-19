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

    def test_slow_dial_conflict_uses_only_independent_register_bounds(self):
        # The saved endpoint permits two or more units. A separate slow-dial
        # comparison caps movement at one. No individual turn can be selected.
        with patch('recovery_range.interval_edges', return_value=[(2, 3, 0, 1)]):
            result, reason = self.calculate()
        self.assertIsNone(reason)
        self.assertEqual((result['lower'], result['upper']), ('2.00', '12.00'))
        self.assertEqual(result['refinement_status'], 'conflicting_saved_constraints')
        self.assertEqual(result['method'], 'saved_register_bands_v1')
        self.assertEqual(result['through'], self.rows[-1]['event_observation'])
        self.assertNotIn('estimate', result)
        self.assertEqual(self.rows, self.original)
        self.assertEqual(self.calculate()[0]['method'], 'saved_prefix_constraints_v1')

    def test_conflicting_interior_hundred_bucket_respects_endpoint_and_anchor(self):
        # Fine intermediate positions 109 then 104 cannot both be monotonic,
        # but both record the same hundred. The endpoint is allowed 112 or 117.
        rows = [self.f.f.row(i, sec, bands) for i, sec, bands in
                [(2, 1, [(100, 100)]), (3, 61, [(109, 109)]),
                 (4, 121, [(104, 104)]), (5, 181, [(112, 112), (117, 117)])]]
        for row in rows:
            row['event_observation'].update(format_id='b'*64, source_sha256='c'*64)
        rows[-1].update(upper_unbounded=False, observation_full_anchor_event_id=2,
                        minimum=9, maximum=14, anchor_captured_at=rows[0]['event_observation']['captured_at'])
        self.rows = rows
        self.obs = dict(rows[-1]['event_observation'], segment_id='s')
        before = copy.deepcopy(rows)
        with patch('recovery_range.interval_edges', return_value=[(2, 5, 0, 30)]):
            result, reason = self.calculate()
        self.assertIsNone(reason)
        self.assertEqual(result['method'], 'saved_register_envelopes_v1')
        self.assertEqual((result['lower'], result['upper']), ('12.00', '12.00'))
        self.assertTrue(result['unknown_gaps_preserved'])
        self.assertNotIn('estimate', result)
        self.assertEqual(self.rows, before)
        # An impossible segment minimum must still withhold.
        rows[-1].update(minimum=19, maximum=24)
        with patch('recovery_range.interval_edges', return_value=[(2, 5, 0, 30)]):
            self.assertIsNone(self.calculate()[0])

    def test_fallback_requires_compatible_clock_and_published_digest(self):
        with patch('recovery_range.interval_edges', return_value=[(2, 3, 0, 1)]):
            self.assertIsNotNone(self.calculate()[0])
            self.rows[-1]['event_observation']['clock_id'] = 'other'
            self.assertIsNone(self.calculate()[0])
            self.obs['source_sha256'] = 'f'*64
            with self.assertRaisesRegex(ValueError, 'endpoint_changed'):
                self.calculate()

    def test_intermediate_register_carry_keeps_both_hundreds(self):
        from daily_constraints import register_bands
        row = self.f.f.row(3, 61, [(199.9, 200.1), (410, 411)])
        self.assertEqual(register_bands(row, Decimal(1000), (2, 4)), [(100, 300), (400, 500)])
        self.assertEqual(register_bands(row, Decimal(1000), (2, 3))[0],
                         (Decimal('199.9'), Decimal('200.1')))

    def test_fallback_rechecks_target_after_earlier_coarse_checkpoint(self):
        from recovery_range import RecoveryRange
        rows = [self.f.f.row(i, 60*i, [(100+i, 100+i)]) for i in range(2, 8)]
        for r in rows:
            r['event_observation'].update(format_id='b'*64, source_sha256='c'*64)
        def saved(db, a, b, segment):
            return [r for r in rows if a <= r['event_observation']['event_id'] <= b]
        def solve(engine, end):
            return engine.calculate(None, self.f.f.day, ZoneInfo('UTC'), self.f.doc,
                                    dict(self.f.base, through=rows[end]['event_observation']),
                                    self.f.policy, {'c':('a'*64,'b'*64,1)})
        engine = RecoveryRange(register_only=True)
        with patch('recovery_range.daily_records', side_effect=saved), patch('recovery_range.CHUNK_EVENTS', 2):
            self.assertIsNone(solve(engine, -1)[1])
            self.assertEqual(engine.checkpoint[1]['event_id'], 6)
            replay, reason = solve(engine, -2)
            self.assertIsNone(reason)
            self.assertEqual(replay, solve(RecoveryRange(register_only=True), -2)[0])
            self.assertEqual((replay['lower'], replay['upper']), ('4.00', '4.00'))

    def test_missing_register_endpoint_withholds_conflict_fallback(self):
        from daily_constraints import InconsistentConstraints
        self.rows[-1]['absolute'] = {}
        with patch('recovery_range.interval_edges', side_effect=InconsistentConstraints('no common solution')):
            self.assertIsNone(self.calculate()[0])
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

