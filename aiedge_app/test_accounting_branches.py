"""Synthetic bounded-path regressions; no private fixtures or accuracy claims."""
import os,random,unittest
from accounting_native import AccountingNative
LIBRARY=os.environ.get('AIEDGE_ACCOUNTING_LIBRARY')
BASE={'version':1,'pipeline_id':'a'*64,'unit':'ft3','maximum_rate_per_second':1700/3600,
      'dials':[{'index':i,'value_per_revolution':p,'position_error':.1} for i,p in enumerate([10000000,1000000,100000,10000,1000,5])]}
@unittest.skipUnless(LIBRARY,'host native accounting library required')
class BranchTests(unittest.TestCase):
    def setUp(self):self.native=AccountingNative(LIBRARY);self.handles=[]
    def tearDown(self):
        for t in self.handles:t.close()
    def tracker(self,doc=None):
        t=self.native.tracker(doc or BASE);self.handles.append(t);return t
    def phases(self,value,doc=BASE):return [(value%d['value_per_revolution'])/d['value_per_revolution']*10 for d in doc['dials']]
    def test_known_long_interval_retains_two_candidates_without_inventing_more(self):
        t=self.tracker();t.observe(self.phases(0),0,'test')
        for sec in range(12,121,6):
            r=t.observe(self.phases(0),sec*1000000,'test')
            self.assertTrue(r['accepted']);self.assertEqual(r['state'],'ambiguous');self.assertIsNone(r['value'])
            self.assertLessEqual(r['maximum'],5.10000001);self.assertEqual(r['minimum'],0)
    def test_real_hidden_turn_remains_included(self):
        t=self.tracker();t.observe(self.phases(0),0,'test')
        for sec in range(12,121,6):
            r=t.observe(self.phases(5),sec*1000000,'test')
            self.assertTrue(r['accepted']);self.assertLessEqual(r['minimum'],5);self.assertGreaterEqual(r['maximum'],5)
            self.assertIsNone(r['value'])
    def test_short_intervals_preserve_many_revolutions(self):
        t=self.tracker()
        for i in range(501):
            r=t.observe(self.phases(i*.5),i*6000000,'test');self.assertTrue(r['accepted'])
            if i:self.assertAlmostEqual(r['value'],i*.5)
    def test_stationary_noise_does_not_accumulate(self):
        t=self.tracker();t.observe(self.phases(100),0,'test')
        for i in range(1,1001):
            r=t.observe(self.phases(100+(.025 if i%2 else -.025)),i*6000000,'test')
            self.assertTrue(r['accepted']);self.assertLess(r['maximum'],.15);self.assertIsNone(r['value'])
    def test_partial_frames_do_not_reuse_coarse_positions(self):
        t=self.tracker();t.observe(self.phases(0),0,'test')
        for sec in range(12,121,6):
            r=t.observe_masked([None]*5+[0.0],[False]*5+[True],sec*1000000,'test')
            self.assertTrue(r['accepted']);self.assertEqual(r['state'],'ambiguous');self.assertLess(r['maximum'],5.11)
    def test_unbounded_rate_stays_unbounded(self):
        doc={k:v for k,v in BASE.items() if k!='maximum_rate_per_second'};t=self.tracker(doc)
        t.observe(self.phases(0),0,'test');r=t.observe(self.phases(0),6000000,'test')
        self.assertTrue(r['accepted']);self.assertTrue(r['upper_unbounded']);self.assertIsNone(r['value'])
    def test_invalid_clock_cannot_advance_or_clear_ambiguity(self):
        t=self.tracker();t.observe(self.phases(0),0,'test');r=t.observe(self.phases(0),12000000,'test')
        bad=t.observe(self.phases(0),18000000,'other');self.assertFalse(bad['accepted']);self.assertFalse(bad['current'])
        later=t.observe(self.phases(0),18000000,'test');self.assertEqual(later['maximum'],r['maximum'])
    def test_branch_budget_fails_closed(self):
        doc={'version':1,'pipeline_id':'a'*64,'unit':'ft3','maximum_rate_per_second':1,'dials':[{'index':0,'value_per_revolution':5,'position_error':.1}]}
        t=self.tracker(doc);t.observe([0],0,'test');r=t.observe([0],1000*1000000,'test')
        self.assertFalse(r['accepted']);self.assertFalse(r['current']);self.assertIsNone(r['value']);self.assertEqual(r['through_us'],0)
    def test_deterministic_replay(self):
        times=[0,12,18,24,30,36];runs=[]
        for _ in range(2):
            t=self.tracker();runs.append([t.observe(self.phases(0),sec*1000000,'test') for sec in times])
        self.assertEqual(*runs)
    def test_later_coarse_evidence_resolves_retained_candidates(self):
        t=self.tracker();anchor=self.phases(0);anchor[4]=.09
        t.observe(anchor,0,'test');first=t.observe(anchor,12000000,'test')
        self.assertEqual(first['state'],'ambiguous');self.assertIsNone(first['value'])
        for i in range(1,201):
            pos=self.phases(i*.5);pos[4]=(pos[4]+(.09 if i<200 else -.09))%10
            r=t.observe(pos,(12+i*6)*1000000,'test');self.assertTrue(r['accepted'])
        self.assertEqual(r['state'],'estimated');self.assertAlmostEqual(r['value'],100)
    def test_physical_paths_with_independent_bounded_noise_are_retained(self):
        # Ground truth is constructed independently, with variable cadence,
        # near-bound flow, wraps, independent noise, and missing coarse dials.
        for seed in range(30):
            rng=random.Random(seed);t=self.tracker();quantity=rng.uniform(200000,300000);initial=quantity;tick=0
            for i in range(120):
                if i:
                    dt=rng.uniform(3,18);quantity+=rng.uniform(0,.4722222222222222)*dt;tick+=round(dt*1e6)
                pos=[(p+rng.uniform(-.099,.099))%10 for p in self.phases(quantity)]
                mask=[True]*6 if i%3==0 else [False]*5+[True]
                r=t.observe_masked([p if flag else None for p,flag in zip(pos,mask)],mask,tick,'test')
                self.assertTrue(r['accepted'],(seed,i,r))
                self.assertLessEqual(r['minimum']-1e-6,quantity-initial,(seed,i,r))
                self.assertGreaterEqual(r['maximum']+1e-6,quantity-initial,(seed,i,r))
if __name__=='__main__':unittest.main(verbosity=2)
