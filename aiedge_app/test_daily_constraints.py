"""Offline tests; no camera, network, store writes or appliance assumptions."""
import copy
import itertools
import random
import unittest
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import patch

import daily_constraints as dc
from daily_range import daily_range, _legacy_range


class DailyConstraintsTests(unittest.TestCase):
    day = date(2026, 11, 7)
    document = dict(unit="ft3", maximum_rate_per_second=2,
                    dials=[dict(value_per_revolution=1000)])

    def row(self, event, second, values, provenance="temporal_consumption_bounds"):
        source = dict(event_id=event, captured_at=(datetime(2026, 11, 7, tzinfo=timezone.utc)
                      + timedelta(seconds=second)).isoformat(), monotonic_us=(second+100)*1000000,
                      camera="saved", clock_id="boot", context_id="c", format_id="f")
        return dict(unit="ft3", event_observation=source, segment_id="s", delta=None,
                    upper_unbounded=True, absolute=dict(unit="ft3", provenance=provenance,
                    bounds=dict(state="bounded", wraps_register=False,
                                ranges=[dict(lower=a, upper=b) for a, b in values])))

    def rows(self):
        return [self.row(1,-1,[(100,100)]), self.row(2,1,[(101,101)]),
                self.row(3,3,[(103,103)])]

    def solve(self, rows, document=None):
        return daily_range(iter(rows), self.day, timezone.utc, document or self.document, "f")

    def baseline(self, rows):
        return _legacy_range(rows, self.day, timezone.utc, self.document, "f")

    def test_midnight_remains_interval(self):
        result = self.solve(self.rows())
        self.assertEqual((result['lower'],result['upper']),('2.00','3.00'))

    def test_unknown_gaps_not_zero_filled(self):
        rows = [self.row(1,-1,[(100,100)]),self.row(2,1,[(100,100)]),
                self.row(3,100,[(100,100),(105,105),(110,110)])]
        result = self.solve(rows)
        self.assertEqual((result['lower'],result['upper']),('0.00','10.00'))
        self.assertTrue(all(r['delta'] is None for r in rows))

    def test_read_only_and_exact_endpoint(self):
        rows = self.rows(); original = copy.deepcopy(rows)
        result = self.solve(rows)
        self.assertEqual(rows, original)
        self.assertEqual(result['through'],rows[-1]['event_observation'])
        self.assertEqual(result['segment_id'],'s')

    def test_backward_pass_eliminates_earlier_band(self):
        rows = [self.row(1,-1,[(100,100),(105,105)]),self.row(2,1,[(105,105)]),
                self.row(3,2,[(106,106)])]
        result = self.solve(rows)
        self.assertEqual((result['lower'],result['upper']),('1.00','1.00'))

    def test_single_image_band_is_used(self):
        rows = [self.row(1,-2,[(100,110)]),self.row(2,-1,[(105,105)],'single_image'),
                self.row(3,1,[(105,105)]),self.row(4,3,[(108,108)])]
        result = self.solve(rows)
        self.assertEqual(result['before']['event_id'],2)
        self.assertEqual((result['lower'],result['upper']),('3.00','3.00'))

    def test_all_alternatives_retained(self):
        rows = [self.row(1,-1,[(100,100),(105,105)]),self.row(2,1,[(100,100),(105,105)]),
                self.row(3,10,[(110,110)])]
        result = self.solve(rows)
        self.assertEqual((result['lower'],result['upper']),('5.00','10.00'))

    def test_rounding_outward(self):
        rows = [self.row(1,-1,[(100,100)]),self.row(2,1,[('100.001','100.009')]),
                self.row(3,3,[('101.001','101.009')])]
        result = self.solve(rows)
        self.assertEqual((result['lower'],result['upper']),('0.99','1.01'))

    def test_configured_rate_only(self):
        rows = [self.row(1,-1,[(100,100)]),self.row(2,1,[(100,100)]),
                self.row(3,2,[(100,100),(105,105)])]
        self.assertEqual(self.solve(rows)['upper'],'0.00')
        doc = dict(self.document, maximum_rate_per_second=5)
        self.assertEqual(self.solve(rows,doc)['upper'],'5.00')

    def test_work_limit_returns_whole_baseline(self):
        rows = self.rows()
        with patch.object(dc,'MAX_WORK',0):
            self.assertEqual(self.solve(rows),self.baseline(rows))

    def test_time_limit_returns_whole_baseline(self):
        rows = self.rows()
        with patch.object(dc,'MAX_SECONDS',-1):
            self.assertEqual(self.solve(rows),self.baseline(rows))

    def test_band_limit_returns_baseline(self):
        rows = self.rows()
        with patch.object(dc,'MAX_BANDS',0):
            self.assertEqual(self.solve(rows),self.baseline(rows))

    def test_limit_during_branch_discards_partial_result(self):
        rows=self.rows(); original=dc.propagate; calls=[]
        def bounded(*args):
            calls.append(True)
            if len(calls)>1:raise dc.WorkLimit()
            return original(*args)
        with patch.object(dc,'propagate',side_effect=bounded):
            self.assertEqual(self.solve(rows),self.baseline(rows))
        self.assertEqual(len(calls),2)

    def test_unknown_provenance_not_used_to_narrow(self):
        rows=self.rows();rows[1]['absolute']['provenance']='unverified_guess'
        rows[1]['absolute']['bounds']['ranges']=[dict(lower=999,upper=999)]
        result=self.solve(rows)
        self.assertLessEqual(Decimal(result['lower']),2)
        self.assertGreaterEqual(Decimal(result['upper']),3)

    def test_exact_midnight_has_no_invented_bracket(self):
        rows=[self.row(1,0,[(100,100)]),self.row(2,1,[(101,101)])]
        result=self.solve(rows)
        self.assertEqual((result['lower'],result['upper']),('1.00','1.00'))
        self.assertEqual(result['before'],result['after'])

    def test_record_limit_never_truncates(self):
        with patch.object(dc,'MAX_RECORDS',2):
            with self.assertRaisesRegex(ValueError,'input limit'):
                self.solve(self.rows())

    def test_bad_single_image_band_rejected(self):
        rows = self.rows(); rows[1]['absolute']['provenance']='single_image'
        rows[1]['absolute']['bounds']['ranges']=[dict(lower=4,upper=3)]
        with self.assertRaisesRegex(ValueError,'bands'):
            self.solve(rows)

    def test_nan_rejected(self):
        rows=self.rows();rows[1]['absolute']['provenance']='single_image'
        rows[1]['absolute']['bounds']['ranges']=[dict(lower='NaN',upper=5)]
        with self.assertRaisesRegex(ValueError,'nonfinite'):
            self.solve(rows)

    def anchor(self, rows, event=1, stamp=None, lo=3, hi=3):
        rows[-1].update(upper_unbounded=False,observation_full_anchor_event_id=event,
                        anchor_captured_at=stamp or rows[0]['event_observation']['captured_at'],
                        minimum=lo, maximum=hi)

    def test_verified_anchor_constraint(self):
        rows=self.rows();self.anchor(rows)
        self.assertEqual(self.solve(rows)['upper'],'3.00')

    def test_anchor_contradiction_rejected(self):
        rows=self.rows();self.anchor(rows,lo=4,hi=4)
        with self.assertRaisesRegex(ValueError,'inconsistent'):
            self.solve(rows)

    def test_anchor_timestamp_mismatch_rejected(self):
        rows=self.rows();self.anchor(rows,stamp='not the anchor')
        with self.assertRaisesRegex(ValueError,'anchor timestamp'):
            self.solve(rows)

    def test_future_anchor_rejected(self):
        rows=self.rows();self.anchor(rows,event=99)
        with self.assertRaisesRegex(ValueError,'anchor'):
            self.solve(rows)

    def test_absent_earlier_anchor_not_invented(self):
        rows=self.rows()
        for r in rows:r['event_observation']['event_id']+=10
        self.anchor(rows,event=1)
        self.assertEqual(self.solve(rows)['upper'],'3.00')

    def test_duplicate_event_rejected(self):
        rows=self.rows();rows[1]['event_observation']['event_id']=1
        with self.assertRaisesRegex(ValueError,'source'):
            self.solve(rows)

    def test_missing_midnight_rejected(self):
        with self.assertRaisesRegex(ValueError,'bracketing'):
            self.solve(self.rows()[1:])

    def test_source_change_rejected(self):
        rows=self.rows();rows[-1]['event_observation']['clock_id']='new'
        with self.assertRaisesRegex(ValueError,'source changed'):
            self.solve(rows)

    def test_integer_exhaustive_oracle_never_excludes_feasible_usage(self):
        rng=random.Random(54)
        # Every feasible trajectory and integer midnight register in these tiny
        # point-band domains is independently enumerated, without the solver.
        checked=0
        for _ in range(100):
            choices=[sorted(rng.sample(range(8),rng.randint(1,4))) for _ in range(4)]
            feasible=[]
            for path in itertools.product(*choices):
                if all(0 <= path[i]-path[i-1] <= (4 if i==1 else 2) for i in range(1,4)):
                    feasible.extend(path[-1]-m for m in range(path[0],path[1]+1))
            if not feasible:continue
            rows=[self.row(i+1,t,[(x,x) for x in choices[i]]) for i,t in enumerate((-1,1,2,3))]
            result=self.solve(rows)
            self.assertLessEqual(Decimal(result['lower']),min(feasible))
            self.assertGreaterEqual(Decimal(result['upper']),max(feasible))
            checked+=1
        self.assertGreater(checked,15)


if __name__=='__main__':
    unittest.main()
