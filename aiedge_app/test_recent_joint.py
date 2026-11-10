"""Whole-hour projection, including a discrete exhaustive path oracle."""
import copy,itertools,random,unittest
from decimal import Decimal
from unittest.mock import patch
import test_recent_usage as fixtures
from datetime import date
from daily_constraints import WorkLimit


class RecentJointTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.RecentRangeTests();self.f.setUp()
        self.f.rows=[self.f.rows[i] for i in (0,15,30,45,60)]

    def domains(self,values):
        for row,choices in zip(self.f.rows,values):
            row['absolute']['bounds']['ranges']=[dict(lower=str(v),upper=str(v)) for v in choices]
            row['unresolved_gap']={'reason':'saved_timeout','delta':None}

    def test_later_hour_readings_remove_impossible_quarter_turn(self):
        self.domains([[100],[100,105],[101,106],[102,107],[103]])
        before=copy.deepcopy(self.f.rows);r=self.f.solve()
        self.assertEqual((r['hour']['lower'],r['hour']['upper']),('3.00','3.00'))
        self.assertEqual([(q['lower'],q['upper']) for q in r['quarters']],
                         [('0.00','0.00'),('1.00','1.00'),('1.00','1.00'),('1.00','1.00')])
        self.assertEqual(self.f.rows,before)
        self.assertEqual(r['quarter_constraint_scope'],'full_hour_saved_readings')

    def test_earlier_hour_readings_remove_impossible_quarter_turn(self):
        self.domains([[105],[100,105],[106],[107],[108]])
        r=self.f.solve()
        self.assertEqual(r['quarters'][1]['upper'],'1.00')

    def test_unresolved_extra_turn_remains_when_hour_allows_it(self):
        self.domains([[100],[100,105],[101,106],[102,107],[103,108]])
        r=self.f.solve();self.assertEqual(r['hour']['upper'],'8.00')
        self.assertEqual(r['quarters'][0]['upper'],'5.00')
        self.assertTrue(all(x['delta'] is None for x in self.f.rows))

    def test_cross_quarter_evidence_is_retained(self):
        self.domains([[100],[100,105],[101,106],[102,107],[103,108]])
        # A source-bound observed anchor crossing a quarter restricts its path.
        row=self.f.rows[2];start=self.f.rows[0]['event_observation']
        row.update(upper_unbounded=False,observation_full_anchor_event_id=start['event_id'],
                   anchor_captured_at=start['captured_at'],minimum='1',maximum='1')
        r=self.f.solve();self.assertEqual(r['quarters'][0]['upper'],'0.00')
        self.assertEqual(r['quarters'][1]['upper'],'1.00')

    def test_every_feasible_discrete_path_remains_inside_reported_ranges(self):
        rng=random.Random(60)
        for trial in range(50):
            values=[[100+i]+([105+i] if rng.choice([False,True]) else []) for i in range(5)]
            self.domains(values);before=copy.deepcopy(self.f.rows);r=self.f.solve()
            paths=[p for p in itertools.product(*values) if all(b>=a for a,b in zip(p,p[1:]))]
            self.assertTrue(paths)
            for path in paths:
                for q,a,b in zip(r['quarters'],path,path[1:]):
                    self.assertLessEqual(Decimal(q['lower']),b-a)
                    self.assertGreaterEqual(Decimal(q['upper']),b-a)
            self.assertTrue(all(Decimal(q['upper'])<=Decimal(r['hour']['upper']) for q in r['quarters']))
            self.assertEqual(self.f.rows,before)

    def test_inconsistent_full_hour_withholds_instead_of_inventing_zero(self):
        self.domains([[100],[105],[101],[102],[103]])
        with self.assertRaises(ValueError):self.f.solve()

    def test_joint_work_exhaustion_returns_no_partial_payload(self):
        from recent_usage import _tighten
        calls=[]
        def limited(*a,**kw):
            calls.append(kw.get('objective_events'))
            if len(calls)==3:raise WorkLimit()
            return _tighten(*a,**kw)
        with patch('recent_usage._tighten',side_effect=limited),self.assertRaises(WorkLimit):self.f.solve()
        self.assertEqual(len(calls),3)

    def test_objective_outside_saved_graph_is_rejected(self):
        from daily_constraints import _tighten,Budget
        first=self.f.rows[0]['event_observation'];last=self.f.rows[-1]['event_observation']
        baseline=dict(before=first,after=first,through=last,lower='0',upper='100')
        with self.assertRaisesRegex(ValueError,'invalid constraint objective'):
            _tighten(self.f.rows,date(2026,11,9),self.f.zone,self.f.document,baseline,Budget(),elapsed=True,objective_events=(1,999))
