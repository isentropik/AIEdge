import unittest

from chart_rate_photos import ChartRatePhotos, comparison_allowance
from optical_rate import solve


class OpticalRateTests(unittest.TestCase):
    @staticmethod
    def replay(phases,slow,seconds=11,start=0,end=None):
        rows=[(i*seconds*1000,i*seconds,v-.05,v+.05,s) for i,(v,s) in enumerate(zip(phases,slow))]
        return solve(rows,start,end if end is not None else rows[-1][0],1700/3600,5,1000,6)

    def test_stationary_dials_never_add_unseen_turns(self):
        r=self.replay([1]*7,[20,None,20,None,20,None,20])
        self.assertEqual(r['use'],0)
        self.assertEqual(len(r['bands']),1)
        self.assertAlmostEqual(r['bands'][0][0],0)
        self.assertAlmostEqual(r['bands'][0][1],.1)

    def test_coarse_motion_selects_the_observed_winding(self):
        r=self.replay([1]*7,[20,None,24,None,29,None,35])
        self.assertAlmostEqual(r['use'],15)
        (lo,hi),=r['bands']
        self.assertAlmostEqual(lo,14.9)
        self.assertAlmostEqual(hi,15.1)

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
        self.assertEqual(len(result['bands']),1)
        self.assertEqual(result['use'],0)

    def test_motion_across_multiple_turns_survives_identical_clock_endpoints(self):
        r=self.replay([1,2,3,4,0,1,2,3,4,0,1],[None]*11)
        self.assertAlmostEqual(r['use'],10)
        (lo,hi),=r['bands']
        self.assertAlmostEqual(lo,9.9)
        self.assertAlmostEqual(hi,10.1)

    def test_jitter_on_either_side_of_zero_does_not_accumulate_turns(self):
        r=self.replay([.01,4.99,.01,4.99,.01],[None]*5)
        self.assertEqual(r['use'],0)
        self.assertLess(r['bands'][0][1],.11)

    def test_clock_tick_between_stationary_photos_does_not_create_a_partial_turn(self):
        r=self.replay([1]*7,[20,None,20.2,None,20.5,None,20.7],start=9000,end=59000)
        self.assertEqual(r['use'],0)
        (lo,hi),=r['bands']
        self.assertAlmostEqual(lo,0)
        self.assertAlmostEqual(hi,.1)

    def test_quiet_frames_either_side_of_a_missing_stretch_do_not_prove_zero(self):
        rows=[(t*1000,t,.95,1.05,None) for t in (0,10,190,200)]
        r=solve(rows,10000,190000,1700/3600,5,1000,6)
        self.assertIsNone(r['use'])
        self.assertEqual(r['bands'],[])

    def test_exact_photos_without_a_hidden_turn_still_support_a_short_interval(self):
        r=self.replay([1,2],[None,None],seconds=4)
        self.assertAlmostEqual(r['use'],1)
        self.assertEqual(len(r['bands']),1)

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
