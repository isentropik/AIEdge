"""Synthetic ABI marshalling checks, not physical meter accuracy evidence."""
import os,unittest
from accounting_native import AccountingNative
from test_consumption import document

LIBRARY=os.environ.get('AIEDGE_ACCOUNTING_LIBRARY')

@unittest.skipUnless(LIBRARY,'accounting native library required')
class MaskedWrapperTests(unittest.TestCase):
    def setUp(self):
        self.native=AccountingNative(LIBRARY)
        self.trackers=[]
    def tracker(self):
        tracker=self.native.tracker(document(rate=.1));self.trackers.append(tracker);return tracker
    def tearDown(self):
        for tracker in self.trackers:tracker.close()
    def test_additive_capability_and_all_observed_parity(self):
        self.assertTrue(self.native.supports_masked)
        full,masked=self.tracker(),self.tracker()
        for tick,positions in ((1000000,[0.,0.]),(31000000,[.01,2.]),(61000000,[.02,4.])):
            self.assertEqual(full.observe(positions,tick,'test-a'),masked.observe_masked(positions,[True,True],tick,'test-a'))
    def test_unknown_none_marshals_without_stale_upper_value(self):
        tracker=self.tracker();tracker.observe([0.,0.],1000000,'test-a')
        result=tracker.observe_masked([None,2.],[False,True],31000000,'test-a')
        self.assertTrue(result['accepted']);self.assertAlmostEqual(result['value'],1.)
        with self.assertRaisesRegex(ValueError,'unobserved_accounting_position'):
            tracker.observe_masked([0.,4.],[False,True],61000000,'test-a')
        self.assertAlmostEqual(tracker.observe_masked([None,4.],[False,True],61000000,'test-a')['value'],2.)
    def test_strict_masks_and_positions_reject_before_native_mutation(self):
        tracker=self.tracker();tracker.observe([0.,0.],1000000,'test-a')
        for mask in ([0,1],[False,1],[False],[],None,[False,True,True]):
            with self.subTest(mask=mask),self.assertRaisesRegex(ValueError,'invalid_accounting_mask'):
                tracker.observe_masked([None,2.],mask,31000000,'test-a')
        for value in (None,float('nan'),float('inf'),True,-.1,10.,'2'):
            with self.subTest(value=value),self.assertRaisesRegex(ValueError,'invalid_accounting_positions'):
                tracker.observe_masked([None,value],[False,True],31000000,'test-a')
        self.assertAlmostEqual(tracker.observe_masked([None,2.],[False,True],31000000,'test-a')['value'],1.)
    def test_partial_bootstrap_and_missing_finest_do_not_create_anchor(self):
        tracker=self.tracker()
        for positions,mask in (([None,0.],[False,True]),([0.,None],[True,False]),([None,None],[False,False])):
            result=tracker.observe_masked(positions,mask,1000000,'test-a')
            self.assertFalse(result['accepted']);self.assertFalse(result['available']);self.assertIsNone(result['value'])
        self.assertTrue(tracker.observe([0.,0.],1000000,'test-a')['accepted'])
    def test_closed_handle_fails_and_legacy_wrapper_requires_every_position(self):
        tracker=self.tracker()
        with self.assertRaisesRegex(ValueError,'invalid_accounting_positions'):tracker.observe([None,0.],1000000,'test-a')
        tracker.close()
        with self.assertRaisesRegex(ValueError,'accounting_tracker_closed'):tracker.observe_masked([None,0.],[False,True],1000000,'test-a')

if __name__=='__main__':unittest.main()
