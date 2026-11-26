import unittest

from chart_rate_photos import ChartRatePhotos, comparison_allowance
from optical_rate import solve


class OpticalRateTests(unittest.TestCase):
    @staticmethod
    def replay(phases,slow,seconds=11,start=0,end=None):
        rows=[(i*seconds*1000,i*seconds,v-.05,v+.05,s) for i,(v,s) in enumerate(zip(phases,slow))]
        return solve(rows,start,end if end is not None else rows[-1][0],1700/3600,5,1000,6)

    def test_quiet_slow_dial_removes_extra_turns_but_keeps_disjoint_bands(self):
        r=self.replay([1]*7,[20,None,20,None,20,None,20])
        self.assertEqual(r['use'],0)
        self.assertEqual(len(r['bands']),2)
        for actual,expected in zip(r['bands'],[[0,.1],[4.9,5.1]]):
            for x,y in zip(actual,expected):self.assertAlmostEqual(x,y)
        self.assertFalse(any(lo<=.531<=hi for lo,hi in r['bands']))

    def test_coarse_motion_selects_the_observed_winding(self):
        r=self.replay([1]*7,[20,None,24,None,29,None,35])
        self.assertAlmostEqual(r['use'],15)
        self.assertTrue(any(a<=r['use']<=b for a,b in r['bands']))
        self.assertGreater(r['bands'][0][0],5)

    def test_interpolated_clock_ticks_use_both_bracketing_exposures(self):
        r=self.replay([4.7,4.9,.1,.3],[999.7,999.9,.1,.3],seconds=4,start=2000,end=10000)
        self.assertAlmostEqual(r['use'],.4)
        self.assertEqual(len(r['bands']),1)
        self.assertLessEqual(r['bands'][0][0],.4)
        self.assertGreaterEqual(r['bands'][0][1],.4)

    def test_short_cadence_excludes_hidden_turn_even_with_broad_slow_error(self):
        self.assertEqual(len(self.replay([1]*7,[20]*7,seconds=6)['bands']),1)

    def test_inconsistent_optics_withhold_a_rate(self):
        r=self.replay([1,1,1],[0,17,22],seconds=2)
        self.assertIsNone(r['use'])
        self.assertEqual(r['bands'],[])

    def test_one_slow_photo_cannot_support_a_comparison(self):
        result=self.replay([1]*7,[None]*3+[20]+[None]*3)
        self.assertEqual(result,self.replay([1]*7,[None]*7))
        self.assertEqual(len(result['bands']),7)
        self.assertEqual(result['use'],0)

    def test_policy_is_specific_to_the_reviewed_format_and_pipeline(self):
        doc=dict(pipeline_id='p',dials=[dict(value_per_revolution=1000),dict(value_per_revolution=5)])
        policy=dict(format_id='f',pipeline_id='p',slow_allowance_ft3=6)
        self.assertEqual(comparison_allowance(doc,'f',policy),6)
        self.assertIsNone(comparison_allowance(doc,'other',policy))
        self.assertIsNone(comparison_allowance(doc,'f',dict(policy,pipeline_id='other')))

    def test_a_failed_transfer_blocks_the_whole_interval_before_reading_phases(self):
        import sqlite3
        db=sqlite3.connect(':memory:')
        self.addCleanup(db.close)
        db.executescript('CREATE TABLE capture_failure_boundaries(after_event_id);'
                         'CREATE TABLE consumption_segment_links(first_event);'
                         'INSERT INTO capture_failure_boundaries VALUES(8);')
        evidence=ChartRatePhotos().get(db,{},dict(camera='c',format_id='f'),6,0,600000,1,62,70)
        self.assertIsNone(evidence)
