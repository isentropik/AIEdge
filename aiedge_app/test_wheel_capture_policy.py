"""Synthetic generic scheduling constraints, without capture or flow guarantees."""
import copy,unittest
from wheel_capture_policy import recommend

class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.cap={'minimum_interval_seconds':1,'partial_recognition':True,'acquisition_seconds':.2,'processing_seconds':.3}
        self.cfg={'normal_interval_seconds':20,'urgent_interval_seconds':2,'full_refresh_seconds':60,'phase_probe_budget':.25,'uncertainty_probe_width':.1}
    def call(self,event):return recommend(event,self.cap,self.cfg)
    def test_static_recommends_partial_but_does_not_certify_hidden_turns(self):
        result=self.call({'observed_phase_speed':0})
        self.assertEqual(result['requested_mode'],'LAST_TWO');self.assertFalse(result['continuity_certified']);self.assertIsNone(result['physical_scalar']);self.assertTrue(result['history_event_required']);self.assertTrue(result['accounting_before_publication_required']);self.assertFalse(result['alignment_bypass'])
    def test_quality_gaps_restart_and_backpressure_require_full(self):
        for key in ('first','gap','restart','context_changed','quality_uncertain','pose_uncertain','phase_ambiguous','backpressure'):
            with self.subTest(key=key):
                result=self.call({key:True});self.assertEqual(result['requested_mode'],'FULL');self.assertIn(key,result['reasons']);self.assertTrue(result['uncertainty_retained']);self.assertEqual(result['requested_interval_seconds'],2)
    def test_generic_high_speed_exceeds_capability_and_withholds_guarantee(self):
        result=self.call({'observed_phase_speed':10})
        self.assertEqual(result['requested_interval_seconds'],.025);self.assertEqual(result['supported_interval_seconds'],1);self.assertEqual(result['requested_mode'],'FULL');self.assertIn('requested_cadence_not_supported',result['reasons']);self.assertFalse(result['continuity_certified'])
    def test_measured_serial_work_cost_limits_cadence(self):
        self.cap.update(acquisition_seconds=2,processing_seconds=3)
        result=self.call({'first':True});self.assertEqual(result['supported_interval_seconds'],5);self.assertIn('requested_cadence_not_supported',result['reasons'])
    def test_periodic_full_and_width_escalation(self):
        result=self.call({'full_age_seconds':60});self.assertEqual(result['requested_mode'],'FULL');self.assertIn('periodic_full',result['reasons'])
        result=self.call({'phase_interval_width':.1});self.assertEqual(result['requested_interval_seconds'],2);self.assertTrue(result['uncertainty_retained'])
    def test_unsupported_partial_requires_full(self):
        self.cap['partial_recognition']=False
        result=self.call({});self.assertIn('partial_recognition_unsupported',result['reasons']);self.assertEqual(result['requested_mode'],'FULL')
    def test_rejects_malformed_or_uncertified_configuration(self):
        for value in (-1,True,float('nan'),float('inf'),10**400,'1'):
            with self.subTest(value=value),self.assertRaises(ValueError):self.call({'observed_phase_speed':value})
        for key,value in [('gap',1),('phase_interval_width',-.1),('full_age_seconds',None)]:
            with self.subTest(key=key),self.assertRaises(ValueError):self.call({key:value})
        config=copy.deepcopy(self.cfg);config['urgent_interval_seconds']=21
        with self.assertRaises(ValueError):recommend({},self.cap,config)
        config['household_daily_usage']=1
        with self.assertRaises(ValueError):recommend({},self.cap,config)

if __name__=='__main__':unittest.main()
