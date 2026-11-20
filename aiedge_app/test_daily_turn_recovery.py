"""Calendar recovery uses saved evidence without assigning movement to an unknown gap."""
import json
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from unittest import TestCase
from unittest.mock import MagicMock, Mock, patch

from daily_constraints import InconsistentConstraints
from daily_range import COARSE_BASIS, daily_range


class DailyTurnRecoveryTests(TestCase):
    day = date(2026, 1, 5)
    midnight = datetime(2026, 1, 5, tzinfo=timezone.utc)
    format = dict(unit="ft3", pipeline_id="p", maximum_rate_per_second=1,
                  dials=[dict(value_per_revolution=n) for n in (10**7, 10**6, 10**5, 10**4, 1000, 5)])

    def rows(self):
        # The second segment's absolute interpretation jumps back two whole turns.
        # Both needle phases advance and the segment-local deltas remain valid.
        result = []
        for i,(secs,absolute,segment,anchor,amount) in enumerate((
                (-1,120,"a",1,0),(1,121,"a",1,1),(5,111,"b",3,0),(10,114,"b",3,3)),1):
            stamp=(self.midnight+timedelta(seconds=secs)).isoformat()
            obs=dict(event_id=i,camera="test",clock_id="k",context_id="c",format_id="f",
                     captured_at=stamp,monotonic_us=(secs+2)*1000000,source_sha256="1"*64)
            anchor_time=stamp if anchor==i else result[anchor-1]["event_observation"]["captured_at"]
            result.append(dict(event_id=i,event_observation=obs,unit="ft3",segment_id=segment,
                               minimum=amount,maximum=amount,upper_unbounded=False,
                               anchor_captured_at=anchor_time,observation_full_anchor_event_id=anchor,
                               unresolved_gap={"delta":None,"first_event":3} if segment=="b" else None,
                               absolute=dict(unit="ft3",provenance="temporal_consumption_bounds",
                                   bounds=dict(state="bounded",wraps_register=False,
                                               ranges=[dict(lower=absolute,upper=absolute)]))))
        return result

    def solve(self,rows,**opts):
        return daily_range(rows,self.day,timezone.utc,self.format,"f",{"c":("p","f",1)},**opts)

    def band(self,row,lo,hi=None):
        row["absolute"]["bounds"]["ranges"]=[dict(lower=lo,upper=lo if hi is None else hi)]

    def test_recovers_midnight_but_never_fills_the_gap(self):
        rows=self.rows(); original=deepcopy(rows)
        result=self.solve(rows)
        # Midnight can occur anywhere between the two observed positions.
        # The upper envelope keeps the rate allowance for the whole bracket.
        self.assertEqual((result['lower'],result['upper']),('3.00','9.00'))
        self.assertEqual(result['constraint_basis'],COARSE_BASIS)
        self.assertTrue(result['unknown_gaps_preserved'])
        for key,index in (('before',0),('after',1),('through',-1)):
            self.assertEqual(result[key],rows[index]['event_observation'])
        self.assertEqual(rows,original)

    def test_recovers_single_image_conflict_in_fine_solver(self):
        rows=self.rows()
        for row in rows[2:]:row['absolute']['provenance']='single_image'
        result=self.solve(rows)
        self.assertEqual(result['constraint_basis'],COARSE_BASIS)
        self.assertEqual(result['through'],rows[-1]['event_observation'])

    def test_preserves_fine_solution(self):
        rows=self.rows()
        self.band(rows[2],122);self.band(rows[3],125)
        with patch('daily_range._check_turn_continuity',side_effect=AssertionError):
            result=self.solve(rows)
        self.assertEqual((result['lower'],result['upper']),('4.00','5.00'))
        self.assertNotIn('constraint_basis',result)

    def test_missing_midnight_fails(self):
        with self.assertRaisesRegex(ValueError,'midnight'):
            self.solve(self.rows()[1:])

    def test_invalid_sources_after_initial_conflict_fail(self):
        for key,val in [('camera','other'),('format_id','other'),('clock_id','reset'),
                        ('monotonic_us',1),('context_id','unknown')]:
            with self.subTest(key=key):
                rows=self.rows();rows[-1]['event_observation'][key]=val
                with self.assertRaises(ValueError):self.solve(rows)

    def test_false_clockwise_phase_jump_fails(self):
        rows=self.rows()
        self.band(rows[0],120);self.band(rows[1],119)
        # Only two ft3 can flow; these phases would need four even without turn counts.
        with self.assertRaisesRegex(InconsistentConstraints,'dial positions'):self.solve(rows)

    def test_irreconcilable_coarse_register_fails(self):
        rows=self.rows()
        self.band(rows[0],220);self.band(rows[1],221)
        with self.assertRaises(InconsistentConstraints):self.solve(rows)

    def test_rollover_is_withheld(self):
        rows=self.rows(); rows[-1]['absolute']['bounds']['wraps_register']=True
        with self.assertRaisesRegex(ValueError,'rollover'):self.solve(rows)

    def test_inconsistent_segment_phase_fails(self):
        rows=self.rows();rows[-1].update(minimum=1,maximum=1)
        with self.assertRaisesRegex(InconsistentConstraints,'dial positions'):self.solve(rows)

    def test_rate_is_only_an_upper_bound(self):
        rows=self.rows()
        small=self.solve(rows,recovery_capacity_cfh=2160)
        normal=self.solve(rows)
        self.assertEqual(small['lower'],normal['lower'])
        self.assertLess(Decimal(small['upper']),Decimal(normal['upper']))
        with self.assertRaises(ValueError):self.solve(rows,recovery_capacity_cfh=1)

    def test_budget_exhaustion_withholds_recovery(self):
        with patch('daily_constraints.MAX_WORK',0):
            with self.assertRaisesRegex(ValueError,'work limit'):self.solve(self.rows())

    def test_other_geometries_do_not_relax(self):
        doc=dict(self.format,dials=self.format['dials'][:-1])
        with self.assertRaises(InconsistentConstraints):
            daily_range(self.rows(),self.day,timezone.utc,doc,'f')

    def test_phase_can_cross_zero(self):
        rows=self.rows()
        for row,value in zip(rows,(124,125,115,118)):
            self.band(row,value)
        self.assertEqual(self.solve(rows)['constraint_basis'],COARSE_BASIS)

    def test_disjoint_register_alternatives_do_not_force_one_hundred(self):
        rows=self.rows()
        for row in rows:
            primary,=row['absolute']['bounds']['ranges']
            row['absolute']['bounds']['ranges'].append(dict(lower=primary['lower']+100,
                                                           upper=primary['upper']+100))
        self.assertEqual(self.solve(rows)['constraint_basis'],COARSE_BASIS)

    def test_hundred_carry_and_dial_phase_must_fit_the_same_transition(self):
        rows=self.rows()
        self.band(rows[0],194);self.band(rows[1],204)
        # The coarse buckets touch and the phases agree. The actual move between
        # those buckets at this phase needs at least 5 ft3 in two seconds.
        rows[1].update(minimum=0,maximum=2)
        self.band(rows[2],204);self.band(rows[3],207)
        with self.assertRaisesRegex(InconsistentConstraints,'dial positions'):self.solve(rows)

    def test_unknown_turns_enclose_real_usage_across_midnight(self):
        # Enumerate possible midnight positions and metered gas used in the gap.
        # Force a mistaken whole-turn interpretation without changing any dial phase.
        for gap_use in (0, 1, 2, 3, 4):
            rows=self.rows()
            for row,value in zip(rows,(120,121,111+gap_use,114+gap_use)):
                self.band(row,value)
            result=self.solve(rows)
            for before_midnight in (Decimal(0),Decimal('0.5'),Decimal(1)):
                actual=1-before_midnight+gap_use+3
                self.assertLessEqual(Decimal(result['lower']),actual)
                self.assertGreaterEqual(Decimal(result['upper']),actual)

    def test_daily_publisher_uses_matching_meter_capacity_and_emits_the_midpoint(self):
        from daily_mqtt import DailyPublisher
        rows=self.rows()
        revision, pipeline='f'*64,'a'*64
        for row in rows:
            row['event_observation']['format_id']=revision
        format_doc=dict(self.format,pipeline_id=pipeline)
        store=MagicMock()
        db=store.connect.return_value.__enter__.return_value
        db.execute.return_value=[('c',pipeline,revision,1)]
        obs=dict(rows[-1]['event_observation'],segment_id=rows[-1]['segment_id'])
        output=Mock(base='meter',interval=30,config={'unique_id':'meter','device':{}})
        for configured_format,expected_rate in [(revision,'0.6'),('0'*64,'1')]:
            policy=dict(capacity_cfh=2160,slow_allowance_ft3=6,format_id=configured_format,pipeline_id=pipeline)
            pub=DailyPublisher(store,policy)
            with (patch.dict('os.environ',TZ='UTC'),patch('daily_mqtt.datetime',wraps=datetime) as clock,
                  patch('daily_mqtt.fresh_range',return_value=obs),
                  patch('daily_mqtt.daily_records',return_value=iter(rows)),
                  patch('daily_empirical.refine',side_effect=AssertionError('retried conflicting turns'))):
                clock.now.return_value=self.midnight
                pub.publish(output,{'format':format_doc})
            topic,encoded=output._publish.call_args.args
            self.assertEqual(topic,'meter/daily_range')
            payload=json.loads(encoded)
            self.assertEqual(payload['maximum_rate_per_second'],expected_rate)
            self.assertEqual(payload['through'],rows[-1]['event_observation'])
            midpoint=(Decimal(payload['lower'])+Decimal(payload['upper']))/2
            self.assertEqual(Decimal(payload['nominal_estimate']['value_ft3']),midpoint)
            self.assertIn('Recovered from midnight',payload['nominal_estimate']['assumption'])
            self.assertTrue(payload['unknown_gaps_preserved'])
